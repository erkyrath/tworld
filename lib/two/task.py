import datetime

import tornado.gen
from bson.objectid import ObjectId
import motor

import two.execute
from two.playconn import PlayerConnection
import twcommon.misc
from twcommon.excepts import MessageException, ErrorMessageException
from twcommon.excepts import SymbolError, ExecRunawayException

DIRTY_WORLD    = 0x01  # World/instance data (creator, etc)
DIRTY_LOCALE   = 0x02  # Main location description
DIRTY_FOCUS    = 0x04  # Closeup view description
DIRTY_POPULACE = 0x08  # Who is in the location
DIRTY_TOOL     = 0x10  # Toolpane "control panel" description
DIRTY_ALL      = 0x1F  # All of the above

class LocContext(object):
    """
    Pure-data class. Sometimes -- in fact, often -- you want to tote around
    a bunch of location information in one object. This lets you do it.
    All of the fields are optional except uid (and really, we may run into
    some situation where uid is None also).
    """
    def __init__(self, uid, wid=None, scid=None, iid=None, locid=None):
        self.uid = uid
        self.wid = wid
        self.scid = scid
        self.iid = iid
        self.locid = locid

    def __repr__(self):
        ls = []
        if self.uid:
            ls.append( ('uid', self.uid) )
        if self.wid:
            ls.append( ('wid', self.wid) )
        if self.scid:
            ls.append( ('scid', self.scid) )
        if self.iid:
            ls.append( ('iid', self.iid) )
        if self.locid:
            ls.append( ('locid', self.locid) )
        val = ' '.join([ ('%s=%s' % (key, val)) for (key, val) in ls ])
        return '<LocContext %s>' % (val,)

class Task(object):
    """
    Context for the execution of one command in the command queue. This
    is used for both player and server commands. (For server commands,
    connid is zero. If the command came from within tworld, twwcid is
    also zero.)

    The basic life cycle is handle(), resolve(), close().
    """

    # Limit on how much work a task can do before we kill it.
    # (The task is actually run is several phases; this is the limit
    # per phase.)
    CPU_TICK_LIMIT = 4000

    # Limit on how deep the eval stack can get.
    STACK_DEPTH_LIMIT = 12
    
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
        self.starttime = twcommon.misc.now()

        # Hard limit on how much script code we'll execute for this task.
        self.cputicks = 0
        # Total of cputicks over all the phases of the task.
        self.totalcputicks = 0
        # Maximum cputicks for a phase.
        self.maxcputicks = 0

        # Maps uids to LocContexts.
        #self.loctxmap = {}

        # This will be a set of change keys.
        self.changeset = None
        # This will map connection IDs to a bitmask of dirty bits.
        # Values in this map should always be nonzero; if a connection
        # is non-dirty, it should not be in the map.
        self.updateconns = None

    def close(self):
        """Clean up any large member variables. This probably reduces
        ref cycles, or, if not, keeps my brain tidy.
        """
        self.app = None
        self.log = None
        self.cmdobj = None
        #self.loctxmap = None
        self.updateconns = None
        self.changeset = None

    def tick(self, val=1):
        self.cputicks = self.cputicks + 1
        if (self.cputicks > self.CPU_TICK_LIMIT):
            self.log.error('ExecRunawayException: User script exceeded tick limit!')
            raise ExecRunawayException('Script ran too long; aborting!')

    def resetticks(self):
        self.totalcputicks = self.totalcputicks + self.cputicks
        self.maxcputicks = max(self.maxcputicks, self.cputicks)
        self.cputicks = 0

    def is_writable(self):
        return (self.updateconns is not None)

    def set_writable(self):
        self.changeset = set()
        self.updateconns = {}

    def set_data_change(self, key):
        assert self.is_writable(), 'set_data_change: Task was never set writable'
        self.changeset.add(key)
        
    def set_data_changes(self, keylist):
        assert self.is_writable(), 'set_data_changes: Task was never set writable'
        self.changeset.update(keylist)
        
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

    def clear_loctx(self, uid):
        #if uid in self.loctxmap:
        #    del self.loctxmap[uid]
        pass

    @tornado.gen.coroutine
    def get_loctx(self, uid):
        #loctx = self.loctxmap.get(uid, None)
        #if loctx:
        #    return loctx

        playstate = yield motor.Op(self.app.mongodb.playstate.find_one,
                                   {'_id':uid},
                                   {'iid':1, 'locid':1, 'focus':1})
    
        iid = playstate['iid']
        if not iid:
            loctx = LocContext(uid, None)
            #self.loctxmap[uid] = loctx
            return loctx
        
        instance = yield motor.Op(self.app.mongodb.instances.find_one,
                              {'_id':iid})
        loctx = LocContext(uid, instance['wid'], instance['scid'],
                           iid, playstate['locid'])
        #self.loctxmap[uid] = loctx
        return loctx
            
    @tornado.gen.coroutine
    def find_locale_players(self, uid=None, notself=False):
        """Generate a list of all players in the same location as a given
        player. If no player is given, we presume the player that triggered
        the current event. (Which means that for server events, you must
        specify a uid or get None.)
        If notself is true, the list excludes the given player.
        """
        if uid is None:
            conn = self.app.playconns.get(self.connid)
            if not conn:
                return None
            uid = conn.uid
        
        playstate = yield motor.Op(self.app.mongodb.playstate.find_one,
                                   {'_id':uid},
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
            if notself and ostate['_id'] == uid:
                continue
            people.append(ostate['_id'])
        # cursor autoclose
            
        return people
        
    @tornado.gen.coroutine
    def find_location_players(self, iid, locid):
        """Generates a list of players in a given location. If locid
        is None, generates a list of players in the entire instance.
        """
        if locid:
            cursor = self.app.mongodb.playstate.find({'iid':iid, 'locid':locid},
                                                     {'_id':1})
        else:
            cursor = self.app.mongodb.playstate.find({'iid':iid},
                                                     {'_id':1})
        people = []
        while (yield cursor.fetch_next):
            ostate = cursor.next_object()
            people.append(ostate['_id'])
        # cursor autoclose
            
        return people
        
    @tornado.gen.coroutine
    def handle(self):
        """
        Carry out a command. (Usually from a player, but sometimes generated
        by the server itself.) 99% of tworld's work happens here.

        Any exception raised by this function is considered serious, and
        throws a full stack trace into the logs.
        """
        self.log.debug('Handling message "%s": %s', self.cmdobj.cmd, str(self.cmdobj)[:64])

        if self.app.shuttingdown:
            raise Exception('The server is shutting down.')

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
                # MessageException is usually not worth logging, but for
                # a server command, there's nobody else listening.
                self.log.info('Message running "%s": %s', cmdname, str(ex))

            # End of connid==0 case.
            return 

        conn = self.app.playconns.get(connid)

        # Command from a player (via conn). A MessageException here passes
        # an error back to the player.

        try:
            cmd = self.app.all_commands.get(cmdname, None)
            if not cmd:
                raise ErrorMessageException('Unknown player command: "%s"' % (cmdname,))

            # Check various limitations on the command.

            if cmd.isserver:
                raise ErrorMessageException('Command may not be invoked by a player: "%s"' % (cmdname,))

            if cmd.restrict == 'admin':
                player = yield motor.Op(self.app.mongodb.players.find_one,
                                        {'_id':conn.uid},
                                        {'admin':1})
                if not (player and player.get('admin', False)):
                    raise ErrorMessageException('Command may only be invoked by an administrator: "%s"' % (cmdname,))

            if cmd.restrict == 'creator':
                # Player must be the creator of the world he is in.
                ### And it must be an unstable version.
                # (Or an admin, anywhere.)
                player = yield motor.Op(self.app.mongodb.players.find_one,
                                        {'_id':conn.uid},
                                        {'admin':1, 'build':1})
                if not player:
                    raise ErrorMessageException('Player not found!')
                if (player.get('admin', False)):
                    # Admins always have creator rights.
                    pass
                elif (not player.get('build', False)):
                    raise ErrorMessageException('Command requires build permission: "%s"' % (cmdname,))
                else:
                    playstate = yield motor.Op(self.app.mongodb.playstate.find_one,
                                               {'_id':conn.uid},
                                               {'iid':1})
                    instance = yield motor.Op(self.app.mongodb.instances.find_one,
                                              {'_id':playstate['iid']})
                    world = yield motor.Op(self.app.mongodb.worlds.find_one,
                                           {'_id':instance['wid']})
                    if world.get('creator', None) != conn.uid:
                        raise ErrorMessageException('Command may only be invoked by this world\'s creator: "%s"' % (cmdname,))

            if not conn:
                # Newly-established connection. Only 'playeropen' will be
                # accepted. (Another twwcid case; we'll have to sneak the
                # stream in through the command object.)
                # (It's also possible that the connection closed since we
                # queued this, in which case we still reject.)
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
        """
        Resolve all side effects caused by data changes during this command.
        
        Some connections will have been marked dirty already, as the commands
        executed. The data changeset will also implicitly set connections
        dirty, based on their current dependencies. After working that all
        out, we send an update to each connection that needs it.

        We reset the tick count per connection, so that a crowded room doesn't
        wipe out the task.
        """
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
            #self.log.debug('Task changeset: %s', changeset)
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
                if not (dirty & DIRTY_TOOL):
                    if not conn.tooldependencies.isdisjoint(changeset):
                        dirty |= DIRTY_TOOL
                if dirty:
                    updateconns[conn.connid] = dirty

        # Again, we might be done.
        if not updateconns:
            return

        # self.log.info('Must resolve updates: %s', updateconns)
        
        # If two connections are on the same player, this won't be
        # as efficient as it might be -- we'll generate text twice.
        # But that's a rare case.
        for (connid, dirty) in updateconns.items():
            try:
                self.resetticks()
                conn = self.app.playconns.get(connid)
                yield two.execute.generate_update(self, conn, dirty)
            except Exception as ex:
                self.log.error('Error updating while resolving task: %s', self.cmdobj, exc_info=True)
        
