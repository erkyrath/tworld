"""
All the URI request handlers used by Tweb.
"""

import datetime
import traceback
import unicodedata
import json

from bson.objectid import ObjectId
import tornado.web
import tornado.gen
import tornado.escape
import tornado.websocket

import motor

import tweblib.session
import twcommon.misc
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
    def prepare(self):
        """
        Called before every get/post invocation for this handler. We use
        the opportunity to look up the session status.
        """
        yield self.find_current_session()
    
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
            self.render('main_auth.html')

    @tornado.gen.coroutine
    def post(self):

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
        self.render('recover.html')

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
        uiprefs = {}
        if self.application.mongodb is not None:
            cursor = self.application.mongodb.playprefs.find({'uid':self.twsession['uid']})
            while (yield cursor.fetch_next):
                pref = cursor.next_object()
                uiprefs[pref['key']] = pref['val']
            cursor.close()
        # We could use the client preferred language here.
        localize = self.application.twlocalize.all()
        self.render('play.html',
                    uiprefs=json.dumps(uiprefs),
                    localize=json.dumps(localize))
        
class TopPageHandler(MyRequestHandler):
    """Handler for miscellaneous top-level pages ("about", etc.)
    """
    def initialize(self, page):
        self.page = page
        
    @tornado.gen.coroutine
    def get(self):
        self.render('top_%s.html' % (self.page,))


class BuildBaseHandler(MyRequestHandler):
    """Base class for the handlers for build pages. This has some common
    functionality.
    """
    @tornado.gen.coroutine
    def prepare(self):
        """
        Called before every get/post invocation for this handler. We use
        the opportunity to make sure the player is authenticated and a
        builder. We also save the admin flag as self.twisadmin.
        """
        yield self.find_current_session()
        if self.twsessionstatus != 'auth':
            raise tornado.web.HTTPError(403, 'You are not signed in.')
        res = yield motor.Op(self.application.mongodb.players.find_one,
                             { '_id':self.twsession['uid'] })
        self.twisadmin = res.get('admin', False)
        if not res or not (self.twisadmin or res.get('build', False)):
            raise tornado.web.HTTPError(403, 'You do not have build access.')

    def extend_template_namespace(self, map):
        map = super().extend_template_namespace(map)
        map['xsrf_token'] = tornado.escape.xhtml_escape(self.xsrf_token)
        return map

    @tornado.gen.coroutine
    def find_build_world(self, wid):
        """Given the ObjectId of a world, look up the world and make sure
        this player is the creator. We also look up the location list for
        the world, since any build page that cares will have a location
        pop-up.
        """
        world = yield motor.Op(self.application.mongodb.worlds.find_one,
                               { '_id':wid })
        if not world:
            raise Exception('No such world')
        if world['creator'] != self.twsession['uid'] and not self.twisadmin:
            raise tornado.web.HTTPError(403, 'You did not create this world.')
        
        locations = []
        cursor = self.application.mongodb.locations.find({'wid':wid})
        while (yield cursor.fetch_next):
            loc = cursor.next_object()
            locations.append(loc)
        cursor.close()
        locations.sort(key=lambda loc:loc['_id']) ### or other criterion?

        return (world, locations)

    def export_prop_array(self, ls):
        """Given an array of property values (from the db), return an array
        suitable for handing over to the client for editing. This means
        an array of type-keyed dicts. We wrap all native values as {value}
        objects.
        """
        res = []
        for prop in ls:
            val = prop['val']
            if type(val) is dict and val.get('type', None):
                pass
            else:
                ### If I defaulted to double-quotes for strings, it would be a bit tidier.
                val = { 'type':'value', 'value':repr(val) }
            newprop = {'key':prop['key'], 'val':val, 'id':str(prop['_id'])}
            res.append(newprop)
        return res

class BuildMainHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self):
        worlds = []
        cursor = self.application.mongodb.worlds.find({'creator':self.twsession['uid']}, {'name':1})
        while (yield cursor.fetch_next):
            world = cursor.next_object()
            worlds.append({'name':world['name'], 'id':str(world['_id'])})
        cursor.close()
        worlds.sort(key=lambda world:world['id']) ### or other criterion?
        self.render('build_main.html', worlds=worlds)
        
class BuildWorldHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self, wid):
        wid = ObjectId(wid)
        (world, locations) = yield self.find_build_world(wid)

        worldname = world.get('name', '???')
        # This array must be handed to the client to construct the pop-up
        # location menu.
        locarray = [ {'id':str(loc['_id']), 'name':loc['name']} for loc in locations ]

        worldprops = []
        cursor = self.application.mongodb.worldprop.find({'wid':wid, 'locid':None}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            worldprops.append(prop)
        cursor.close()
        worldprops.sort(key=lambda prop:prop['_id']) ### or other criterion?

        playerprops = []
        cursor = self.application.mongodb.wplayerprop.find({'wid':wid, 'uid':None}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            playerprops.append(prop)
        cursor.close()
        playerprops.sort(key=lambda prop:prop['_id']) ### or other criterion?

        encoder = JSONEncoderExtra()
        worldproparray = encoder.encode(self.export_prop_array(worldprops))
        playerproparray = encoder.encode(self.export_prop_array(playerprops))

        self.render('build_world.html',
                    wid=str(wid), worldname=worldname,
                    locarray=json.dumps(locarray), locations=locations,
                    worldproparray=worldproparray, playerproparray=playerproparray)

### Put elsewhere?
### Necessary at all? I may be pushing all JSONable values now. Although I need to think about datetime objects.
class JSONEncoderExtra(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)
        
class BuildLocHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self, locid):
        locid = ObjectId(locid)
        location = yield motor.Op(self.application.mongodb.locations.find_one,
                                  { '_id':locid })
        if not location:
            raise Exception('No such location')
        wid = location['wid']
        (world, locations) = yield self.find_build_world(wid)

        worldname = world.get('name', '???')
        # This array must be handed to the client to construct the pop-up
        # location menu.
        locarray = [ {'id':str(loc['_id']), 'name':loc['name']} for loc in locations ]

        lockey = location.get('key')
        locname = location.get('name', '???')

        props = []
        cursor = self.application.mongodb.worldprop.find({'wid':wid, 'locid':locid}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            props.append(prop)
        cursor.close()
        props.sort(key=lambda prop:prop['_id']) ### or other criterion?

        encoder = JSONEncoderExtra()
        proparray = encoder.encode(self.export_prop_array(props))
        
        self.render('build_loc.html',
                    wid=str(wid), worldname=worldname,
                    locarray=json.dumps(locarray), locations=locations,
                    locname=locname, locid=str(locid), lockey=json.dumps(lockey),
                    proparray=proparray)

class BuildSetPropHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        self.application.twlog.debug('### property value: %s', repr(self.get_argument('val')))
        try:
            wid = ObjectId(self.get_argument('world'))
            locid = self.get_argument('loc')
            if locid == '$realm':
                locid = None
            elif locid == '$player':
                pass  # special case
            else:
                locid = ObjectId(locid)
    
            # Check the heck out of the arguments.
            world = yield motor.Op(self.application.mongodb.worlds.find_one,
                                   { '_id':wid })
            if not world:
                raise Exception('No such world')
            if world['creator'] != self.twsession['uid'] and not self.twisadmin:
                raise tornado.web.HTTPError(403, 'You did not create this world.')
            if locid in (None, '$player'):
                loc = locid
            else:
                loc = yield motor.Op(self.application.mongodb.locations.find_one,
                                     { '_id':locid })
                if not loc:
                    raise Exception('No such location')
    
            if self.get_argument('delete', False):
                raise Exception('### Delete it!')
    
            self.write( { 'error': 'Dummy error' } )
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (setting property): %s', ex)
            self.write( { 'error': str(ex) } )

class AdminMainHandler(MyRequestHandler):
    """Handler for the Admin page, which is rudimentary and not worth much
    right now.
    """
    @tornado.gen.coroutine
    def prepare(self):
        """
        Called before every get/post invocation for this handler. We use
        the opportunity to look up the session status, and then make sure
        the player is an administrator.
        """
        yield self.find_current_session()
        if self.twsessionstatus != 'auth':
            raise tornado.web.HTTPError(403, 'You are not signed in.')
        res = yield motor.Op(self.application.mongodb.players.find_one,
                             { '_id':self.twsession['uid'] })
        if not res or not res.get('admin', False):
            raise tornado.web.HTTPError(403, 'You do not have admin access.')
    
    @tornado.gen.coroutine
    def get(self):
        self.render('admin.html',
                    mongoavailable=(self.application.mongodb is not None),
                    tworldavailable=(self.application.twservermgr.tworldavailable),
                    conntable=self.application.twconntable.as_dict())

    @tornado.gen.coroutine
    def post(self):
        if (self.get_argument('playerconntable', None)):
            msg = { 'cmd':'logplayerconntable' }
            self.application.twservermgr.tworld_write(0, msg)
        self.redirect('/admin')

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
        self.application.twlog.debug('### received a websocket connection...')
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
            self.write_tw_error('Unable to register connection with service: %s' % (ex,))
            self.close()
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
        """Callback: web socket has closed.
        """
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
        
