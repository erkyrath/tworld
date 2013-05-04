#!/usr/bin/env python3

import sys
import logging

import tornado.web
import tornado.gen
import tornado.ioloop
import tornado.options

import motor

# Set up all the options. (Generally found in the config file.)

# Clever hack to parse a config file off the command line.
tornado.options.define(
    'config', type=str,
    help='configuration file',
    callback=lambda path: tornado.options.parse_config_file(path, final=False))

tornado.options.define(
    'template_path', type=str,
    help='template directory')
tornado.options.define(
    'static_path', type=str,
    help='static files directory')
tornado.options.define(
    'python_path', type=str,
    help='Python modules directory (optional)')

tornado.options.define(
    'app_title', type=str, default='Tworld',
    help='name of app (plain text, appears in <title>)')
tornado.options.define(
    'app_banner', type=str, default='Tworld',
    help='name of app (html, appears in page header <h1>)')

tornado.options.define(
    'top_pages', type=str, multiple=True,
    help='additional pages served from templates')

tornado.options.define(
    'port', type=int, default=4000,
    help='port number to listen on')
tornado.options.define(
    'debug', type=bool,
    help='application debugging (see Tornado docs)')

tornado.options.define(
    'tworld_port', type=int, default=4001,
    help='port number for communication between tweb and tworld')

tornado.options.define(
    'mongo_database', type=str, default='tworld',
    help='name of mongodb database')
tornado.options.define(
    'cookie_secret', type=str,
    help='cookie secret key (see Tornado docs)')

# Parse 'em up.
tornado.options.parse_command_line()
opts = tornado.options.options

if opts.python_path:
    sys.path.insert(0, opts.python_path)

# Now that we have a python_path, we can import the tworld-specific modules.

import tweblib.session
import tweblib.handlers
import tweblib.connections
import tweblib.servers

# Define application options which are always set.
appoptions = {
    'xsrf_cookies': True,
    'static_handler_class': tweblib.handlers.MyStaticFileHandler,
    }

# Pull out some of the config-file options to pass along to the application.
for key in [ 'debug', 'template_path', 'static_path', 'cookie_secret' ]:
    val = getattr(opts, key)
    if val is not None:
        appoptions[key] = val

# Core handlers.
handlers = [
    (r'/', tweblib.handlers.MainHandler),
    (r'/register', tweblib.handlers.RegisterHandler),
    (r'/logout', tweblib.handlers.LogOutHandler),
    (r'/play', tweblib.handlers.PlayHandler),
    (r'/admin', tweblib.handlers.AdminMainHandler),
    (r'/websocket', tweblib.handlers.PlayWebSocketHandler),
    (r'/test', tweblib.handlers.TestHandler),
    ]

# Add in all the top_pages handlers.
for val in opts.top_pages:
    handlers.append( ('/'+val, tweblib.handlers.TopPageHandler, {'page': val}) )

# Fallback 404 handler for everything else.
handlers.append( (r'.*', tweblib.handlers.MyErrorHandler, {'status_code': 404}) )

class TwebApplication(tornado.web.Application):
    def init_tworld(self):
        # The parsed options (all of them, not just the tornado options)
        self.twopts = opts
        
        # Grab the same logger that tornado uses.
        self.twlog = logging.getLogger("tornado.general")

        # This will be self.twservermgr.mongo[mongo_database], when that's
        # available.
        self.mongodb = None

        # Set up a session manager (for web client sessions).
        self.twsessionmgr = tweblib.session.SessionMgr(self)

        # And a server manager (for mongodb and tworld connections).
        self.twservermgr = tweblib.servers.ServerMgr(self)

        # And a connection table (for talking to tworld).
        self.twconntable = tweblib.connections.ConnectionTable(self)

        # When the IOLoop starts, we'll set up periodic tasks.
        tornado.ioloop.IOLoop.instance().add_callback(self.init_timers)

    def init_timers(self):
        self.twlog.info('Launching timers')
        self.twservermgr.init_timers()


application = TwebApplication(
    handlers,
    ui_methods={
        'tworld_app_title': lambda handler:opts.app_title,
        'tworld_app_banner': lambda handler:opts.app_banner,
        },
    **appoptions)

application.init_tworld()
application.listen(opts.port)
tornado.ioloop.IOLoop.instance().start()
