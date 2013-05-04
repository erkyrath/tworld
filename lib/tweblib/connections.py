"""
This table manages the websocket connections from clients.
"""

import tweblib.handlers

class ConnectionTable(object):
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.table = {}
        self.counter = 1

    def generate_connid(self):
        res = self.counter
        self.counter += 1
        return res

    def add(self, handler, uid):
        assert isinstance(handler, tweblib.handlers.PlayWebSocketHandler)
        assert handler.twconnid, 'handler.twconnid is not positive'
        conn = Connection(handler, uid)
        self.table[conn.connid] = conn
        return conn

    def find(self, connid):
        return self.table[connid]

    def remove(self, handler):
        if not handler.twconnid:
            return
        conn = self.table.get(handler.twconnid, None)
        if not conn:
            return
        del self.table[handler.twconnid]
        
class Connection(object):
    def __init__(self, handler, uid):
        self.handler = handler
        self.connid = handler.twconnid
        self.uid = uid

    def __repr__(self):
        return '<Connection %d>' % (self.connid,)
        
    def write_tw_error(self, msg):
        self.handler.write_tw_error(msg)
        
