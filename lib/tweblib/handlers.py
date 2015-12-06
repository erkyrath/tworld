"""
The main URI request handlers used by Tweb.
"""

import types
import re
import datetime
import traceback
import unicodedata
import random
import json

from bson.objectid import ObjectId
import tornado.web
import tornado.gen
import tornado.escape
import tornado.websocket

import motor

import tweblib.session
import tweblib.mailer
import twcommon.misc
from twcommon.excepts import MessageException
from twcommon.misc import sluggify

class MyHandlerMixin:
    """
    Mix-in class, which I used for several of the standard request handlers.
    It does several things:
    - Custom error page
    - Utility method to figure out the current session
    - Set up default values for the base template
    - Load in information for the portlink cookie, if one is set
    """

    # Set this True for classes that will care about displaying a portlink.
    tw_load_portlink = False

    # Class defaults. The prepare method will fill in values for handler
    # objects as they're being set up.
    twsessionstatus = None
    twsession = None
    twportlink = None

    @tornado.gen.coroutine
    def prepare(self):
        """
        Called before every get/post invocation for this handler. We use
        the opportunity to look up the session status, and also portlink
        information.
        """
        yield self.find_current_session()
        if self.tw_load_portlink:
            portid = self.get_cookie('tworld_portlink', None)
            if portid:
                # Load up the portlink data, if possible. (If it's not 
                # possible, don't worry too much.)
                try:
                    portid = ObjectId(portid)
                    self.twportlink = yield self.external_portal_description(portid)
                except Exception as ex:
                    self.application.twlog.info('Unable to load portlink info for template: %s', ex)
    
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

        This is invoked from the prepare() method, but also manually if
        we know the session info has changed.
        """
        if self.application.caughtinterrupt:
            # Server is shutting down; don't accept any significant requests.
            raise MessageException('Server is shutting down!')
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
        
    @tornado.gen.coroutine
    def check_external_portal(self, portid):
        """Check to make sure a portal is okay for external linking.
        (This lives here because a couple of different handlers use it.)
        Returns the portal DB object, or raises an exception.
        """
        portal = yield motor.Op(self.application.mongodb.portals.find_one,
                                { '_id':portid })
        if not portal:
            raise tornado.web.HTTPError(403, 'No such portal')
        if portal['iid'] is not None:
            raise tornado.web.HTTPError(403, 'Portal is not world-level')
        if portal['scid'] == 'same':
            raise tornado.web.HTTPError(403, 'Portal is current-scope')
        
        plist = yield motor.Op(self.application.mongodb.portlists.find_one,
                               { '_id':portal['plistid'] })
        if not plist:
            raise tornado.web.HTTPError(403, 'No such portlist')
        if plist['type'] != 'world':
            raise tornado.web.HTTPError(403, 'Portlist is not world-level')
        if not plist.get('external', False):
            raise tornado.web.HTTPError(403, 'Portlist is not available for external linking')

        world = yield motor.Op(self.application.mongodb.worlds.find_one,
                               { '_id':portal['wid'] },
                               { 'copyable':1 })
        if not world:
            raise tornado.web.HTTPError(403, 'No such world')
        if not world.get('copyable', False):
            raise tornado.web.HTTPError(403, 'World is not copyable')
        
        return portal

    @tornado.gen.coroutine
    def external_portal_description(self, portid, done=False):
        """Load up enough information about an external portal
        to display it.
        Returns an object with world, location, creator, portaldesc,
        and done fields. (The done argument is just passed along.
        This indicates whether the "put into your list" action is complete
        or not.)
        Raises an exception if anything goes wrong.
        """
        portal = yield self.check_external_portal(portid)
        world = yield motor.Op(self.application.mongodb.worlds.find_one,
                               { '_id': portal['wid'] },
                               { 'name':1, 'creator':1 })
        location = yield motor.Op(self.application.mongodb.locations.find_one,
                                  { '_id': portal['locid'] },
                                  { 'name':1 })
        creator = yield motor.Op(self.application.mongodb.players.find_one,
                                 { '_id': world['creator'] },
                                 { 'name':1 })
        portaldesc = yield motor.Op(self.application.mongodb.worldprop.find_one,
                                    { 'wid': portal['wid'],
                                      'locid': portal['locid'],
                                      'key': 'portaldesc' })
        if not portaldesc:
            portaldesc = yield motor.Op(self.application.mongodb.worldprop.find_one,
                                        { 'wid': portal['wid'],
                                          'locid': None,
                                          'key': 'portaldesc' })
        if not portaldesc:
            portaldesc = {
                'val': self.application.twlocalize('message.no_portaldesc') # 'The destination is hazy.'
                }

        portaldesc = portaldesc['val']
        if isinstance(portaldesc, dict) and portaldesc.get('type', None) == 'text':
            portaldesc = portaldesc.get('text', '???')
            
        return types.SimpleNamespace(
            world=world['name'],
            location=location['name'],
            creator=creator['name'],
            portaldesc=portaldesc,
            done=done)

    def render_portal(self, portal):
        """
        Render a portal object (as from external_portal_description)
        into a block of text, which can be used in page output. This
        is non-yieldy; the portal data must all be already loaded.
        If portal is None, returns nothing.
        """
        if not portal:
            return ''
        return self.render_string('portal_block.html', portal=portal)
    
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
            if not error_text:
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

class MyNotFoundErrorHandler(MyHandlerMixin, tornado.web.ErrorHandler):
    """Customization of tornado's ErrorHandler."""
    def initialize(self):
        super().initialize(404)
        
    @tornado.gen.coroutine
    def prepare(self):
        """
        The way tornado's ErrorHandler works is to raise the appropriate
        error. We want to set up the session info first, then do that.
        """
        yield self.find_current_session()
        raise tornado.web.HTTPError(self._status_code)
    
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
        # Always permit HEAD requests. Although we don't generate
        # any data, which means the Content-Length comes as zero.
        pass
    
    def get_current_user(self):
        # Look up the user name (email address, really) in the current
        # session.
        if self.twsession:
            return self.twsession['email']

class MainHandler(MyRequestHandler):
    """Top page: the login form.
    """
    tw_load_portlink = True
    
    @tornado.gen.coroutine
    def get(self):
        if not self.twsession:
            try:
                name = self.get_cookie('tworld_name', None)
                name = tornado.escape.url_unescape(name)
            except:
                name = None
            self.render('main.html', init_name=name)
        else:
            connectedlist = yield self.application.tworld_players_connected_list()
            self.render('main_auth.html',
                        connectedlist=connectedlist)

    @tornado.gen.coroutine
    def post(self):

        # If this flag is set, logins are restricted to administrators.
        locked = yield self.get_config_key('nologin')
        
        # If the "register" form was submitted, jump to the player-
        # registration page.
        if (self.get_argument('register', None)):
            self.redirect('/register')
            return

        # If the "guest login" form was submitted, create a guest session
        # and play.
        if (self.get_argument('guest', None)):
            try:
                if locked:
                    raise MessageException('Sign-ins are not allowed at this time.')
                (res, email) = yield self.application.twsessionmgr.create_session_guest(self)
            except MessageException as ex:
                formerror = str(ex)
                self.render('main.html', formerror=formerror)
                return
            self.application.twlog.info('Player signed in as guest: %s (session %s)', email, res)
            self.redirect('/play')
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
                        expires_days=30)

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
    tw_load_portlink = True
    
    @tornado.gen.coroutine
    def get(self):
        if self.twsession:
            # Can't register if you're already logged in!
            self.redirect('/')
            return
        self.render('register.html')

    @tornado.gen.coroutine
    def post(self):

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
        elif (len(name) > 32):
            formerror = 'Your name is limited to 32 characters.'
            formfocus = 'name'
        elif (not email):
            formerror = 'You must enter an email address.'
            formfocus = 'email'
        elif ('@' not in email):
            formerror = 'Your email address must contain an @ sign.'
            formfocus = 'email'
        elif (len(email) > 128):
            formerror = 'Your email address is limited to 128 characters.'
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
        elif (len(password) > 128):
            formerror = 'Please use no more than 128 characters in your password.'
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
                        expires_days=30)
        
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

class RecoverHandler(MyRequestHandler):
    """The page for recovering a lost password.
    """
    @tornado.gen.coroutine
    def get(self):
        try:
            name = self.get_cookie('tworld_name', None)
            name = tornado.escape.url_unescape(name)
        except:
            name = None
        self.render('recover.html', init_name=name)

    @tornado.gen.coroutine
    def post(self):
        # Apply canonicalizations to the name.
        name = self.get_argument('name', '')
        name = unicodedata.normalize('NFKC', name)
        name = tornado.escape.squeeze(name.strip())
        
        formerror = None
        if self.twsessionstatus == 'auth':
            formerror = 'You are already signed in!'
        elif (not name):
            formerror = 'You must enter your player name or email address.'
        if formerror:
            self.render('recover.html', formerror=formerror, init_name=name)
            return

        try:
            res = yield self.application.twsessionmgr.find_player_nopw(self, name)
        except MessageException as ex:
            formerror = str(ex)
            self.render('recover.html', formerror=formerror, init_name=name)
            return

        try:
            if not res:
                raise MessageException('There is no such player.')
            if res.get('guest', None):
                raise MessageException('The guest account password cannot be changed.')
       
            uid = res['_id']
            email = res['email']

            rec = yield motor.Op(self.application.mongodb.pwrecover.find_one,
                                 { '_id':uid })
            if rec:
                raise MessageException('A recovery email has already been sent for this account. Please wait for it to arrive. If the message has been lost, you may try again in 24 hours.')

            # Invent a random key string, avoiding collision, even though
            # collision is unlikely.
            while True:
                key = self.application.twsessionmgr.random_bytes(16).decode()
                rec = yield motor.Op(self.application.mongodb.pwrecover.find_one,
                                     { 'key':key })
                if not rec:
                    break

            rec = {
                '_id':uid, 'key':key,
                'createtime':twcommon.misc.now(),
                }

            yield motor.Op(self.application.mongodb.pwrecover.insert, rec)
            
            self.application.twlog.warning('Player lost password: %s', email)

            # Send the email. We set this up as a subprocess call to
            # /bin/mail (or equivalent), using Tornado's async subprocess
            # wrapper.

            message = self.render_string('mail_recover.txt',
                                         hostname=self.application.twopts.hostname,
                                         key=key)

            mailer = tweblib.mailer.Mailer(self.application)
            yield mailer.send(email, 'Password change request', message)

        except MessageException as ex:
            formerror = str(ex)
            self.render('recover.html', formerror=formerror, init_name=name)
            return
        
        self.render('recover.html', mailsent=True)
        
    def get_template_namespace(self):
        map = super().get_template_namespace()
        # Add a couple of default values. The handlers may or may not override
        # these Nones.
        map['formerror'] = None
        map['init_name'] = None
        map['mailsent'] = False
        return map

class Recover2Handler(MyRequestHandler):
    """The page for changing a lost password, in recovery.
    """
    @tornado.gen.coroutine
    def get(self, key):
        res = yield motor.Op(self.application.mongodb.pwrecover.find_one,
                             { 'key':key })
        if not res:
            raise tornado.web.HTTPError(404)
        uid = res['_id']
        self.render('recover2.html', key=key)

    @tornado.gen.coroutine
    def post(self, key):
        res = yield motor.Op(self.application.mongodb.pwrecover.find_one,
                             { 'key':key })
        if not res:
            raise tornado.web.HTTPError(404)
        uid = res['_id']

        # Apply canonicalizations to the passwords.
        password = self.get_argument('password', '')
        password = unicodedata.normalize('NFKC', password)
        password = password.encode()  # to UTF8 bytes
        password2 = self.get_argument('password2', '')
        password2 = unicodedata.normalize('NFKC', password2)
        password2 = password2.encode()  # to UTF8 bytes
        
        formerror = None
        formfocus = 'name'
        
        if self.twsessionstatus == 'auth':
            formerror = 'You are already signed in!'
        elif (not password):
            formerror = 'You must enter your new password.'
            formfocus = 'password'
        elif (not password2):
            formerror = 'You must enter your new password twice.'
            formfocus = 'password2'
        elif (len(password) < 6):
            formerror = 'Please use at least six characters in your password.'
            formfocus = 'password'
        elif (len(password) > 128):
            formerror = 'Please use no more than 128 characters in your password.'
            formfocus = 'password'
        elif (password != password2):
            formerror = 'The passwords you entered were not the same.'
            password2 = ''
            formfocus = 'password2'

        if formerror:
            self.render('recover2.html', key=key, formerror=formerror)
            return

        try:
            yield self.application.twsessionmgr.change_password(uid, password)
            # Success.
            yield motor.Op(self.application.mongodb.pwrecover.remove,
                           { 'key':key })
            formerror = None
        except MessageException as ex:
            formerror = str(ex)

        if formerror:
            self.render('recover2.html', key=key, formerror=formerror)
            return

        self.render('recover2.html', key=key, pwchanged=True)
    
    def get_template_namespace(self):
        map = super().get_template_namespace()
        # Add a couple of default values. The handlers may or may not override
        # these Nones.
        map['formerror'] = None
        map['pwchanged'] = False
        return map

class PortLinkHandler(MyRequestHandler):
    """The page for an external portal URL. This has to do various things,
    depending on the session state.
    - If you have a web session and an open socket, the link is added to
    your personal list and focussed.
    - If you have a web session but have no socket, the link is added to
    your personal list and focussed; then the page redirects to the game.
    - If you are not logged in, tweb sets a (short-term) cookie with the
    portid; then it redirects to the front page.
    """

    @tornado.gen.coroutine
    def get(self, portid):
        portid = ObjectId(portid)
        portal = yield self.check_external_portal(portid)
        
        if self.twsessionstatus != 'auth':
            # Set a one-hour cookie. We presume that the player can
            # register or log in within an hour.
            self.set_cookie('tworld_portlink', str(portid),
                            expires_days=0.05)
            self.redirect('/')
            return

        # Add the link to the player's personal list, if it's not already.
        # This also sets the focus.
        uid = self.twsession['uid']
        msg = { 'cmd':'externalcopyportal', 'uid':str(uid),
                'portid':str(portid), 'focus':True }
        self.application.twservermgr.tworld_write(0, msg)

        # Check whether the player has an active web session.
        ls = self.application.twconntable.for_uid(uid)
        if not ls:
            # Redirect to the play page.
            self.redirect('/play')
            return

        # Display a success message (with a play link, in case the player
        # wants that). Also the portal info, which we belatedly stuff
        # into self.twportlink.
        self.twportlink = yield self.external_portal_description(portid, done=True)
        self.render('portlink.html')
    
class AccountHandler(MyRequestHandler):
    """The page for updating your account state. (Currently, this is just
    changing your password.)
    """
    @tornado.gen.coroutine
    def prepare(self):
        """
        Called before every get/post invocation for this handler. We use
        the opportunity to store the various build permission flags.
        """
        yield self.find_current_session()
        if self.twsessionstatus != 'auth':
            raise tornado.web.HTTPError(403, 'You are not signed in.')
        res = yield motor.Op(self.application.mongodb.players.find_one,
                             { '_id':self.twsession['uid'] })
        if not res:
            raise tornado.web.HTTPError(403, 'You do not exist.')
        self.twisadmin = res.get('admin', False)
        self.twisbuild = (self.twisadmin or res.get('build', False))
        
    def get_template_namespace(self):
        map = super().get_template_namespace()
        # Add a couple of default values. The handlers may or may not override
        # these Nones.
        map['formerror'] = None
        return map

    @tornado.gen.coroutine
    def get(self):
        self.render('account.html',
                    name=self.twsession.get('name', '???'),
                    email=self.twsession.get('email', '???'),
                    isadmin=self.twisadmin,
                    isbuild=self.twisbuild)
        
    @tornado.gen.coroutine
    def post(self):

        # Apply canonicalizations to the passwords.
        oldpassword = self.get_argument('oldpassword', '')
        oldpassword = unicodedata.normalize('NFKC', oldpassword)
        oldpassword = oldpassword.encode()  # to UTF8 bytes
        password = self.get_argument('password', '')
        password = unicodedata.normalize('NFKC', password)
        password = password.encode()  # to UTF8 bytes
        password2 = self.get_argument('password2', '')
        password2 = unicodedata.normalize('NFKC', password2)
        password2 = password2.encode()  # to UTF8 bytes
        
        formerror = None
        formfocus = 'name'
        
        if (not oldpassword):
            formerror = 'You must enter your old password.'
            formfocus = 'oldpassword'
        elif (not password):
            formerror = 'You must enter your new password.'
            formfocus = 'password'
        elif (not password2):
            formerror = 'You must enter your new password twice.'
            formfocus = 'password2'
        elif (len(password) < 6):
            formerror = 'Please use at least six characters in your password.'
            formfocus = 'password'
        elif (len(password) > 128):
            formerror = 'Please use no more than 128 characters in your password.'
            formfocus = 'password'
        elif (password != password2):
            formerror = 'The passwords you entered were not the same.'
            password2 = ''
            formfocus = 'password2'

        if not formerror:
            try:
                res = yield self.application.twsessionmgr.find_player(self, self.twsession['email'], oldpassword)
                if not res:
                    formerror = 'Your current password does not match what you entered.'
                elif res['_id'] != self.twsession['uid']:
                    formerror = 'Your account ID did not match.'
                elif res.get('guest', None):
                    formerror = 'The guest account password cannot be changed.'
            except MessageException as ex:
                formerror = str(ex)
            
        if formerror:
            self.render('account.html', formerror=formerror,
                        name=self.twsession.get('name', '???'),
                        email=self.twsession.get('email', '???'),
                        isbuild=self.twisbuild)
            return

        try:
            yield self.application.twsessionmgr.change_password(self.twsession['uid'], password)
            # Success.
            formerror = 'Password changed.'
        except MessageException as ex:
            formerror = str(ex)

        self.render('account.html', formerror=formerror,
                    name=self.twsession.get('name', '???'),
                    email=self.twsession.get('email', '???'),
                    isbuild=self.twisbuild)

class LogOutHandler(MyRequestHandler):
    """The sign-out page.
    """
    @tornado.gen.coroutine
    def get(self):
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
    """Handler for the game page itself.
    """
    @tornado.gen.coroutine
    def get(self):
        if not self.twsession:
            self.redirect('/')
            return

        portid = self.get_cookie('tworld_portlink', None)
        if portid:
            # This is a one-use deal. (If it fails, it's more likely
            # to be an invalid portal than a temporary failure. Anyhow,
            # the player can probably find the URL again.)
            self.clear_cookie('tworld_portlink')
            
            # This should be okay even if the externalcopyportal arrives
            # after the player's browser loads the game.
            try:
                portid = ObjectId(portid)
                portal = yield self.check_external_portal(portid)
                uid = self.twsession['uid']
                msg = { 'cmd':'externalcopyportal', 'uid':str(uid),
                        'portid':str(portid), 'focus':True }
                self.application.twservermgr.tworld_write(0, msg)
            except Exception as ex:
                self.application.twlog.info('Unable to load portlink info for play: %s', ex)
        
        uiprefs = {}
        if self.application.mongodb is not None:
            cursor = self.application.mongodb.playprefs.find({'uid':self.twsession['uid']})
            while (yield cursor.fetch_next):
                pref = cursor.next_object()
                uiprefs[pref['key']] = pref['val']
            # cursor autoclose
        # We could use the client preferred language here.
        usessl = (self.request.protocol == 'https')
        localize = self.application.twlocalize.all()
        self.render('play.html',
                    uiprefs=json.dumps(uiprefs),
                    usessl=usessl,
                    localize=json.dumps(localize))
        
class TopPageHandler(MyRequestHandler):
    """Handler for miscellaneous top-level pages ("about", etc.)
    """
    def initialize(self, page):
        self.page = page
        
    @tornado.gen.coroutine
    def get(self):
        self.render('top_%s.html' % (self.page,))

        
class PlayWebSocketHandler(MyHandlerMixin, tornado.websocket.WebSocketHandler):
    """Handler for the websocket URI.

    This winds up stored inside a Connection object, for as long as the
    connection stays open.
    """
    def open(self):
        """Callback: web socket has been opened.
        
        Proceed using a callback, because the open() method cannot be
        made into a coroutine.
        """
        self.twconnid = None
        self.twconn = None
        self.find_current_session(callback=self.open_cont)

    def open_cont(self, result):
        """Callback to the callback: we've pulled session info from
        the database.
        """
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
            self.twconn = self.application.twconntable.add(self, uid, email, self.twsession)
        except Exception as ex:
            self.application.twlog.error('Unable to add connection: %s', ex)
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
            # The connection is in the table now, so we'll remove it the
            # fancy way.
            self.twconn.close('Unable to register connection with service: %s' % (ex,))
            return

    def on_message(self, msg):
        """Callback: web socket has received a message.
        
        Note that message is a string here. The UTF-8 bytes have been decoded,
        but it hasn't been de-jsoned.
        """
        if not self.twconn or not self.twconn.available:
            self.application.twlog.warning('Websocket connection is not available')
            self.write_tw_error('Your connection is not registered.')
            return

        self.twconn.lastmsgtime = twcommon.misc.now()

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
        """Callback: web socket has closed. (We also call this manually when
        manually closing the connection.)
        """
        if self.twconnid is None:
            self.application.twlog.warning('PlayWebSocketHandler got on_close while not in table.')
            return
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
        
