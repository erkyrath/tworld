import datetime
import tornado.gen
import tornado.ioloop


def delay(dur, callback=None):
    """Delay N seconds. This must be invoked as
    yield tornado.gen.Task(twcommon.async.delay, dur)
    """
    delta = datetime.timedelta(seconds=dur)
    return tornado.ioloop.IOLoop.current().add_timeout(delta, callback)
