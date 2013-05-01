#!/usr/bin/env python3

import traceback
import logging

import tornado.ioloop
import tornado.web
import tornado.gen
import tornado.options
import tornado.template
import tornado.escape

import motor

import twlib.session

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
appoptions = { 'xsrf_cookies': True }

# Pull out some of the config-file options to pass along to the application.
for key in [ 'debug', 'template_path', 'static_path', 'cookie_secret' ]:
    val = getattr(opts, key)
    if val is not None:
        appoptions[key] = val

# Mix-in class, which I used for several of the standard request handlers.
# It does several things.
        
class MyHandlerMixin:
    twsessionstatus = None
    twsession = None
    
    @tornado.gen.coroutine
    def find_current_session(self):
        """
        Look up the user's session, using the sessionid cookie.
        Sets twsessionstatus to be 'auth', 'unauth', or 'unknown' (if the
        auth server is unavailable).
        If this is never called (e.g., the error handler) then the status
        remains None.
        """
        res = yield tornado.gen.Task(self.application.twsessionmgr.find_session, self)
        if (res):
            (self.twsessionstatus, self.twsession) = res
        return True

    def extend_template_namespace(self, map):
        """
        Add session-related entries to the template namespace. This is
        required for all the handlers that use the "base.html" template,
        which is all of them.
        """
        map['twsessionstatus'] = self.twsessionstatus
        map['twsession'] = self.twsession
        return map
        
    def write_error(self, status_code, exc_info=None, error_text=None):
        """
        Render a custom error page. This is invoked if a handler throws
        an exception. We also call it manually, in some places.
        """
        if (status_code == 404):
            self.render('404.html')
            return
        if (status_code == 403):
            self.render('error.html', status_code=403, exception='Not permitted')
            return
        exception = ''
        if (error_text):
            exception = error_text
        if (exc_info):
            ls = [ ln for ln in traceback.format_exception(*exc_info) ]
            if (exception):
                exception = exception + '\n'
            exception = exception + ''.join(ls)
        self.render('error.html', status_code=status_code, exception=exception)

class MyErrorHandler(MyHandlerMixin, tornado.web.ErrorHandler):
    def get_template_namespace(self):
        # Call the appropriate super.
        map = tornado.web.ErrorHandler.get_template_namespace(self)
        map = self.extend_template_namespace(map)
        return map

class MyStaticFileHandler(MyHandlerMixin, tornado.web.StaticFileHandler):
    def get_template_namespace(self):
        # Call the appropriate super.
        map = tornado.web.ErrorHandler.get_template_namespace(self)
        map = self.extend_template_namespace(map)
        return map
    
class MyRequestHandler(MyHandlerMixin, tornado.web.RequestHandler):
    def get_template_namespace(self):
        # Call the appropriate super.
        map = tornado.web.RequestHandler.get_template_namespace(self)
        map = self.extend_template_namespace(map)
        return map
    
    def head(self):
        # Always permit HEAD requests.
        pass
    
    def get_current_user(self):
        # Look up the user name (email address, really) in the current
        # session.
        if self.twsession:
            return self.twsession['email']

class MainHandler(MyRequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield tornado.gen.Task(self.find_current_session)
        self.application.twlog.info('### myreq get getting on')
        if not self.current_user:
            try:
                name = self.get_cookie('tworld_name', None)
                name = tornado.escape.url_unescape(name)
            except:
                name = None
            self.render('main.html', init_name=name)
        else:
            self.render('main_auth.html')

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        yield tornado.gen.Task(self.find_current_session)
        name = self.get_argument('name', '')
        name = tornado.escape.squeeze(name.strip())
        password = self.get_argument('password', '')
        formerror = None
        if (not name):
            formerror = 'You must enter your user name or email address.'
        elif (not password):
            formerror = 'You must enter your password.'
        elif (password != 'x'): ### check password...
            formerror = 'That name and password do not match.'
        if formerror:
            self.render('main.html', formerror=formerror, init_name=name)
            return

        # Set a name cookie, for future form fill-in
        self.set_cookie('tworld_name', tornado.escape.url_escape(name),
                        expires_days=14)
        ### convert name to email address; get userid
        res = yield tornado.gen.Task(self.application.twsessionmgr.create_session, self, name)
        self.application.twlog.info('User signed in: %s (session %s)', name, res)
        self.redirect('/')

    def get_template_namespace(self):
        # Call super.
        map = MyRequestHandler.get_template_namespace(self)
        # Add a couple of default values. The handlers may or may not override
        # these Nones.
        map['formerror'] = None
        map['init_name'] = None
        return map

class LogOutHandler(MyRequestHandler):
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield tornado.gen.Task(self.find_current_session)
        self.application.twsessionmgr.remove_session(self)
        self.render('logout.html')

class TopPageHandler(MyRequestHandler):
    def initialize(self, page):
        self.page = page
        
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield tornado.gen.Task(self.find_current_session)
        self.render('top_%s.html' % (self.page,))

class TestHandler(MyRequestHandler):
    def get(self):
        self.render('test.html', foo=11, xsrf=self.xsrf_form_html())

# Core handlers.
handlers = [
    (r'/', MainHandler),
    (r'/logout', LogOutHandler),
    (r'/test', TestHandler),
    ]

# Add in all the top_pages handlers.
for val in opts.top_pages:
    handlers.append( ('/'+val, TopPageHandler, {'page': val}) )

# Fallback 404 handler for everything else.
handlers.append( (r'.*', MyErrorHandler, {'status_code': 404}) )

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


appoptions['static_handler_class'] = MyStaticFileHandler ### move

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
