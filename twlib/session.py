
import os
import binascii
import datetime

import tornado.gen
import motor

class SessionMgr(object):

    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
    
    @tornado.gen.coroutine
    def create_session(self, handler, email):
        if (not self.app.mongo.connected):
            raise Exception('mongodb not connected')
        
        # Generate a random sessionid.
        byt = os.urandom(24)
        sessionid = binascii.hexlify(byt)
        handler.set_secure_cookie('sessionid', sessionid)
        
        sess = {
            'email': email,
            ### and the userid
            'sid': sessionid,
            'ipaddr': handler.request.remote_ip,
            'starttime': datetime.datetime.now(),
            }

        res = yield motor.Op(self.app.mongo.mydb.sessions.insert, sess)
        return res

    def find_session(self, handler):
        sessionid = handler.get_secure_cookie('sessionid')
        if not sessionid:
            return None
        sess = None ###
        return sess

    def remove_session(self, handler):
        sessionid = handler.get_secure_cookie('sessionid')
        if (sessionid):
            pass ###
        handler.clear_cookie('sessionid')
    
    ### occasionally expire sessions
