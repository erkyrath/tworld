
import os
import binascii
import datetime
import hashlib

import tornado.gen
import motor

from tweblib.misc import MessageException

### occasionally expire sessions

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
            raise MessageException('Database not available')

        if ('@' in name):
            key = 'email'
        else:
            key = 'name'
            
        try:
            res = yield motor.Op(self.app.mongodb.players.find_one,
                                 { key: name })
        except Exception as ex:
            return MessageException('Database error: %s' % ex)

        if not res:
            return None

        # Check password. (It is already a bytes.)
        saltedpw = res['pwsalt'] + b':' + password
        cryptpw = hashlib.sha1(saltedpw).hexdigest().encode()
        if (res['password'] != cryptpw):
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
            raise MessageException('Database not available')

        # Check for collisions first.
        try:
            resname = yield motor.Op(self.app.mongodb.players.find_one,
                                     { 'name': name })
            resemail = yield motor.Op(self.app.mongodb.players.find_one,
                                     { 'email': email })
        except Exception as ex:
            return MessageException('Database error: %s' % ex)

        if (resname):
            raise MessageException('That player name is already in use.')
        if (resemail):
            raise MessageException('That email address is already registered.')

        # Both the salt and password strings are stored as bytes, although
        # they'll really be ascii hex digits.
        pwsalt = self.random_bytes(8)
        saltedpw = pwsalt + b':' + password
        cryptpw = hashlib.sha1(saltedpw).hexdigest().encode()
        
        player = {
            'name': name,
            'email': email,
            'pwsalt': pwsalt,
            'password': cryptpw,
            'createtime': datetime.datetime.now(),
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
            'locale': None,
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
        
        # Create a sign-in session too, and we're done.
        sessionid = yield tornado.gen.Task(self.create_session, handler, uid, email, name)
        return sessionid
        
    @tornado.gen.coroutine
    def create_session(self, handler, uid, email, name):
        """
        Create a session from the request parameters. Return it (as
        a dict, with _id).
        """
        if (not self.app.mongodb):
            raise MessageException('Database not available')
        
        # Generate a random sessionid.
        sessionid = self.random_bytes(24)
        handler.set_secure_cookie('sessionid', sessionid)
        
        sess = {
            'sid': sessionid,
            'uid': uid,
            'email': email,
            'name': name,
            'ipaddr': handler.request.remote_ip,
            'starttime': datetime.datetime.now(),
            }

        res = yield motor.Op(self.app.mongodb.sessions.insert, sess)
        return sessionid

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
    
