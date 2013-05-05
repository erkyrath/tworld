from bson.objectid import ObjectId

class PlayerConnectionTable(object):
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = self.app.log

        self.map = {}  # maps connids to PlayerConnections.
        # If we wanted to set the system up with several twebs, we'd
        # need to either partition connids among them (so they don't
        # collide) or key this on (twwcid, connid). Currently we only
        # support a single tweb, so I am ignoring the problem.

    def get(self, connid):
        return self.map.get(connid, None)

    def add(self, connid, uidstr, stream):
        assert connid not in self.map, 'Connection ID already in use!'
        conn = PlayerConnection(connid, ObjectId(uidstr), stream)
        self.map[connid] = conn
        return conn

    def remove(self, connid):
        conn = self.map[connid]
        del self.map[connid]
        conn.connid = None
        conn.stream = None
        conn.twwcid = None

    def dumplog(self):
        self.log.debug('PlayerConnectionTable has %d entries', len(self.map))
        for (connid, conn) in sorted(self.map.items()):
            self.log.debug(' %d: uid %s (twwcid %d)', connid, conn.uid, conn.twwcid)

class PlayerConnection(object):
    def __init__(self, connid, uid, stream):
        self.connid = connid
        self.uid = uid   # an ObjectId
        self.stream = stream   # WebConnIOStream that handles this connection
        self.twwcid = stream.twwcid
        

