#!/usr/bin/env python3

import sys
import types
import logging

import tornado.options
import tornado.ioloop
import tornado.autoreload

sys.path.insert(0, '/Volumes/Zarfslab Tir/seltani/lib')

# Set up all the options. (Generally found in the config file.)

# Clever hack to parse a config file off the command line.
tornado.options.define(
    'config', type=str,
    help='configuration file',
    callback=lambda path: tornado.options.parse_config_file(path, final=False))

tornado.options.define(
    'python_path', type=str,
    help='Python modules directory (optional)')

tornado.options.define(
    'debug', type=bool,
    help='application debugging (see Tornado docs)')
tornado.options.define(
    'tworld_port', type=int, default=4001,
    help='port number for communication between tweb and tworld')

# Parse 'em up.
tornado.options.parse_command_line()
opts = tornado.options.options

if opts.python_path:
    sys.path.insert(0, opts.python_path)

rootlogger = logging.getLogger('')
rootlogger.setLevel(logging.DEBUG) ### or based on an options
if (rootlogger.handlers):
    roothandler = rootlogger.handlers[0]
else:
    roothandler = logging.StreamHandler(sys.stdout)
    rootlogger.addHandler(roothandler)
rootform = logging.Formatter('[%(levelname).1s %(asctime)s: %(module)s:%(lineno)d] %(message)s', '%b-%d %H:%M:%S')
roothandler.setFormatter(rootform)
### log rotation, see volityd.py again...

if opts.debug:
    tornado.autoreload.start()

import two.app

app = two.app.Tworld(opts)
app.listen()

tornado.ioloop.IOLoop.instance().start()
