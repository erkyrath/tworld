#!/usr/bin/env python3

import logging

import tornado.ioloop
import tornado.web
import tornado.gen
import tornado.options

import motor

import twlib.session
import twlib.handlers

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
    'cookie_secret', type=str,
    help='cookie secret key (see Tornado docs)')
tornado.options.define(
    'debug', type=bool,
    help='application debugging (see Tornado docs)')

tornado.options.parse_command_line()
opts = tornado.options.options

# Define application options which are always set.
appoptions = {
    'xsrf_cookies': True,
    'static_handler_class': twlib.handlers.MyStaticFileHandler,
    }

# Pull out some of the config-file options to pass along to the application.
for key in [ 'debug', 'template_path', 'static_path', 'cookie_secret' ]:
    val = getattr(opts, key)
    if val is not None:
        appoptions[key] = val

# Core handlers.
handlers = [
    (r'/', twlib.handlers.MainHandler),
    (r'/logout', twlib.handlers.LogOutHandler),
    (r'/test', twlib.handlers.TestHandler),
    ]

# Add in all the top_pages handlers.
for val in opts.top_pages:
    handlers.append( ('/'+val, twlib.handlers.TopPageHandler, {'page': val}) )

# Fallback 404 handler for everything else.
handlers.append( (r'.*', twlib.handlers.MyErrorHandler, {'status_code': 404}) )

class TworldApplication(tornado.web.Application):
    def init_tworld(self):
        # Set up a Motor (MongoDB) connection. But don't open it yet.
        self.mongo = motor.MotorClient()
        
        # Set up a session manager.
        self.twsessionmgr = twlib.session.SessionMgr(self)

        # Grab the same logger that tornado uses.
        self.twlog = logging.getLogger("tornado.general")

        # When the IOLoop starts, we'll set up periodic tasks.
        tornado.ioloop.IOLoop.instance().add_callback(self.init_timers)

    @tornado.gen.coroutine
    def init_timers(self):
        self.twlog.info('Launching timers')
        try:
            res = yield motor.Op(self.mongo.open)
            self.twlog.info('Mongo client open')
        except Exception as ex:
            self.twlog.error('Mongo client not open: %s' % ex)


application = TworldApplication(
    handlers,
    ui_methods={
        'tworld_app_title': lambda handler:opts.app_title,
        'tworld_app_banner': lambda handler:opts.app_banner,
        },
    **appoptions)

application.init_tworld()
application.listen(opts.port)
tornado.ioloop.IOLoop.instance().start()
