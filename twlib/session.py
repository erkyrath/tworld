
# Currently, this just keeps sessions in memory.

import os
import binascii

class SessionMgr(object):

    def __init__(self):
        # Maps sessionids to session dicts.
        self.sessionmap = {}
    
    def create_session(self, handler, userid):
        # Generate a random sessionid.
        byt = os.urandom(24)
        sessionid = binascii.hexlify(byt)
        handler.set_secure_cookie('sessionid', sessionid)
        
        sess = {
            'userid': userid,
            'sid': sessionid,
            'ipaddr': handler.request.remote_ip
            }
        self.sessionmap[sessionid] = sess
        return sess

    def find_session(self, handler):
        sessionid = handler.get_secure_cookie('sessionid')
        if not sessionid:
            return None
        sess = self.sessionmap.get(sessionid, None)
        return sess

    def remove_session(self, handler):
        sessionid = handler.get_secure_cookie('sessionid')
        if (sessionid):
            self.sessionmap.pop(sessionid)
        handler.clear_cookie('sessionid')
    
    ### occasionally expire sessions
