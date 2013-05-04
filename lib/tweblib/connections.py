"""
This table manages the websocket connections from clients.

The table contains Connection objects. A connection is mostly a wrapper
for an active PlayWebSocketHandler, and has a nonzero connection ID as a
key. (The connection ID is requested by the handler before it adds itself
to the table. We use simple incrementing integers for the ID. There's no
need to track across tweb sessions, because if tweb crashes, we lose all
the websockets anyway...)

A Connection is "available" once it has been sent to the tworld (and we
got an ack back). If tworld crashes, all connections become unavailable
until it returns (and then we have to ack them again).
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

    def as_dict(self):
        return dict(self.table)

    def add(self, handler, uid):
        """Add the handler to the table, as a new Connection. It will
        initially be unavailable. Returns the Connection.
        """
        assert isinstance(handler, tweblib.handlers.PlayWebSocketHandler)
        assert handler.twconnid, 'handler.twconnid is not positive'
        conn = Connection(handler, uid)
        self.table[conn.connid] = conn
        return conn

    def find(self, connid):
        """Return the connection with the given connid. Throws an exception
        if not found.
        """
        return self.table[connid]

    def remove(self, handler):
        if not handler.twconnid:
            return
        conn = self.table.get(handler.twconnid, None)
        if not conn:
            return
        assert handler.twconnid == conn.connid
        conn.handler = None
        conn.uid = None
        conn.available = False
        del self.table[handler.twconnid]
        
class Connection(object):
    def __init__(self, handler, uid):
        self.handler = handler
        self.connid = handler.twconnid
        self.uid = uid
        self.available = False

    def __repr__(self):
        return '<Connection %d>' % (self.connid,)
        
    def write_tw_error(self, msg):
        """Write a JSON error-reporting command through the socket.
        """
        if self.handler:
            self.handler.write_tw_error(msg)
