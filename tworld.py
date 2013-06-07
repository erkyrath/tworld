#!/usr/bin/env python3

"""
tworld: Copyright (c) 2013, Andrew Plotkin
(Available under the MIT License; see LICENSE file.)

This is the top-level script which acts as Tworld's core server.

Players do not connect directly to this process. The tweb server (the web
server process) connects to this; players connect to tweb. All game
commands are relayed to us through tweb.
"""

import sys
import types
import logging

import tornado.options
import tornado.ioloop
import tornado.autoreload


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
    'log_level', type=str, default=None,
    help='logging threshold (default usually WARNING)')

tornado.options.define(
    'tworld_port', type=int, default=4001,
    help='port number for communication between tweb and tworld')

tornado.options.define(
    'mongo_database', type=str, default='tworld',
    help='name of mongodb database')

# Parse 'em up.
tornado.options.parse_command_line()
opts = tornado.options.options

if opts.python_path:
    sys.path.insert(0, opts.python_path)

rootlogger = logging.getLogger('')
if opts.log_level:
    rootlogger.setLevel(opts.log_level)
if (rootlogger.handlers):
    roothandler = rootlogger.handlers[0]
else:
    roothandler = logging.StreamHandler(sys.stdout)
    rootlogger.addHandler(roothandler)
rootform = logging.Formatter('[%(levelname).1s %(asctime)s: %(module)s:%(lineno)d] %(message)s', '%b-%d %H:%M:%S')
roothandler.setFormatter(rootform)
### log rotation, see volityd.py again...

import twcommon.autoreload
import two.app
app = two.app.Tworld(opts)

if opts.debug:
    twcommon.autoreload.sethandler(app.autoreload_handler)
    tornado.autoreload.start()

tornado.ioloop.IOLoop.instance().start()
