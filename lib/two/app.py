
import datetime
import logging

import tornado.ioloop
import tornado.gen

import two.webconn
import two.playconn
import two.mongomgr

from twcommon import wcproto

class Tworld(object):
    def __init__(self, opts):
        self.opts = opts
        self.log = logging.getLogger('tworld')
        
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
        self.webconns.listen()
        self.mongomgr.init_timers()

    def queue_command(self, obj, connid, twwcid):
        # If this command was caused by a message from tweb, twwcid is
        # its ID number. We will rarely need this.
        self.log.info('### received message %s', obj)
        self.queue.append( (obj, connid, twwcid, datetime.datetime.now()) )
        
        if not self.commandbusy:
            tornado.ioloop.IOLoop.instance().add_callback(self.pop_queue)

    @tornado.gen.coroutine
    def pop_queue(self):
        if self.commandbusy:
            self.log.warning('pop_queue called when already busy!')
            return

        if not self.queue:
            self.log.warning('### queue is empty now')
            return

        self.commandbusy = True

        (obj, connid, twwcid, queuetime) = self.queue.pop(0)

        starttime = datetime.datetime.now()

        try:
            yield tornado.gen.Task(self.handle_command, obj, connid, twwcid, queuetime)
        except Exception as ex:
            self.log.error('error handling command: %s', obj, exc_info=True)

        endtime = datetime.datetime.now()
        self.log.info('finished command in %.3f ms (queued for %.3f ms)',
                      (endtime-starttime).total_seconds() * 1000,
                      (starttime-queuetime).total_seconds() * 1000)
        
        self.commandbusy = False

        # Keep popping, if the queue is nonempty.
        if self.queue:
            tornado.ioloop.IOLoop.instance().add_callback(self.pop_queue)

    @tornado.gen.coroutine
    def handle_command(self, obj, connid, twwcid, queuetime):
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
                        stream.write(wcproto.message(0, {'cmd':'playernotok', 'connid':connobj.connid}))
                        continue
                    conn = self.playconns.add(connobj.connid, connobj.uid, connobj.email, stream)
                    stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':conn.connid}))
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
            raise Exception('Unknown server command "%s": %s' % (cmd, obj))

        conn = self.playconns.get(connid)
        
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
                    stream.write(wcproto.message(0, {'cmd':'playernotok', 'connid':connid}))
                except:
                    pass
                return
            # Add entry to player connection table.
            try:
                conn = self.playconns.add(connid, obj.uid, obj.email, stream)
                conn.stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':connid}))
                self.log.info('Player %s has connected (uid %s)', conn.email, conn.uid)
            except Exception as ex:
                self.log.error('Failed to ack new playeropen: %s', ex)
            return
        
        # This message needs to do something. Something which may
        # involve a lot of database access.
        cmd = obj.cmd

        if not self.mongodb:
            # Guess the database access is not going to work.
            try:
                conn.stream.write(wcproto.message(connid, {'cmd':'error', 'text':'Tworld has lost contact with mongo.'}))
            except Exception as ex:
                pass
            return
        
        if cmd == 'playerclose':
            self.log.info('Player %s has disconnected (uid %s)', conn.email, conn.uid)
            try:
                self.playconns.remove(connid)
            except Exception as ex:
                self.log.error('Failed to remove on playerclose %d: %s', connid, ex)
            return

        if cmd == 'say':
            for oconn in self.playconns.all():
                if conn.uid == oconn.uid:
                    val = 'You say, \u201C%s\u201D' % (obj.text,)
                else:
                    val = '%s says, \u201C%s\u201D' % (conn.email, obj.text,)
                try:
                    oconn.stream.write(wcproto.message(oconn.connid, {'cmd':'event', 'text':val}))
                except Exception as ex:
                    self.log.error('Unable to write to %d: %s', oconn.connid, ex)
            return

        if cmd == 'uiprefs':
            ### Could we handle this in tweb? I guess, if we cared.
            self.log.info('### Player set uiprefs %s', obj.map.__dict__)
            ### write them to the database, when we have a database handle
            return
        
        raise Exception('Unknown player command "%s": %s' % (cmd, obj))
