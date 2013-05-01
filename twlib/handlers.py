
import traceback
import unicodedata

import tornado.web
import tornado.gen
import tornado.escape

import motor

import twlib.session
from twlib.misc import MessageException

class MyHandlerMixin:
    """
    Mix-in class, which I used for several of the standard request handlers.
    It does several things:
    - Custom error page
    - Utility method to figure out the current session
    - Set up default values for the base template
    """
    
    twsessionstatus = None
    twsession = None
    
    @tornado.gen.coroutine
    def find_current_session(self):
        """
        Look up the user's session, using the sessionid cookie.
        Sets twsessionstatus to be 'auth', 'unauth', or 'unknown' (if the
        auth server is unavailable).
        If this is never called (e.g., the error handler) then the status
        remains None. All the handlers which want to show the header-bar
        status need to call this.
        (It would be nice to call this automatically from the prepare()
        method, but that can't be async in Tornado 3.0. Maybe in 3.1.)
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
            error_text = 'Not permitted'
            if (exc_info):
                error_text = str(exc_info[1])
            self.render('error.html', status_code=403, exception=error_text)
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
    """Customization of tornado's ErrorHandler."""
    def get_template_namespace(self):
        # Call the appropriate super.
        map = tornado.web.ErrorHandler.get_template_namespace(self)
        map = self.extend_template_namespace(map)
        return map

class MyStaticFileHandler(MyHandlerMixin, tornado.web.StaticFileHandler):
    """Customization of tornado's StaticFileHandler."""
    def get_template_namespace(self):
        # Call the appropriate super.
        map = tornado.web.ErrorHandler.get_template_namespace(self)
        map = self.extend_template_namespace(map)
        return map
    
class MyRequestHandler(MyHandlerMixin, tornado.web.RequestHandler):
    """Customization of tornado's RequestHandler. Used for all my
    page-specific handlers.
    """
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
    """Top page: the login form.
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield tornado.gen.Task(self.find_current_session)
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

        # If the "register" form was submitted, jump to the other page.
        if (self.get_argument('register', None)):
            self.redirect('/register')
            return

        # Apply canonicalizations to the name and password.
        name = self.get_argument('name', '')
        name = unicodedata.normalize('NFKC', name)
        name = tornado.escape.squeeze(name.strip())
        password = self.get_argument('password', '')
        password = unicodedata.normalize('NFKC', password)
        password = password.encode()  # to UTF8 bytes
        
        formerror = None
        if (not name):
            formerror = 'You must enter your user name or email address.'
        elif (not password):
            formerror = 'You must enter your password.'
        if formerror:
            self.render('main.html', formerror=formerror, init_name=name)
            return

        try:
            res = yield tornado.gen.Task(self.application.twsessionmgr.find_player, self, name, password)
        except MessageException as ex:
            formerror = str(ex)
            self.render('main.html', formerror=formerror, init_name=name)
            return
            
        if not res:
            formerror = 'That name and password do not match.'
            self.render('main.html', formerror=formerror, init_name=name)
            return
        
        fieldname = name
        uid = res['_id']
        email = res['email']
        name = res['name']

        # Set a name cookie, for future form fill-in. This is whatever the
        # user entered in the form (name or email)
        self.set_cookie('tworld_name', tornado.escape.url_escape(fieldname),
                        expires_days=14)

        res = yield tornado.gen.Task(self.application.twsessionmgr.create_session, self, uid, email, name)
        self.application.twlog.info('User signed in: %s (session %s)', email, res)
        self.redirect('/')

    def get_template_namespace(self):
        # Call super.
        map = MyRequestHandler.get_template_namespace(self)
        # Add a couple of default values. The handlers may or may not override
        # these Nones.
        map['formerror'] = None
        map['init_name'] = None
        return map

class RegisterHandler(MyRequestHandler):
    """The page for registering a new account.
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield tornado.gen.Task(self.find_current_session)
        self.render('register.html')

    def get_template_namespace(self):
        # Call super.
        map = MyRequestHandler.get_template_namespace(self)
        # Add a couple of default values. The handlers may or may not override
        # these Nones.
        map['formerror'] = None
        return map

class LogOutHandler(MyRequestHandler):
    """The sign-out page.
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield tornado.gen.Task(self.find_current_session)
        self.application.twsessionmgr.remove_session(self)
        # Now reload the session status. Also override the out-of-date
        # get_template_namespace entries.
        yield tornado.gen.Task(self.find_current_session)
        self.render('logout.html',
                    twsessionstatus=self.twsessionstatus,
                    twsession=self.twsession)

class TopPageHandler(MyRequestHandler):
    """Handler for miscellaneous top-level pages ("about", etc.)
    """
    def initialize(self, page):
        self.page = page
        
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield tornado.gen.Task(self.find_current_session)
        self.render('top_%s.html' % (self.page,))

class TestHandler(MyRequestHandler):
    """Debugging -- will go away eventually.
    """
    def get(self):
        self.render('test.html', foo=11, xsrf=self.xsrf_form_html())

