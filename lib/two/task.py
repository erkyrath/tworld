import datetime

import tornado.gen

from twcommon.excepts import MessageException, ErrorMessageException

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

    def close(self):
        """Clean up any large member variables. This probably reduces
        ref cycles, or if not, keeps my brain tidy.
        """
        self.app = None
        self.cmdobj = None

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



def delay(dur, callback=None):
    """Delay N seconds. This must be invoked as
    yield tornado.gen.Task(app.delay, dur)
    """
    delta = datetime.timedelta(seconds=dur)
    return tornado.ioloop.IOLoop.current().add_timeout(delta, callback)
