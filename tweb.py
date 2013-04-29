#!/usr/bin/env python3

import traceback

import tornado.ioloop
import tornado.web
import tornado.options
import tornado.template

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
    'app_banner', type=str, default='<h1>Tworld</h1>',
    help='name of app (html, appears in page header)')

tornado.options.define(
    'top_pages', type=str, multiple=True,
    help='additional pages served from templates')

tornado.options.define(
    'port', type=int, default=4000,
    help='port number to listen on')
tornado.options.define(
    'debug', type=bool,
    help='application debugging (see Tornado docs)')

tornado.options.parse_command_line()
opts = tornado.options.options

# Define application options which are always set.
appoptions = { 'xsrf_cookies': True }

# Pull out some of the config-file options to pass along to the application.
for key in [ 'debug', 'template_path', 'static_path' ]:
    val = getattr(opts, key)
    if val is not None:
        appoptions[key] = val

class MyWriteErrorHandler:
    def write_error(self, status_code, exc_info=None):
        if (status_code == 404):
            self.render('404.html')
            return
        exception = None
        if (exc_info):
            ls = [ tornado.escape.xhtml_escape(ln) for ln in traceback.format_exception(*exc_info) ]
            exception = ''.join(ls)
        self.render('error.html', status_code=status_code, exception=exception)

class MyStaticFileHandler(MyWriteErrorHandler, tornado.web.StaticFileHandler):
    pass

class MyErrorHandler(MyWriteErrorHandler, tornado.web.ErrorHandler):
    pass

class MyRequestHandler(MyWriteErrorHandler, tornado.web.RequestHandler):
    def head(self):
        pass

class MainHandler(MyRequestHandler):
    def get(self):
        self.render('main.html')

class TopPageHandler(MyRequestHandler):
    def initialize(self, page):
        self.page = page
    def get(self):
        self.render('top_%s.html' % (self.page,))

class TestHandler(MyRequestHandler):
    def get(self):
        self.render('test.html', foo=11, xsrf=self.xsrf_form_html())

# Core handlers.
handlers = [
    (r'/', MainHandler),
    (r'/test', TestHandler),
    ]

# Add in all the top_pages handlers.
for val in opts.top_pages:
    handlers.append( ('/'+val, TopPageHandler, {'page': val}) )

# Fallback 404 handler for everything else.
handlers.append( (r'.*', MyErrorHandler, {'status_code': 404}) )
        
application = tornado.web.Application(
    handlers,
    ui_methods={
        'tworld_app_title': lambda handler:opts.app_title,
        'tworld_app_banner': lambda handler:opts.app_banner,
        },
    **appoptions)

application.listen(opts.port)
tornado.ioloop.IOLoop.instance().start()
