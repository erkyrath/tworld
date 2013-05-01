
import os
import binascii
import datetime
import hashlib

import tornado.gen
import motor

from twlib.misc import MessageException

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
        if (not self.app.mongoavailable):
            raise MessageException('Database not available')

        if ('@' in name):
            key = 'email'
        else:
            key = 'name'
            
        try:
            res = yield motor.Op(self.app.mongo.mydb.players.find_one,
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
    def create_session(self, handler, uid, email, name):
        """
        Create a session from the request parameters. Return it (as
        a dict, with _id).
        """
        if (not self.app.mongoavailable):
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

        res = yield motor.Op(self.app.mongo.mydb.sessions.insert, sess)
        return res

    @tornado.gen.coroutine
    def find_session(self, handler):
        """
        Look up the user's session, using the sessionid cookie. Returns
        (status, session). The status is 'auth', 'unauth', or 'unknown'
        (if the auth server is unavailable).
        """
        if (not self.app.mongoavailable):
            return ('unknown', None)
        sessionid = handler.get_secure_cookie('sessionid')
        if not sessionid:
            return ('unauth', None)
        try:
            res = yield motor.Op(self.app.mongo.mydb.sessions.find_one,
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
            yield motor.Op(self.app.mongo.mydb.sessions.remove,
                           { 'sid': sessionid })
    
