"""
The SessionMgr manages the collection of login sessions from client.
When you sign into the web site, you get a sessionid cookie, and we
create a session entry in the database. The session lasts until one of
those disappears.

(Note that sessions are not web socket connections. See the connections.py
module for those.)
"""

import os
import binascii
import datetime
import hashlib

import bson.son
import tornado.gen
import tornado.httputil
import motor

import twcommon.misc
import twcommon.access
from twcommon.excepts import MessageException
from twcommon.misc import sluggify

class SessionMgr(object):
    """
    Manage the collection of sessions in mongodb.

    All these methods are async, which means all my handlers get/post
    methods have to be async. Pain in the butt, it is.
    """

    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app

    def random_bytes(self, count):
        """Generate random hexadecimal bytes, from a good source.
        (Result will be a bytes object containing 2*N (ASCII, lowercase)
        hex digits.)
        """
        byt = os.urandom(count)
        return binascii.hexlify(byt)

    @tornado.gen.coroutine
    def find_player(self, handler, name, password):
        """
        Locate the player whose name *or* email address is given. Return
        the player dict. If the password does not match, or the player is
        not found, return None.

        This presumes that names do not contain @ signs, and that neither
        names nor email addresses are duplicated.
        """
        if (not self.app.mongodb):
            raise MessageException('Database not available.')

        if ('@' in name):
            key = 'email'
        else:
            key = 'name'
            
        try:
            res = yield motor.Op(self.app.mongodb.players.find_one,
                                 { key: name })
        except Exception as ex:
            raise MessageException('Database error: %s' % ex)

        if not res:
            return None

        # Check password. (It is already a bytes.)
        saltedpw = res['pwsalt'] + b':' + password
        cryptpw = hashlib.sha1(saltedpw).hexdigest().encode()
        if (res['password'] != cryptpw):
            return None

        return res
    
    @tornado.gen.coroutine
    def find_player_nopw(self, handler, name):
        """
        Locate the player whose name *or* email address is given. Return
        the player dict. If the player is not found, return None.

        This is the same as above, but doesn't require a password.
        We use this only for password recovery.
        """
        if (not self.app.mongodb):
            raise MessageException('Database not available.')

        if ('@' in name):
            key = 'email'
        else:
            key = 'name'
            
        try:
            res = yield motor.Op(self.app.mongodb.players.find_one,
                                 { key: name })
        except Exception as ex:
            raise MessageException('Database error: %s' % ex)

        if not res:
            return None

        return res
    
    @tornado.gen.coroutine
    def create_player(self, handler, email, name, password):
        """
        Create a player entry with the given parameters. Also create a
        session and sign the player in.
        
        The name and email should already have been validated and
        canonicalized, as much as possible.
        """
        if (not self.app.mongodb):
            raise MessageException('Database not available.')

        namekey = sluggify(name)
        
        # Check for collisions first.
        try:
            resname = yield motor.Op(self.app.mongodb.players.find_one,
                                     { 'name': name })
            resnamekey = yield motor.Op(self.app.mongodb.players.find_one,
                                     { 'namekey': namekey })
            resemail = yield motor.Op(self.app.mongodb.players.find_one,
                                     { 'email': email })
        except Exception as ex:
            raise MessageException('Database error: %s' % ex)

        if (resname):
            raise MessageException('The player name %s is already in use.' % (name,))
        if (resnamekey):
            raise MessageException('The player name %s is already in use.' % (resnamekey['name'],))
        if (resemail):
            raise MessageException('That email address is already registered.')

        # Both the salt and password strings are stored as bytes, although
        # they'll really be ascii hex digits.
        pwsalt = self.random_bytes(8)
        saltedpw = pwsalt + b':' + password
        cryptpw = hashlib.sha1(saltedpw).hexdigest().encode()
        
        player = {
            'name': name,
            'namekey': namekey,
            'email': email,
            'pwsalt': pwsalt,
            'password': cryptpw,
            'createtime': twcommon.misc.now(),
            }

        playerfields = yield motor.Op(self.app.mongodb.config.find_one, {'key':'playerfields'})
        if playerfields:
            player.update(playerfields['val'])

        uid = yield motor.Op(self.app.mongodb.players.insert, player)
        if not uid:
            raise MessageException('Unable to create player.')

        # Create the playstate entry.
        playstate = {
            '_id': uid,
            'iid': None,
            'locid': None,
            'focus': None,
            }
        
        uid = yield motor.Op(self.app.mongodb.playstate.insert, playstate)
        if not uid:
            raise MessageException('Unable to create playstate.')

        # Create a personal scope for the player.
        scope = {
            'type': 'pers',
            'uid': uid,
            }
    
        scid = yield motor.Op(self.app.mongodb.scopes.insert, scope)
        yield motor.Op(self.app.mongodb.players.update,
                       {'_id':uid},
                       {'$set': {'scid': scid}})

        # And give the player full access to it
        yield motor.Op(self.app.mongodb.scopeaccess.insert,
                       {'uid':uid, 'scid':scid, 'level':twcommon.access.ACC_FOUNDER})

        # Create a personal portlist (booklet) for the player.
        portlist = {
            'type': 'pers',
            'uid': uid,
            }

        plistid = yield motor.Op(self.app.mongodb.portlists.insert, portlist)
        yield motor.Op(self.app.mongodb.players.update,
                       {'_id':uid},
                       {'$set': {'plistid': plistid}})

        # Create the first entry for the portlist.
        try:
            yield self.create_starting_portal(plistid, scid)
        except Exception as ex:
            self.app.twlog.error('Error creating player\'s first portal: %s', ex)
        
        # Create a sign-in session too, and we're done.
        sessionid = yield tornado.gen.Task(self.create_session, handler, uid, email, name)
        return sessionid

    @tornado.gen.coroutine
    def create_starting_portal(self, plistid, scid):
        res = yield motor.Op(self.app.mongodb.config.find_one, {'key':'firstportal'})
        firstportal = None
        if res:
            firstportal = res['val']
        if not firstportal:
            res = yield motor.Op(self.app.mongodb.config.find_one, {'key':'startworldid'})
            portwid = res['val']
            res = yield motor.Op(self.app.mongodb.config.find_one, {'key':'startworldloc'})
            portlockey = res['val']
            res = yield motor.Op(self.app.mongodb.locations.find_one, {'wid':portwid, 'key':portlockey})
            portlocid = res['_id']
            portscid = scid
        else:
            portwid = firstportal['wid']
            portlocid = firstportal['locid']
            portscid = firstportal['scid']
            if portscid == 'global':
                res = yield motor.Op(self.app.mongodb.config.find_one, {'key':'globalscopeid'})
                portscid = res['val']
            elif portscid == 'personal':
                portscid = scid
        if not (portwid and portscid and portlocid):
            raise Exception('Unable to define portal')

        portal = {
            'plistid':plistid, 'iid':None, 'listpos':1.0,
            'wid':portwid, 'scid':portscid, 'locid':portlocid,
            }
        yield motor.Op(self.app.mongodb.portals.insert, portal)
    
    @tornado.gen.coroutine
    def change_password(self, uid, password):
        """
        Change an existing player's password.
        """
        # Both the salt and password strings are stored as bytes, although
        # they'll really be ascii hex digits.
        pwsalt = self.random_bytes(8)
        saltedpw = pwsalt + b':' + password
        cryptpw = hashlib.sha1(saltedpw).hexdigest().encode()
        
        yield motor.Op(self.app.mongodb.players.update,
                       {'_id':uid},
                       {'$set': {'pwsalt': pwsalt, 'password':cryptpw}})
        
    @tornado.gen.coroutine
    def create_session(self, handler, uid, email, name):
        """
        Create a session from the request parameters. Return the session
        id.
        """
        if (not self.app.mongodb):
            raise MessageException('Database not available')
        
        # Generate a random sessionid.
        sessionid = self.random_bytes(24)
        handler.set_secure_cookie('sessionid', sessionid, expires_days=10)

        now = twcommon.misc.now()
        sess = {
            'sid': sessionid,
            'uid': uid,
            'email': email,
            'name': name,
            'ipaddr': handler.request.remote_ip,
            'starttime': now,
            'refreshtime': now,
            }

        res = yield motor.Op(self.app.mongodb.sessions.insert, sess)
        return sessionid

    @tornado.gen.coroutine
    def create_session_guest(self, handler):
        """
        Create a guest session. Return the session id and email address,
        or raise an exception.
        """
        # Find the first guest account which is not in use.
        player = None
        cursor = self.app.mongodb.players.find({'guest':True},
                                               sort=[('_id', 1)])
        while (yield cursor.fetch_next):
            res = cursor.next_object()
            if res.get('guestsession', None):
                # This one is busy.
                continue
            player = res
            break
        yield motor.Op(cursor.close)
        if not player:
            raise MessageException('All guest accounts are busy right now! You can still register a permanent account.')
        uid = player['_id']
        self.app.twlog.debug('### Found guest account: %s', player)

        # Generate a random sessionid.
        sessionid = self.random_bytes(24)
        handler.set_secure_cookie('sessionid', sessionid, expires_days=10)

        # Mark the guest account as in-use, and clear out its associated
        # data. (Including desc and pronoun.)
        playerfields = yield motor.Op(self.app.mongodb.config.find_one, {'key':'playerfields'})
        if not playerfields:
            raise Exception('No playerfields data found for guest!')
        playerfields = playerfields['val']
        playerfields['build'] = False
        playerfields['askbuild'] = False
        playerfields['guestsession'] = sessionid

        yield motor.Op(self.app.mongodb.players.update,
                       { '_id': uid },
                       { '$set': playerfields})

        # Clear out the player's personal portlist, and add back the starting
        # portal.
        yield motor.Op(self.app.mongodb.portals.remove,
                       { 'plistid': player['plistid'] })
        # Create the first entry for the portlist.
        try:
            yield self.create_starting_portal(player['plistid'], player['scid'])
        except Exception as ex:
            self.app.twlog.error('Error creating guest\'s first portal: %s', ex)
        
        # Clear out instance properties associated with the start world. This
        # should maybe be in a site-specific hook; it presumes that the
        # start world has tutorial-like features built on instance props.
        res = yield motor.Op(self.app.mongodb.config.find_one,
                             {'key':'startworldid'})
        startinstance = yield motor.Op(self.app.mongodb.instances.find_one,
                                       {'wid':res['val'], 'scid':player['scid']})
        if startinstance:
            yield motor.Op(self.app.mongodb.instanceprop.remove,
                           { 'iid': startinstance['_id'] })

        # Finally, create the session entry.
        now = twcommon.misc.now()
        sess = {
            'sid': sessionid,
            'uid': uid,
            'email': player['email'],
            'name': player['name'],
            'ipaddr': handler.request.remote_ip,
            'starttime': now,
            'refreshtime': now,
            'guest': True,
            }

        res = yield motor.Op(self.app.mongodb.sessions.insert, sess)
        return (sessionid, player['email'])
        
    @tornado.gen.coroutine
    def find_session(self, handler):
        """
        Look up the user's session, using the sessionid cookie. Returns
        (status, session). The status is 'auth', 'unauth', or 'unknown'
        (if the auth server is unavailable).
        """
        if (not self.app.mongodb):
            return ('unknown', None)
        sessionid = handler.get_secure_cookie('sessionid')
        if not sessionid:
            return ('unauth', None)
        try:
            res = yield motor.Op(self.app.mongodb.sessions.find_one,
                                 { 'sid': sessionid })
        except Exception as ex:
            self.app.twlog.error('Error finding session: %s', ex)
            return ('unknown', None)
        if not res:
            return ('unauth', None)
        return ('auth', res)

    @tornado.gen.coroutine
    def remove_session(self, handler):
        """
        Remove the user's session and sessionid cookie.
        """
        sessionid = handler.get_secure_cookie('sessionid')
        handler.clear_cookie('sessionid')
        if (sessionid):
            yield motor.Op(self.app.mongodb.sessions.remove,
                           { 'sid': sessionid })
    
    @tornado.gen.coroutine
    def monitor_sessions(self):
        """
        The session strategy: When you sign in, you get a secure cookie
        ("sessionid") with an ten-day expiration. Then, as long as you're
        connected to a websocket, we'll send you a notice to extend that
        expiration after seven days. If you're not connected, we'll clean
        up the session on our end after eight days.

        (Most web sites would also do an extend on normal page browsing.
        But we've got nothing to offer except the websocket service, so
        if you're on, you're on that.)
        """
        # If any live connections are more than seven days old, bump
        # them up.
        now = twcommon.misc.now()
        sevendays = now - datetime.timedelta(days=7)
        ls = [ conn for conn in self.app.twconntable.all()
               if conn.sessiontime < sevendays ]
        if ls:
            plustendays = now + datetime.timedelta(days=10)
            msgobj = {
                'cmd': 'extendcookie',
                'key': 'sessionid',
                'date': tornado.httputil.format_timestamp(plustendays)
                }
            
            for conn in ls:
                try:
                    conn.sessiontime = now
                    conn.handler.write_message(msgobj)
                    yield motor.Op(self.app.mongodb.sessions.update,
                                   { 'sid': conn.sessionid },
                                   { '$set': {'refreshtime':now }})
                    self.app.twlog.info('Player session refreshed: %s (connid %d)', conn.email, conn.connid)
                except Exception as ex:
                    self.app.twlog.error('Error refreshing session: %s', ex)

        # Expire old sessions.
        try:
            # Order matters for the count command, so we must construct
            # it as BSON.
            eightdays = now - datetime.timedelta(days=8)
            countquery = bson.son.SON()
            countquery['count'] = 'sessions'
            countquery['query'] = {'refreshtime': {'$lt': eightdays}}
            
            res = yield motor.Op(self.app.mongodb.command, countquery)
            if res and res['n']:
                self.app.twlog.info('Expiring %d sessions', res['n'])
                res = yield motor.Op(self.app.mongodb.sessions.remove,
                                     {'refreshtime': {'$lt': eightdays}})
            
        except Exception as ex:
            self.app.twlog.error('Error expiring old sessions: %s', ex)

    @tornado.gen.coroutine
    def monitor_pwrecover(self):
        """
        This has nothing to do with sessions, but it's an easy place to
        stick it. Once an hour, we trim out all pwrecover entries more than
        24 hours old.
        """
        now = twcommon.misc.now()
        yesterday = now - datetime.timedelta(days=1)

        try:
            self.app.twlog.info('Performing pwrecover cleanup')
            res = yield motor.Op(self.app.mongodb.pwrecover.remove,
                                 {'createtime': {'$lt': yesterday}})
        except Exception as ex:
            self.app.twlog.error('Error expiring old pwrecover: %s', ex)

    @tornado.gen.coroutine
    def monitor_trashprop(self):
        """
        This has nothing to do with sessions, but it's an easy place to
        stick it. Once an hour, we trim out all trashprop entries more than
        24 hours old.
        """
        now = twcommon.misc.now()
        yesterday = now - datetime.timedelta(days=1)

        try:
            self.app.twlog.info('Performing trashprop cleanup')
            res = yield motor.Op(self.app.mongodb.trashprop.remove,
                                 {'changed': {'$lt': yesterday}})
        except Exception as ex:
            self.app.twlog.error('Error expiring old trashprop: %s', ex)


