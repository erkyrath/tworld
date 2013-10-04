"""
Utility class for sending email in the Tornado async environment.

This totally sloughs off the problem of async smtp. It just uses
tornado.process to invoke /bin/mail, or whatever external script you
have configured.
"""

import datetime

from bson.objectid import ObjectId
import tornado.gen
import tornado.process

from twcommon.excepts import MessageException

class Mailer(object):
    """Create a Mailer object, and then invoke it as often as you like
    to send email. (There's no reason to cache the thing long-term, though.
    It's cheap to create.)
    """
    
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = app.twlog

    @tornado.gen.coroutine
    def send(self, toaddr, subject, body):
        """Send a message. Raises an exception on failure.
        The From line is taken from the application config.
        """
            
        mailargs = self.app.twopts.email_command
        if not mailargs:
            raise MessageException('Unable to send recovery email -- email command not configured.')
        if not isinstance(mailargs, list):
            mailargs = mailargs.split()
            
        replace_array_el(mailargs, '$TO', toaddr)
        replace_array_el(mailargs, '$FROM', self.app.twopts.email_from)
        replace_array_el(mailargs, '$SUBJECT', subject)
        
        proc = tornado.process.Subprocess(mailargs,
                                          close_fds=True,
                                          stdin=tornado.process.Subprocess.STREAM,
                                          stdout=tornado.process.Subprocess.STREAM)

        # We'll read from the subprocess, logging all output,
        # and triggering a callback when its stdout closes.
        callkey = ObjectId() # unique key
        proc.stdout.read_until_close(
            (yield tornado.gen.Callback(callkey)),
            lambda dat:self.log.info('Email script output: %s', dat))
        
        # Now push in the message body.
        proc.stdin.write(body, callback=proc.stdin.close)
        proc.stdin.close()
        
        # And wait for that close callback.
        yield tornado.gen.Wait(callkey)

        # Wait a few more seconds for the process to exit, which it should.
        # (stdout has closed, so it's done.)
        # This is probably terrible use of the ioloop, but I don't want
        # to rely on set_exit_callback and its SIGCHILD weirdness.
        callkey = ObjectId() # unique key
        callback = yield tornado.gen.Callback(callkey)
        ticker = list(range(8))
        tickdelta = datetime.timedelta(seconds=0.25)
        ioloop = tornado.ioloop.IOLoop.instance()
        
        def func():
            if proc.proc.poll() is not None:
                # process has exited
                callback()
            elif not ticker:
                # out of ticks
                callback()
            else:
                # reduce the ticker, call again soon
                ticker.pop()
                ioloop.add_timeout(tickdelta, func)
        ioloop.add_callback(func)

        yield tornado.gen.Wait(callkey)
        
        res = proc.proc.poll()
        self.log.info('Email script result: %s', res)
        if res is None:
            raise MessageException('Email sending timed out.')
        if res:
            raise MessageException('Email sending failed, code %s.' % (res,))
        return


def replace_array_el(ls, was, to):
    """Utility function: replace an entry in an array, if present.
    """
    try:
        ls[ls.index(was)] = to
    except:
        pass
