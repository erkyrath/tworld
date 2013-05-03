
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
        assert handler.connid, 'handler.connid is not positive'
        conn = Connection(handler, uid)
        self.table[conn.connid] = conn
        return conn
        
class Connection(object):
    def __init__(self, handler, uid):
        self.handler = handler
        self.connid = handler.connid
        self.uid = uid
        
    def write_tw_error(self, msg):
        self.handler.write_tw_error(msg)
        
