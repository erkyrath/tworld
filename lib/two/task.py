import datetime

import tornado.gen
from bson.objectid import ObjectId
import motor

import two.execute
from two.playconn import PlayerConnection
from twcommon.excepts import MessageException, ErrorMessageException

DIRTY_WORLD = 0x01  # Instance, really
DIRTY_LOCALE = 0x02
DIRTY_FOCUS = 0x04
DIRTY_POPULACE = 0x08
DIRTY_ALL = 0x0F  # All of the above

class Task(object):
    def __init__(self, app, cmdobj, connid, twwcid, queuetime):
        self.app = app
        self.log = app.log
        # The Namespace object that represents the command:
        self.cmdobj = cmdobj
        # Connection ID for player that sent this (or 0 if from a server):
        self.connid = connid
        # Connection ID for tweb that invoked this (or 0 if it came from
        # tworld itself):
        self.twwcid = twwcid
        # When this command was received by tworld:
        self.queuetime = queuetime
        # When we started working on the command:
        self.starttime = datetime.datetime.now()

        # This will be a set of change keys.
        self.changeset = None
        # This will map connection IDs to a bitmask of dirty bits.
        # Values in this map should always be nonzero; if a connection
        # is non-dirty, it should not be in the map.
        self.updateconns = None

    def close(self):
        """Clean up any large member variables. This probably reduces
        ref cycles, or if not, keeps my brain tidy.
        """
        self.app = None
        self.cmdobj = None
        self.updateconns = None
        self.changeset = None

    def is_writable(self):
        return (self.updateconns is not None)

    def set_writable(self):
        self.changeset = set()
        self.updateconns = {}

    def set_data_change(self, key):
        assert self.is_writable(), 'set_data_change: Task was never set writable'
        self.changeset.add(key)
        
    def set_dirty(self, ls, dirty):
        # ls may be a PlayerConnection, a uid (an ObjectId), or a list
        # of either. Or None.
        # dirty is one or more DIRTY flags.
        assert self.is_writable(), 'set_dirty: Task was never set writable'
        if ls is None:
            return

        if type(ls) not in (tuple, list):
            ls = ( ls, )

        for obj in ls:
            if isinstance(obj, PlayerConnection):
                val = self.updateconns.get(obj.connid, 0) | dirty
                self.updateconns[obj.connid] = val
            elif isinstance(obj, ObjectId):
                subls = self.app.playconns.get_for_uid(obj)
                if subls:
                    for conn in subls:
                        val = self.updateconns.get(conn.connid, 0) | dirty
                        self.updateconns[conn.connid] = val
            else:
                self.log.warning('write_event: unrecognized %s', obj)
        
    def write_event(self, ls, text):
        # ls may be a PlayerConnection, a uid (an ObjectId), or a list
        # of either. Or None.
        if ls is None:
            return

        if type(ls) not in (tuple, list):
            ls = ( ls, )

        for obj in ls:
            if isinstance(obj, PlayerConnection):
                obj.write({'cmd':'event', 'text':text})
            elif isinstance(obj, ObjectId):
                subls = self.app.playconns.get_for_uid(obj)
                if subls:
                    for conn in subls:
                        conn.write({'cmd':'event', 'text':text})
            else:
                self.log.warning('write_event: unrecognized %s', obj)
            
    @tornado.gen.coroutine
    def find_locale_players(self, notself=False):
        conn = self.app.playconns.get(self.connid)
        if not conn:
            return None
        
        playstate = yield motor.Op(self.app.mongodb.playstate.find_one,
                                   {'_id':conn.uid},
                                   {'iid':1, 'locid':1})
        if not playstate:
            return None
        iid = playstate['iid']
        if not iid:
            return None
        locid = playstate['locid']
        if not locid:
            return None
        
        cursor = self.app.mongodb.playstate.find({'iid':iid, 'locid':locid},
                                                 {'_id':1})
        people = []
        while (yield cursor.fetch_next):
            ostate = cursor.next_object()
            if notself and ostate['_id'] == conn.uid:
                continue
            people.append(ostate['_id'])
            
        return people
        
    @tornado.gen.coroutine
    def handle(self):
        """
        Carry out a command. (Usually from a player, but sometimes generated
        by the server itself.) 99% of tworld's work happens here.

        Any exception raised by this function is considered serious, and
        throws a full stack trace into the logs.
        """
        self.log.info('### handling message %s', self.cmdobj)

        cmdname = self.cmdobj.cmd
        connid = self.connid
        twwcid = self.twwcid

        if connid == 0:
            # A message not from any player!
            if twwcid == 0:
                # Internal message, from tworld itself.
                stream = None
            else:
                # This is from tweb, not relayed from a player.
                # (This is the rare case where we use twwcid; we have no
                # other path back.)
                stream = self.app.webconns.get(twwcid)

            try:
                if twwcid and not stream:
                    raise ErrorMessageException('Server message from completely unrecognized stream.')
                
                cmd = self.app.all_commands.get(cmdname, None)
                if not cmd:
                    raise ErrorMessageException('Unknown server command: "%s"' % (cmdname,))
            
                if not cmd.isserver:
                    raise ErrorMessageException('Command must be invoked by a player: "%s"' % (cmdname,))

                if not cmd.noneedmongo and not self.app.mongodb:
                    # Guess the database access is not going to work.
                    raise ErrorMessageException('Tworld has lost contact with the database.')

                if cmd.doeswrite:
                    # May cause display changes.
                    self.set_writable()
                
                res = yield cmd.func(self.app, self, self.cmdobj, stream)
                if res is not None:
                    self.log.info('Command "%s" result: %s', cmdname, res)
                
            except ErrorMessageException as ex:
                self.log.warning('Error message running "%s": %s', cmdname, str(ex))
            except MessageException as ex:
                pass

            # End of connid==0 case.
            return 

        conn = self.app.playconns.get(connid)

        # Command from a player (via conn). A MessageException here passes
        # an error back to the player.

        try:
            cmd = self.app.all_commands.get(cmdname, None)
            if not cmd:
                raise ErrorMessageException('Unknown player command: "%s"' % (cmdname,))

            if cmd.isserver:
                raise ErrorMessageException('Command may not be invoked by a player: "%s"' % (cmdname,))

            if not conn:
                # Newly-established connection. Only 'playeropen' will be
                # accepted. (Another twwcid case; we'll have to sneak the
                # stream in through the object.)
                if not cmd.preconnection:
                    raise ErrorMessageException('Tworld has not yet registered this connection.')
                assert cmd.name=='playeropen', 'Command not playeropen should have already been rejected'
                stream = self.app.webconns.get(twwcid)
                if not stream:
                    raise ErrorMessageException('Message from completely unrecognized stream')
                self.cmdobj._connid = connid
                self.cmdobj._stream = stream

            if not cmd.noneedmongo and not self.app.mongodb:
                # Guess the database access is not going to work.
                raise ErrorMessageException('Tworld has lost contact with the database.')

            if cmd.doeswrite:
                # May cause display changes.
                self.set_writable()
                
            res = yield cmd.func(self.app, self, self.cmdobj, conn)
            if res is not None:
                self.log.info('Command "%s" result: %s', cmdname, res)

        except ErrorMessageException as ex:
            # An ErrorMessageException is worth logging and sending back
            # to the player, but not splatting out a stack trace.
            self.log.warning('Error message running "%s": %s', cmdname, str(ex))
            try:
                # This is slightly hairy, because various error paths can
                # arrive here with no conn or no connid.
                if conn:
                    conn.write({'cmd':'error', 'text':str(ex)})
                else:
                    # connid may be zero or nonzero, really
                    stream = self.app.webconns.get(twwcid)
                    stream.write(wcproto.message(connid, {'cmd':'error', 'text':str(ex)}))
            except Exception as ex:
                pass

        except MessageException as ex:
            # A MessageException is not worth logging.
            try:
                # This is slightly hairy, because various error paths can
                # arrive here with no conn or no connid.
                if conn:
                    conn.write({'cmd':'message', 'text':str(ex)})
                else:
                    # connid may be zero or nonzero, really
                    stream = self.app.webconns.get(twwcid)
                    stream.write(wcproto.message(connid, {'cmd':'message', 'text':str(ex)}))
            except Exception as ex:
                pass

    @tornado.gen.coroutine
    def resolve(self):
        if not self.is_writable():
            return
        
        # Detach the update map. From this point on, the task is nonwritable
        # again!
        updateconns = self.updateconns
        changeset = self.changeset
        self.updateconns = None
        self.changeset = None

        # If nobody needs updating, we're done.
        if not (changeset or updateconns):
            return

        connections = self.app.playconns.all()

        # Go through the data changes, setting dirty bits as needed.
        # (But we try to do as little work as possible.)
        if changeset:
            for conn in connections:
                dirty = updateconns.get(conn.connid, 0)
                if not (dirty & DIRTY_LOCALE):
                    if not conn.localedependencies.isdisjoint(changeset):
                        dirty |= DIRTY_LOCALE
                if not (dirty & DIRTY_POPULACE):
                    if not conn.populacedependencies.isdisjoint(changeset):
                        dirty |= DIRTY_POPULACE
                if not (dirty & DIRTY_FOCUS):
                    if not conn.focusdependencies.isdisjoint(changeset):
                        dirty |= DIRTY_FOCUS
                if dirty:
                    updateconns[conn.connid] = dirty

        # Again, we might be done.
        if not updateconns:
            return

        self.log.info('### Must resolve updates: %s', updateconns)
        # If two connections are on the same player, this won't be
        # as efficient as it might be -- we'll generate text twice.
        # But that's a rare case.
        for (connid, dirty) in updateconns.items():
            try:
                conn = self.app.playconns.get(connid)
                yield two.execute.generate_update(self.app, conn, dirty)
            except Exception as ex:
                self.log.error('Error updating while resolving task: %s', self.cmdobj, exc_info=True)
        
