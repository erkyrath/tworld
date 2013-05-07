
import datetime
import logging

import tornado.ioloop
import tornado.gen

import two.webconn
import two.playconn
import two.mongomgr

import motor

from twcommon import wcproto
from twcommon.excepts import MessageException

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

    def queue_command(self, obj, connid, twwcid):
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
        ### You would love some kind of command dispatcher here.

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
                if not stream:
                    self.log.warning('Server message from completely unrecognized stream.')
                    return
                
            cmd = obj.cmd
            if cmd == 'connect':
                assert stream is not None, 'Tweb connect command from no stream.'
                stream.write(wcproto.message(0, {'cmd':'connectok'}))
                for connobj in obj.connections:
                    if not self.mongodb:
                        # Reject the players.
                        stream.write(wcproto.message(0, {'cmd':'playernotok', 'connid':connobj.connid, 'text':'The database is not available.'}))
                        continue
                    conn = self.playconns.add(connobj.connid, connobj.uid, connobj.email, stream)
                    stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':conn.connid}))
                    self.queue_command({'cmd':'refreshconn', 'connid':conn.connid}, 0, 0)
                    self.log.info('Player %s has reappeared (uid %s)', conn.email, conn.uid)
                return
            if cmd == 'disconnect':
                for (connid, conn) in self.playconns.as_dict().items():
                    if conn.twwcid == obj.twwcid:
                        try:
                            self.playconns.remove(connid)
                        except:
                            pass
                self.log.warning('Tweb has disconnected; now %d connections remain', len(self.playconns.as_dict()))
                return
            if cmd == 'logplayerconntable':
                self.playconns.dumplog()
                return
            if cmd == 'refreshconn':
                # Refresh one connection (not all the player's connections!)
                conn = self.playconns.get(obj.connid)
                newobj = {'cmd':'refresh', 'locale':'You are in a place.', 'focus':None, 'world':{'world':'Start', 'scope':'(Personal instance)', 'creator':'Created by Somebody'}}
                conn.stream.write(wcproto.message(obj.connid, newobj))
                return
            raise Exception('Unknown server command "%s": %s' % (cmd, obj))

        conn = self.playconns.get(connid)

        """####
        if conn is None:
            # Newly-established connection. Only 'playeropen' is acceptable.
            # (Another twwcid case, because there's no conn yet.)
            stream = self.webconns.get(twwcid)
            if not stream:
                self.log.warning('Message from completely unrecognized stream.')
                return
            if obj.cmd != 'playeropen':
                # Pass back an error.
                try:
                    stream.write(wcproto.message(connid, {'cmd':'error', 'text':'Tworld has not yet registered this connection.'}))
                except:
                    pass
                return
            if not self.mongodb:
                # Reject the players anyhow.
                try:
                    stream.write(wcproto.message(0, {'cmd':'playernotok', 'connid':connid, 'text':'The database is not available.'}))
                except:
                    pass
                return
            # Add entry to player connection table.
            try:
                conn = self.playconns.add(connid, obj.uid, obj.email, stream)
                conn.stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':connid}))
                self.queue_command({'cmd':'refreshconn', 'connid':connid}, 0, 0)
                self.log.info('Player %s has connected (uid %s)', conn.email, conn.uid)
            except Exception as ex:
                self.log.error('Failed to ack new playeropen: %s', ex)
            return
        ####"""
        
        # Command from a player (via conn). A MessageException here passes
        # an error back to the player.

        try:
            cmd = self.all_commands.get(obj.cmd, None)
            if not cmd:
                raise MessageException('Unknown player command: "%s"' % (obj.cmd,))

            if cmd.isserver:
                raise MessageException('Command may not be invoked by a player: "%s"' % (obj.cmd,))

            if not conn:
                # Newly-established connection. Only 'playeropen' will be
                # accepted. (Another twwcid case; we'll have to sneak the
                # stream in through the object.)
                if not cmd.preconnection:
                    raise MessageException('Tworld has not yet registered this connection.')
                assert cmd.name=='playeropen', 'Command not playeropen should have already been rejected'
                stream = self.webconns.get(twwcid)
                if not stream:
                    raise MessageException('Message from completely unrecognized stream')
                obj._connid = connid
                obj._stream = stream

            if not cmd.noneedmongo and not self.mongodb:
                # Guess the database access is not going to work.
                raise MessageException('Tworld has lost contact with the database.')

            res = yield tornado.gen.Task(cmd.func, self, obj, conn)

        except MessageException as ex:
            # A MessageException is worth logging and sending back to the
            # player, but not splatting out a stack trace.
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

