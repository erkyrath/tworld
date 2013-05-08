
import datetime
import logging

import tornado.ioloop
import tornado.gen

import two.webconn
import two.playconn
import two.mongomgr

import motor

from twcommon import wcproto
from twcommon.excepts import MessageException, ErrorMessageException

import two.commands

class Tworld(object):
    def __init__(self, opts):
        self.opts = opts
        self.log = logging.getLogger('tworld')

        self.all_commands = two.commands.define_commands()
        
        # This will be self.mongomgr.mongo[mongo_database], when that's
        # available.
        self.mongodb = None

        self.webconns = two.webconn.WebConnectionTable(self)
        self.playconns = two.playconn.PlayerConnectionTable(self)
        self.mongomgr = two.mongomgr.MongoMgr(self)

        # The command queue.
        self.queue = []
        self.commandbusy = False

        # When the IOLoop starts, we'll set up periodic tasks.
        tornado.ioloop.IOLoop.instance().add_callback(self.init_timers)
        
    def init_timers(self):
        self.ioloop = tornado.ioloop.IOLoop.current()
        self.webconns.listen()
        self.mongomgr.init_timers()

    def queue_command(self, obj, connid=0, twwcid=0):
        if type(obj) is dict:
            obj = wcproto.namespace_wrapper(obj)
        # If this command was caused by a message from tweb, twwcid is
        # its ID number. We will rarely need this.
        self.queue.append( (obj, connid, twwcid, datetime.datetime.now()) )
        
        if not self.commandbusy:
            self.ioloop.add_callback(self.pop_queue)

    @tornado.gen.coroutine
    def pop_queue(self):
        if self.commandbusy:
            self.log.warning('pop_queue called when already busy!')
            return

        if not self.queue:
            self.log.warning('pop_queue called when already empty!')
            return

        self.commandbusy = True

        (obj, connid, twwcid, queuetime) = self.queue.pop(0)

        starttime = datetime.datetime.now()

        try:
            yield tornado.gen.Task(self.handle_command, obj, connid, twwcid, queuetime)
        except Exception as ex:
            self.log.error('Error handling command: %s', obj, exc_info=True)

        endtime = datetime.datetime.now()
        self.log.info('Finished command in %.3f ms (queued for %.3f ms)',
                      (endtime-starttime).total_seconds() * 1000,
                      (starttime-queuetime).total_seconds() * 1000)
        
        self.commandbusy = False

        # Keep popping, if the queue is nonempty.
        if self.queue:
            self.ioloop.add_callback(self.pop_queue)

    @tornado.gen.coroutine
    def handle_command(self, obj, connid, twwcid, queuetime):
        """
        Carry out a command. (Usually from a player, but sometimes generated
        by the server itself.) 99% of tworld's work happens here.

        Any exception raised by this function is considered serious, and
        throws a full stack trace into the logs.
        """
        self.log.info('### handling message %s', obj)

        if connid == 0:
            # A message not from any player!
            if twwcid == 0:
                # Internal message, from tworld itself.
                stream = None
            else:
                # This is from tweb, not relayed from a player.
                # (This is the rare case where we use twwcid; we have no
                # other path back.)
                stream = self.webconns.get(twwcid)

            try:
                if twwcid and not stream:
                    raise ErrorMessageException('Server message from completely unrecognized stream.')
                
                cmd = self.all_commands.get(obj.cmd, None)
                if not cmd:
                    raise ErrorMessageException('Unknown server command: "%s"' % (obj.cmd,))
            
                if not cmd.isserver:
                    raise ErrorMessageException('Command must be invoked by a player: "%s"' % (obj.cmd,))

                if not cmd.noneedmongo and not self.mongodb:
                    # Guess the database access is not going to work.
                    raise ErrorMessageException('Tworld has lost contact with the database.')
                
                res = yield tornado.gen.Task(cmd.func, self, obj, stream)
                
            except ErrorMessageException as ex:
                self.log.warning('Error message running "%s": %s', obj.cmd, str(ex))
            except MessageException as ex:
                pass

            # End of connid==0 case.
            return 

        conn = self.playconns.get(connid)

        # Command from a player (via conn). A MessageException here passes
        # an error back to the player.

        try:
            cmd = self.all_commands.get(obj.cmd, None)
            if not cmd:
                raise ErrorMessageException('Unknown player command: "%s"' % (obj.cmd,))

            if cmd.isserver:
                raise ErrorMessageException('Command may not be invoked by a player: "%s"' % (obj.cmd,))

            if not conn:
                # Newly-established connection. Only 'playeropen' will be
                # accepted. (Another twwcid case; we'll have to sneak the
                # stream in through the object.)
                if not cmd.preconnection:
                    raise ErrorMessageException('Tworld has not yet registered this connection.')
                assert cmd.name=='playeropen', 'Command not playeropen should have already been rejected'
                stream = self.webconns.get(twwcid)
                if not stream:
                    raise ErrorMessageException('Message from completely unrecognized stream')
                obj._connid = connid
                obj._stream = stream

            if not cmd.noneedmongo and not self.mongodb:
                # Guess the database access is not going to work.
                raise ErrorMessageException('Tworld has lost contact with the database.')

            res = yield tornado.gen.Task(cmd.func, self, obj, conn)

        except ErrorMessageException as ex:
            # An ErrorMessageException is worth logging and sending back
            # to the player, but not splatting out a stack trace.
            self.log.warning('Error message running "%s": %s', obj.cmd, str(ex))
            try:
                # This is slightly hairy, because various error paths can
                # arrive here with no conn or no connid.
                if conn:
                    conn.write({'cmd':'error', 'text':str(ex)})
                else:
                    # connid may be zero or nonzero, really
                    stream = self.webconns.get(twwcid)
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
                    stream = self.webconns.get(twwcid)
                    stream.write(wcproto.message(connid, {'cmd':'message', 'text':str(ex)}))
            except Exception as ex:
                pass

