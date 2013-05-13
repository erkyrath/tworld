
import datetime
import logging

import tornado.ioloop
import tornado.gen

import motor

import two.webconn
import two.playconn
import two.mongomgr
import two.commands
import two.task
import twcommon.misc
from twcommon import wcproto

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
        self.queue.append( (obj, connid, twwcid, twcommon.misc.now()) )
        
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

        (cmdobj, connid, twwcid, queuetime) = self.queue.pop(0)

        task = two.task.Task(self, cmdobj, connid, twwcid, queuetime)
        self.commandbusy = True

        # Handle the command.
        try:
            yield task.handle()
        except Exception as ex:
            self.log.error('Error handling task: %s', cmdobj, exc_info=True)

        # Resolve all changes resulting from the command. We do this
        # in a separate try block, so that if the command died partway,
        # we still display the partial effects.
        if task.is_writable():
            try:
                yield task.resolve()
            except Exception as ex:
                self.log.error('Error resolving task: %s', cmdobj, exc_info=True)

        starttime = task.starttime
        endtime = twcommon.misc.now()
        self.log.info('Finished command in %.3f ms (queued for %.3f ms)',
                      (endtime-starttime).total_seconds() * 1000,
                      (starttime-queuetime).total_seconds() * 1000)

        self.commandbusy = False
        task.close()

        # Keep popping, if the queue is nonempty.
        if self.queue:
            self.ioloop.add_callback(self.pop_queue)

