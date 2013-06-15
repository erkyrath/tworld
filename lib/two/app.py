
import sys
import datetime
import logging
import signal

import tornado.ioloop
import tornado.gen

import motor

import two.webconn
import two.playconn
import two.mongomgr
import two.commands
import two.symbols
import two.task
from two.evalctx import EvalPropContext
import twcommon.misc
import twcommon.autoreload
from twcommon import wcproto

class Tworld(object):
    def __init__(self, opts):
        self.opts = opts
        self.log = logging.getLogger('tworld')

        self.global_symbol_table = two.symbols.define_globals()
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

        # Miscellaneous.
        self.caughtinterrupt = False
        self.shuttingdown = False
        self.debugstacktraces = opts.show_stack_traces

        # When the IOLoop starts, we'll set up periodic tasks.
        tornado.ioloop.IOLoop.instance().add_callback(self.init_timers)
        
    def init_timers(self):
        self.ioloop = tornado.ioloop.IOLoop.current()
        try:
            self.webconns.listen()
        except Exception as ex:
            self.log.error('Unable to listen on socket: %s', ex)
            self.ioloop.stop()
            return
        self.mongomgr.init_timers()

        # Catch SIGINT (ctrl-C) and SIGHUP with our own signal handler.
        # The handler will try to close sockets cleanly and allow messages
        # to drain out.
        # (Not SIGKILL; we leave that as a shut-down-right-now option.)
        signal.signal(signal.SIGINT, self.interrupt_handler)
        signal.signal(signal.SIGHUP, self.interrupt_handler)

        # This periodic command kicks disconnected players to the void.
        # (Every three minutes, plus an uneven fraction of a second.)
        def func():
            self.queue_command({'cmd':'checkdisconnected'})
        res = tornado.ioloop.PeriodicCallback(func, 180100)
        res.start()

    def shutdown(self, reason=None):
        """This is called when an orderly shutdown is requested. (Either
        an admin request, or by the interrupt handler.) It should only
        be called as part of its own command queue event (shutdownprocess).

        We set the shuttingdown flag, which means the command queue is
        frozen. Then we wait a second, so that any outgoing messages can
        drain out of the write buffers. Then we close all the sockets.
        Then we wait a little more, to allow the sockets to finish closing.
        (IOStream doesn't seem to have an async close, seriously, wtf.) Then
        we exit the process.

        Reason 'autoreload' is a special case, triggered by the
        tornado.autoreload module. (Actually our patched version in
        twcommon.) That's the case where we're going to relaunch the
        process, rather than just exiting.
        """
        self.shuttingdown = True
        def shutdown_cont():
            if reason == 'autoreload':
                def shutdown_final():
                    self.log.info('Autoreloading for real.')
                    twcommon.autoreload.autoreload()
                    sys.exit(0)   # Should not reach here
            else:
                def shutdown_final():
                    self.log.info('Shutting down for real.')
                    sys.exit(0)
            self.mongomgr.close()
            self.webconns.close()
            self.log.info('Waiting 0.5 second for sockets to close...')
            self.ioloop.add_timeout(datetime.timedelta(seconds=0.5),
                                    shutdown_final)
            return
        self.log.info('Waiting 1 second for sockets to drain...')
        self.ioloop.add_timeout(datetime.timedelta(seconds=1.0),
                                shutdown_cont)
        
    def interrupt_handler(self, signum, stackframe):
        """This is called when Python catches a SIGINT (ctrl-C) signal.
        (It replaces the usual behavior of raising KeyboardInterrupt.)
        It's also called on SIGHUP. (But not SIGKILL.)

        We don't want to interrupt a command (in the command queue). So
        we queue up a special command which will shut down the process.
        But in case that doesn't fly -- say, if the queue is jammed up --
        we shut down immediately on the second interrupt.
        """
        if signum == signal.SIGINT:
            signame = 'Interrupt'
        elif signum == signal.SIGHUP:
            signame = 'Hangup'
        else:
            signame = 'Signal %s' % (signum,)
        if self.caughtinterrupt:
            self.log.error('%s! Shutting down immediately!', signame)
            raise KeyboardInterrupt()
        self.log.warning('%s! Queueing shutdown!', signame)
        self.caughtinterrupt = True
        # Gotta use a special method from inside a signal handler.
        self.ioloop.add_callback_from_signal(
            self.queue_command, {'cmd':'shutdownprocess'})

    def autoreload_handler(self):
        self.log.warning('Queueing autoreload shutdown!')
        self.queue_command({'cmd':'shutdownprocess', 'restarting':'autoreload'})

    def schedule_command(self, obj, delay):
        """Schedule a command to be queued, delay seconds in the future.
        This only handles commands internal to tworld (connid 0, twwcid 0).
        
        This does *not* put the scheduled command in the database. It
        is therefore unreliable; if tworld shuts down before the command
        runs, it will be lost.
        """
        self.ioloop.add_timeout(datetime.timedelta(seconds=delay),
                                lambda:self.queue_command(obj))

    def queue_command(self, obj, connid=0, twwcid=0):
        if self.shuttingdown:
            self.log.warning('Not queueing command, because server is shutting down')
            return
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

        EvalPropContext.context_stack.clear()

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
                task.resetticks()
                yield task.resolve()
            except Exception as ex:
                self.log.error('Error resolving task: %s', cmdobj, exc_info=True)

        if EvalPropContext.context_stack:
            self.log.error('EvalPropContext.context_stack has %d entries remaining at end of task!', len(EvalPropContext.context_stack))
            
        task.resetticks()
        starttime = task.starttime
        endtime = twcommon.misc.now()
        self.log.info('Finished command in %.3f ms (queued for %.3f ms); %d ticks max, %d ticks total',
                      (endtime-starttime).total_seconds() * 1000,
                      (starttime-queuetime).total_seconds() * 1000,
                      task.maxcputicks,
                      task.totalcputicks)

        self.commandbusy = False
        task.close()

        # Keep popping, if the queue is nonempty.
        if self.queue:
            self.ioloop.add_callback(self.pop_queue)

