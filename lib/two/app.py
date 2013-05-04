
import datetime
import logging

import tornado.ioloop
import tornado.gen

import two.webconn

from twcommon import wcproto

class Tworld(object):
    def __init__(self, opts):
        self.opts = opts
        self.log = logging.getLogger('tworld')
        
        self.webconns = two.webconn.WebConnectionTable(self)

        # The command queue.
        self.queue = []
        self.commandbusy = False

    def listen(self):
        self.webconns.listen()

    def queue_command(self, tup, stream):
        self.log.info('### received message %s', tup)
        self.queue.append( (tup, stream, datetime.datetime.now()) )
        
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

        (tup, stream, queuetime) = self.queue.pop(0)

        starttime = datetime.datetime.now()

        try:
            yield tornado.gen.Task(self.handle_command, tup, stream, queuetime)
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
    def handle_command(self, tup, stream, queuetime):
        self.log.info('### handling message %s', tup)

        (connid, raw, obj) = tup
        if connid == 0:
            # This message is for us!
            cmd = obj.cmd
            if cmd == 'connect':
                ### look at cmd.connections array, install
                stream.write(wcproto.message(0, {'cmd':'connectok'}))
        else:
            # This message needs to do something. Something which may
            # involve a lot of database access.
            pass
