from bson.objectid import ObjectId

from twcommon import wcproto

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

        self.uidmap = {} # maps uids (ObjectIds) to sets of PlayerConnections.

    def get(self, connid):
        """Look up a player connection by its ID. Returns None if not found.
        """
        return self.map.get(connid, None)

    def get_for_uid(self, uid):
        """Returns all player connections matching the given user id, or
        None.
        """
        uset = self.uidmap.get(uid, None)
        if not uset:
            return None
        return list(uset)

    def count_for_uid(self, uid):
        """Returns number of player connections matching the given user id.
        """
        uset = self.uidmap.get(uid, None)
        if not uset:
            return 0
        return len(uset)

    def all(self):
        """A (non-dynamic) list of all player connections.
        """
        return list(self.map.values())

    def as_dict(self):
        """A (non-dynamic) map of all player connections.
        """
        return dict(self.map)

    def add(self, connid, uidstr, email, stream):
        """Add a new player connection. This should only be invoked
        from the "connect" and "playeropen" commands.
        """
        assert connid not in self.map, 'Connection ID already in use!'
        conn = PlayerConnection(self, connid, ObjectId(uidstr), email, stream)
        self.map[connid] = conn
        uset = self.uidmap.get(conn.uid, None)
        if uset:
            uset.add(conn)
        else:
            self.uidmap[conn.uid] = set( (conn,) )
        return conn

    def remove(self, connid):
        """Remove a dead player connection. This should only be invoked
        from the "disconnect" and "playerconnect" commands.
        """
        conn = self.map[connid]
        del self.map[connid]
        uset = self.uidmap.get(conn.uid, None)
        if uset:
            uset.remove(conn)
            if not uset:
                del self.uidmap[conn.uid]
        conn.connid = None
        conn.stream = None
        conn.twwcid = None

    def dumplog(self):
        self.log.debug('PlayerConnectionTable has %d entries', len(self.map))
        for (connid, conn) in sorted(self.map.items()):
            self.log.debug(' %d: email %s, uid %s (twwcid %d)', connid, conn.email, conn.uid, conn.twwcid)
        uls = [ len(uset) for uset in self.uidmap.values() ]
        uidsum = sum(uls)
        if 0 in uls:
            self.log.debug('ERROR: empty set in uidmap!')
        if uidsum != len(self.map):
            self.log.debug('ERROR: uidmap has %d entries!', uidsum)

class PlayerConnection(object):
    def __init__(self, table, connid, uid, email, stream):
        self.table = table
        self.connid = connid
        self.uid = uid   # an ObjectId
        self.email = email  # used only for log messages, not DB work
        self.stream = stream   # WebConnIOStream that handles this connection
        self.twwcid = stream.twwcid

        # Map action codes to bits of script, for the player's current
        # location (and focus).
        # (We don't try to keep these in the database, because if the
        # server crashes, it'll regenerate all this stuff for the connected
        # players as soon as it comes back.)
        self.localeactions = {}
        self.focusactions = {}
        self.populaceactions = {}

        # Sets of what change keys will cause the location (focus, etc)
        # text to change.
        self.localedependencies = set()
        self.focusdependencies = set()
        self.populacedependencies = set()
        
        
    def write(self, msg):
        """Shortcut to send a message to a player via this connection.
        """
        try:
            self.stream.write(wcproto.message(self.connid, msg))
            return True
        except Exception as ex:
            self.table.log.error('Unable to write to %d: %s', self.connid, ex)
            return False
