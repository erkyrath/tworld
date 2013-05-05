
import datetime
import logging

import tornado.ioloop
import tornado.gen

import two.webconn
import two.playconn

from twcommon import wcproto

class Tworld(object):
    def __init__(self, opts):
        self.opts = opts
        self.log = logging.getLogger('tworld')
        
        self.webconns = two.webconn.WebConnectionTable(self)
        self.playconns = two.playconn.PlayerConnectionTable(self)

        # The command queue.
        self.queue = []
        self.commandbusy = False

    def listen(self):
        self.webconns.listen()

    def queue_command(self, tup, twwcid):
        # If this command was caused by a message from tweb, twwcid is
        # its ID number. We will rarely need this.
        self.log.info('### received message %s', tup)
        self.queue.append( (tup, twwcid, datetime.datetime.now()) )
        
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

        (tup, twwcid, queuetime) = self.queue.pop(0)

        starttime = datetime.datetime.now()

        try:
            yield tornado.gen.Task(self.handle_command, tup, twwcid, queuetime)
        except Exception as ex:
            self.log.error('error handling command: %s', tup, exc_info=True)

        endtime = datetime.datetime.now()
        self.log.info('finished command in %.3f ms (queued for %.3f ms)',
                      (endtime-starttime).total_seconds() * 1000,
                      (starttime-queuetime).total_seconds() * 1000)
        
        self.commandbusy = False

        # Keep popping, if the queue is nonempty.
        if self.queue:
            tornado.ioloop.IOLoop.instance().add_callback(self.pop_queue)

    @tornado.gen.coroutine
    def handle_command(self, tup, twwcid, queuetime):
        self.log.info('### handling message %s', tup)

        (connid, raw, obj) = tup
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
                    conn = self.playconns.add(connobj.connid, connobj.uid, stream)
                    stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':conn.connid}))
            return

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
            # Add entry to player connection table.
            try:
                conn = self.playconns.add(connid, obj.uid, stream)
                conn.stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':connid}))
            except Exception as ex:
                self.log.error('Failed to ack new playeropen: %s', ex)
            return
        
        # This message needs to do something. Something which may
        # involve a lot of database access.
        #### playerclose case...

        if obj.cmd == 'say':
            val = 'You say, \u201C%s\u201D' % (obj.text,)
            conn.stream.write(wcproto.message(conn.connid, {'cmd':'event', 'text':val}))
