#!/usr/bin/env python3

import sys
import types
import logging
import tornado.ioloop

sys.path.insert(0, '/Volumes/Zarfslab Tir/seltani/lib')

# Lazy options setup, for now
options = types.SimpleNamespace(
    tworld_port = 4001)

rootlogger = logging.getLogger('')
rootlogger.setLevel(logging.DEBUG) ### or based on an options
roothandler = logging.StreamHandler(sys.stdout)
rootform = logging.Formatter('[%(levelname).1s %(asctime)s: %(module)s:%(lineno)d] %(message)s', '%b-%d %H:%M:%S')
roothandler.setFormatter(rootform)
rootlogger.addHandler(roothandler)
### log rotation, see volityd.py again...

import two.app

app = two.app.Tworld(options)
app.listen()

tornado.ioloop.IOLoop.instance().start()
