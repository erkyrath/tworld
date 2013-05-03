#!/usr/bin/env python3

import sys
import logging
import socket

import tornado.web
import tornado.gen
import tornado.ioloop
import tornado.iostream
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
        # This will be the Motor (MongoDB) connection. We'll open it in the
        # first monitor_mongo_status call.
        self.mongo = None
        self.mongodb = None   # will be mongo[mongo_database]
        self.mongoavailable = False  # true if self.mongo exists and is open
        self.mongotimerbusy = False  # true while monitor_mongo_status runs

        # This will be the Tworld connection. Handled by monitor_tworld_status.
        self.tworld = None
        self.tworldavailable = False  # true if self.tworld exists and is ready
        self.tworldtimerbusy = False
        
        # Set up a session manager (for web client sessions).
        self.twsessionmgr = tweblib.session.SessionMgr(self)

        # And a connection table (for talking to tworld).
        self.twconntable = tweblib.connections.ConnectionTable(self)

        # Grab the same logger that tornado uses.
        self.twlog = logging.getLogger("tornado.general")

        # When the IOLoop starts, we'll set up periodic tasks.
        tornado.ioloop.IOLoop.instance().add_callback(self.init_timers)

    def init_timers(self):
        self.twlog.info('Launching timers')

        ioloop = tornado.ioloop.IOLoop.instance()
        
        # The mongo status monitor. We set up one call immediately, and then
        # try again every five seconds.
        ioloop.add_callback(self.monitor_mongo_status)
        res = tornado.ioloop.PeriodicCallback(self.monitor_mongo_status, 5000)
        res.start()

        # The tworld status monitor. Same deal.
        ioloop.add_callback(self.monitor_tworld_status)
        res = tornado.ioloop.PeriodicCallback(self.monitor_tworld_status, 5000)
        res.start()

    @tornado.gen.coroutine
    def monitor_mongo_status(self):
        if (self.mongotimerbusy):
            self.twlog.warning('monitor_mongo_status: already in flight; did a previous call jam?')
            return
        self.mongotimerbusy = True
        
        if (self.mongoavailable):
            try:
                res = yield motor.Op(self.mongo.admin.command, 'ping')
                if (not res):
                    self.twlog.error('monitor_mongo_status: Mongo client not alive')
                    self.mongoavailable = False
            except Exception as ex:
                self.twlog.error('monitor_mongo_status: Mongo client not alive: %s', ex)
                self.mongoavailable = False
            if (not self.mongoavailable):
                self.mongo.disconnect()
                self.mongo = None
                self.mongodb = None
            
        if (not self.mongoavailable):
            try:
                self.mongo = motor.MotorClient()
                res = yield motor.Op(self.mongo.open)
                ### maybe authenticate to a database?
                self.mongodb = self.mongo[opts.mongo_database]
                self.mongoavailable = True
                self.twlog.info('monitor_mongo_status: Mongo client open')
            except Exception as ex:
                self.mongoavailable = False
                self.twlog.error('monitor_mongo_status: Mongo client not open: %s', ex)
        
        self.mongotimerbusy = False

    @tornado.gen.coroutine
    def monitor_tworld_status(self):
        if (self.tworldtimerbusy):
            self.twlog.warning('monitor_tworld_status: already in flight; did a previous call jam?')
            return

        if (self.tworldavailable):
            # Nothing to do
            return
        
        self.tworldtimerbusy = True

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            # We do a sync connect, because I don't understand how the
            # async version works. (IOStream.connect seems to hang forever
            # when the other process is down?)
            sock.connect(('localhost', opts.tworld_port))
            sock.setblocking(0)
            self.tworld = tornado.iostream.IOStream(sock)
        except Exception as ex:
            self.tworldavailable = False
            self.twlog.error('monitor_tworld_status: Tworld socket would not open: %s', ex)
            self.tworldtimerbusy = False
            return
            
        self.twlog.info('monitor_tworld_status: Tworld socket open')
        self.tworldavailable = True
        self.tworldtimerbusy = False



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
