
import datetime
import traceback
import unicodedata
import json

import tornado.web
import tornado.gen
import tornado.escape
import tornado.websocket

import motor

import tweblib.session
from twcommon.excepts import MessageException

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
        auth server is unavailable). In the 'auth' case, also sets
        twsession to the session dict.
        
        If this is never called (e.g., the error handler) then the status
        remains None. This method should catch all its own exceptions
        (setting 'unknown').

        All the handlers which want to show the header-bar status need to
        call this. (It would be nice to call this automatically from the
        prepare() method, but that can't be async in Tornado 3.0. Maybe in
        3.1.)
        """
        res = yield self.application.twsessionmgr.find_session(self)
        if (res):
            (self.twsessionstatus, self.twsession) = res
        return True

    @tornado.gen.coroutine
    def get_config_key(self, key):
        """
        Look up a config key in the database. If not present, return None.
        """
        try:
            res = yield motor.Op(self.application.mongodb.config.find_one,
                                 { 'key': key })
        except Exception as ex:
            raise MessageException('Database error: %s' % (ex,))
        if not res:
            return None
        return res['val']
        
    def extend_template_namespace(self, map):
        """
        Add session-related entries to the template namespace. This is
        required for all the handlers that use the "base.html" template,
        which is all of them.
        (I suppose I could handle this by the right super implementation
        of get_template_namespace.)
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
            self.render('error.html', status_code=403, exctitle=None, exception=error_text)
            return
        exception = ''
        exctitle = None
        if (error_text):
            exception = error_text
        if (exc_info):
            exctitle = str(exc_info[1])
            ls = [ ln for ln in traceback.format_exception(*exc_info) ]
            if (exception):
                exception = exception + '\n'
            exception = exception + ''.join(ls)
        self.render('error.html', status_code=status_code, exctitle=exctitle, exception=exception)

class MyErrorHandler(MyHandlerMixin, tornado.web.ErrorHandler):
    """Customization of tornado's ErrorHandler."""
    def get_template_namespace(self):
        map = super().get_template_namespace()
        map = self.extend_template_namespace(map)
        return map

class MyStaticFileHandler(MyHandlerMixin, tornado.web.StaticFileHandler):
    """Customization of tornado's StaticFileHandler."""
    def get_template_namespace(self):
        map = super().get_template_namespace()
        map = self.extend_template_namespace(map)
        return map
    
class MyRequestHandler(MyHandlerMixin, tornado.web.RequestHandler):
    """Customization of tornado's RequestHandler. Used for all my
    page-specific handlers.
    """
    def get_template_namespace(self):
        map = super().get_template_namespace()
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
        yield self.find_current_session()
        if not self.twsession:
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
        yield self.find_current_session()

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
        
        locked = yield self.get_config_key('nologin')
        
        formerror = None
        if (not name):
            formerror = 'You must enter your player name or email address.'
        elif (not password):
            formerror = 'You must enter your password.'
        if formerror:
            self.render('main.html', formerror=formerror, init_name=name)
            return

        try:
            res = yield self.application.twsessionmgr.find_player(self, name, password)
        except MessageException as ex:
            formerror = str(ex)
            self.render('main.html', formerror=formerror, init_name=name)
            return
        
        if not res:
            formerror = 'The name and password do not match.'
            self.render('main.html', formerror=formerror, init_name=name)
            return
        
        fieldname = name
        uid = res['_id']
        email = res['email']
        name = res['name']

        if locked and not res.get('admin', None):
            formerror = 'Sign-ins are not allowed at this time.'
            self.render('main.html', formerror=formerror, init_name=name)
            return            

        # Set a name cookie, for future form fill-in. This is whatever the
        # player entered in the form (name or email)
        self.set_cookie('tworld_name', tornado.escape.url_escape(fieldname),
                        expires_days=14)

        res = yield self.application.twsessionmgr.create_session(self, uid, email, name)
        self.application.twlog.info('Player signed in: %s (session %s)', email, res)
        self.redirect('/play')

    def get_template_namespace(self):
        map = super().get_template_namespace()
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
        yield self.find_current_session()
        if self.twsession:
            self.redirect('/')
            return
        self.render('register.html')

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        yield self.find_current_session()

        # Apply canonicalizations to the name and password.
        name = self.get_argument('name', '')
        name = unicodedata.normalize('NFKC', name)
        name = tornado.escape.squeeze(name.strip())
        email = self.get_argument('email', '')
        email = unicodedata.normalize('NFKC', email)
        email = tornado.escape.squeeze(email.strip())
        password = self.get_argument('password', '')
        password = unicodedata.normalize('NFKC', password)
        password = password.encode()  # to UTF8 bytes
        password2 = self.get_argument('password2', '')
        password2 = unicodedata.normalize('NFKC', password2)
        password2 = password2.encode()  # to UTF8 bytes
        
        locked = yield self.get_config_key('noregistration')
        
        formerror = None
        formfocus = 'name'
        if locked:
            formerror = 'Player registration is not allowed at this time.'
        elif (not name):
            formerror = 'You must enter your player name.'
            formfocus = 'name'
        elif ('@' in name):
            formerror = 'Your player name may not contain the @ sign.'
            formfocus = 'name'
        elif (not email):
            formerror = 'You must enter an email address.'
            formfocus = 'email'
        elif ('@' not in email):
            formerror = 'Your email address must contain an @ sign.'
            formfocus = 'email'
        elif (not password):
            formerror = 'You must enter your password.'
            formfocus = 'password'
        elif (not password2):
            formerror = 'You must enter your password twice.'
            formfocus = 'password2'
        elif (len(password) < 6):
            formerror = 'Please use at least six characters in your password.'
            formfocus = 'password'
        elif (password != password2):
            formerror = 'The passwords you entered were not the same.'
            password2 = ''
            formfocus = 'password2'
        if formerror:
            self.render('register.html', formerror=formerror, formfocus=formfocus,
                        init_name=name, init_email=email, init_password=password, init_password2=password2)
            return

        try:
            res = yield self.application.twsessionmgr.create_player(self, email, name, password)
            self.application.twlog.info('Player created: %s (session %s)', email, res)
        except MessageException as ex:
            formerror = str(ex)
            self.render('register.html', formerror=formerror, formfocus=formfocus,
                        init_name=name, init_email=email, init_password=password, init_password2=password2)
            return
        
        # Set a name cookie, for future form fill-in. We use the player name.
        self.set_cookie('tworld_name', tornado.escape.url_escape(name),
                        expires_days=14)
        
        self.redirect('/play')
        
    def get_template_namespace(self):
        map = super().get_template_namespace()
        # Add a couple of default values. The handlers may or may not override
        # these Nones.
        map['formerror'] = None
        map['formfocus'] = 'name'
        map['init_name'] = None
        map['init_email'] = None
        map['init_password'] = None
        map['init_password2'] = None
        return map

class LogOutHandler(MyRequestHandler):
    """The sign-out page.
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield self.find_current_session()
        # End this sign-in session and kill the cookie.
        yield self.application.twsessionmgr.remove_session(self)
        # Clobber any open web sockets on this session. (But the player
        # might still be signed in on a different session.)
        ls = self.application.twconntable.as_dict().values()
        ls = [ conn for conn in ls if conn.sessionid == self.twsession['sid'] ]
        for conn in ls:
            try:
                conn.close('Your session has been signed out.')
            except Exception as ex:
                pass
        # Now reload the session status. Also override the out-of-date
        # get_template_namespace entries.
        yield self.find_current_session()
        self.render('logout.html',
                    twsessionstatus=self.twsessionstatus,
                    twsession=self.twsession)

class PlayHandler(MyRequestHandler):
    """Handler for the game itself.
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield self.find_current_session()
        if not self.twsession:
            self.redirect('/')
            return
        uiprefs = {}
        if self.application.mongodb is not None:
            cursor = self.application.mongodb.playprefs.find({'uid':self.twsession['uid']})
            while (yield cursor.fetch_next):
                pref = cursor.next_object()
                uiprefs[pref['key']] = pref['val']
        self.render('play.html', uiprefs=json.dumps(uiprefs))
        
class TopPageHandler(MyRequestHandler):
    """Handler for miscellaneous top-level pages ("about", etc.)
    """
    def initialize(self, page):
        self.page = page
        
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield self.find_current_session()
        self.render('top_%s.html' % (self.page,))

class AdminMainHandler(MyRequestHandler):
    
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        yield self.find_current_session()
        ### check player credentials too!
        if self.twsessionstatus != 'auth':
            raise tornado.web.HTTPError(403, 'You do not have admin access.')
        self.render('admin.html',
                    mongoavailable=(self.application.mongodb is not None),
                    tworldavailable=(self.application.twservermgr.tworldavailable),
                    conntable=self.application.twconntable.as_dict())

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        yield self.find_current_session()
        ### check player credentials too!
        if self.twsessionstatus != 'auth':
            raise tornado.web.HTTPError(403, 'You do not have admin access.')
        if (self.get_argument('playerconntable', None)):
            msg = { 'cmd':'logplayerconntable' }
            self.application.twservermgr.tworld_write(0, msg)
        self.redirect('/admin')

class PlayWebSocketHandler(MyHandlerMixin, tornado.websocket.WebSocketHandler):
    def open(self):
        # Proceed using a callback, because the open() method cannot be
        # made into a coroutine.
        self.twconnid = None
        self.twconn = None
        self.find_current_session(callback=self.open_cont)

    def open_cont(self, result):
        # From here on out we have to catch our own exceptions and close
        # the socket.
        if self.twsessionstatus != 'auth':
            self.write_tw_error('You are not authenticated.')
            self.close()
            return
        
        self.twconnid = self.application.twconntable.generate_connid()
        uid = self.twsession['uid']
        email = self.twsession['email']
        self.application.twlog.info('Player connected to websocket: %s (session %s, connid %d)', self.twsession['email'], self.twsession['sid'], self.twconnid)

        if not self.application.twservermgr.tworldavailable:
            self.write_tw_error('Tworld service is not available.')
            self.close()
            return

        # Add it to the connection table.
        try:
            self.twconn = self.application.twconntable.add(self, uid, email, self.twsession['sid'])
        except Exception as ex:
            self.write_tw_error('Unable to add connection: %s' % (ex,))
            self.close()
            return

        # Tell tworld about this new connection. Tworld will send back
        # a reply, at which point we'll mark it available.
        try:
            msg = { 'cmd':'playeropen', 'uid':str(uid), 'email':email }
            self.application.twservermgr.tworld_write(self.twconnid, msg)
        except Exception as ex:
            self.application.twlog.error('Could not write playeropen message to tworld socket: %s', ex)
            self.write_tw_error('Unable to register connection with service: %s' % (ex,))
            self.close()
            return

    def on_message(self, msg):
        # Note that message is a string here; it hasn't been de-jsoned.
        self.application.twlog.info('### message: %s' % (msg,))
        if not self.twconn or not self.twconn.available:
            self.application.twlog.warning('Websocket connection is not available')
            self.write_tw_error('Your connection is not registered.')
            return

        self.twconn.lastmsgtime = datetime.datetime.now()

        if not self.application.twservermgr.tworldavailable:
            self.application.twlog.warning('Tworld is not available.')
            self.write_tw_error('Tworld service is not available.')
            return

        # Perform some very minimal format-checking.
        if not msg.startswith('{'):
            self.application.twlog.warning('Message from client appeared invalid: %s', msg[0:50])
            self.write_tw_error('Message format appeared to be invalid.')
            return

        if len(msg) > 1000:
            ### This will require some tuning
            self.application.twlog.warning('Message from client was too long: %s', msg[0:50])
            self.write_tw_error('Message was too long.')
            return

        # Pass it along to tworld. (The tworld_write method is smart when
        # handed a string containing JSON data.)
        try:
            self.application.twservermgr.tworld_write(self.twconnid, msg)
        except Exception as ex:
            self.application.twlog.error('Could not pass message to tworld socket: %s', ex)
            self.write_tw_error('Unable to pass command to service: %s' % (ex,))

    def on_close(self):
        self.application.twlog.info('Player disconnected from websocket %s', self.twconnid)
        # Tell tworld that the connection is closed. (Maybe it never
        # became available, but we'll send the message anyway.)
        try:
            msg = {'cmd':'playerclose'}
            self.application.twservermgr.tworld_write(self.twconnid, msg)
        except Exception as ex:
            self.application.twlog.error('Could not write playerclose message to tworld socket: %s', ex)
        # Remove the connection from our table.
        try:
            self.application.twconntable.remove(self)
        except Exception as ex:
            self.application.twlog.error('Error removing connection: %s', ex)
        # Clean up dangling fields, and drop self forever.
        self.twconnid = None
        self.twconn = None

    def write_tw_error(self, msg):
        """Write a JSON error-reporting command through the socket.
        """
        try:
            obj = { 'cmd': 'error', 'text': msg }
            self.write_message(obj)
        except Exception as ex:
            self.application.twlog.warning('Unable to send error to websocket (%s): %s', msg, ex)
        
class TestHandler(MyRequestHandler):
    """Debugging -- will go away eventually.
    """
    def get(self):
        self.render('test.html', foo=11, xsrf=self.xsrf_form_html())

