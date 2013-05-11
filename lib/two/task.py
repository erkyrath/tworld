import datetime

import tornado.gen

import two.describe
from twcommon.excepts import MessageException, ErrorMessageException

DIRTY_LOCALE = 1
DIRTY_FOCUS = 2
DIRTY_POPULACE = 4
DIRTY_ALL = 7  # All of the above

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
        
    def set_conn_dirty(self, conn, dirty):
        assert self.is_writable(), 'set_conn_dirty: Task was never set writable'
        val = self.updateconns.get(conn.connid, 0) | dirty
        self.updateconns[conn.connid] = val

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
                dirty = updateconns.get(conn.id, 0)
                if not (dirty & DIRTY_LOCALE):
                    if not conn.localedependencies.isdisjoint(changeset):
                        dirty |= DIRTY_LOCALE
                if not (dirty & DIRTY_FOCUS):
                    if not conn.focusdependencies.isdisjoint(changeset):
                        dirty |= DIRTY_FOCUS
                ### populace?
                if dirty:
                    updateconns[conn.id] = dirty

        # Again, we might be done.
        if not updateconns:
            return

        self.log.info('### Must resolve updates: %s', updateconns)
        for (connid, dirty) in updateconns.items():
            try:
                conn = self.app.playconns.get(connid)
                ### Do this more efficiently, with dirty bits!
                yield two.describe.generate_locale(self.app, conn)
            except Exception as ex:
                self.log.error('Error updating while resolving task: %s', self.cmdobj, exc_info=True)
        

def delay(dur, callback=None):
    """Delay N seconds. This must be invoked as
    yield tornado.gen.Task(app.delay, dur)
    """
    delta = datetime.timedelta(seconds=dur)
    return tornado.ioloop.IOLoop.current().add_timeout(delta, callback)
