"""
Manage the connections to the MongoDB server and the Tworld server.
"""

import socket

import tornado.gen
import tornado.ioloop
import tornado.iostream
import tornado.platform

import motor

import twcommon.localize
from twcommon import wcproto

class ServerMgr(object):
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = self.app.twlog
        
        # This will be the Motor (MongoDB) connection. We'll open it in the
        # first monitor_mongo_status call.
        self.mongo = None
        self.mongoavailable = False  # true if self.mongo exists and is open
        self.mongotimerbusy = False  # true while monitor_mongo_status runs
        
        # We also manage self.app.mongodb, a MotorDatabase. This must be
        # non-None exactly when mongoavailable is true.

        # This will be the Tworld connection. Handled by monitor_tworld_status.
        self.tworld = None
        self.tworldavailable = False  # true if self.tworld exists and is ready
        self.tworldtimerbusy = False

        # Buffer for Tworld message data.
        self.twbuffer = None

    def init_timers(self):
        """Start the ioloop timers for this module.
        """
        ioloop = tornado.ioloop.IOLoop.instance()
        
        # The mongo status monitor. We set up one call immediately, and then
        # try again every five seconds.
        ioloop.add_callback(self.monitor_mongo_status)
        res = tornado.ioloop.PeriodicCallback(self.monitor_mongo_status, 5000)
        res.start()

        # The tworld status monitor. Same deal.
        ioloop.add_callback(self.monitor_tworld_status)
        res = tornado.ioloop.PeriodicCallback(self.monitor_tworld_status, 5000)
        res.start()

    def tworld_write(self, connid, msg):
        """Shortcut for writing to the tworld process. May raise exceptions.
        """
        if not self.tworldavailable:
            raise Exception('Tworld service is not available.')
        if type(msg) is dict:
            val = wcproto.message(connid, msg)
        else:
            val = wcproto.message(connid, msg, alreadyjson=True)
        self.tworld.write(val)

    def mongo_disconnect(self):
        """Close the connection to mongodb. (The monitor will start it
        right back up again, or try to.)
        """
        if self.mongo:
            try:
                self.mongo.disconnect()
            except Exception as ex:
                self.log.error('Error disconnecting mongo: %s', ex)
        self.mongoavailable = False
        self.mongo = None
        self.app.mongodb = None

    @tornado.gen.coroutine
    def monitor_mongo_status(self):
        """Check the status of the MongoDB connection. If the server has
        died, close the socket. If the socket is closed (or has never been
        opened), try to open it.

        This is called once when the app launches, to open the initial
        connection, and every few seconds thereafter.

        The mongotimerbusy flag protects us from really slow connection
        attempts. Not sure why that would happen, but if it does, we'll
        avoid piling up multiple attempts. On the down side, if the function
        throws an uncaught exception, the flag will be stuck forever.
        (So don't do that.)
        """
        if (self.mongotimerbusy):
            self.log.warning('monitor_mongo_status: already in flight; did a previous call jam?')
            return
        if (self.app.caughtinterrupt):
            self.log.warning('monitor_mongo_status: shutting down, never mind')
            return
        self.mongotimerbusy = True
        
        if (self.mongoavailable):
            try:
                res = yield motor.Op(self.mongo.admin.command, 'ping')
                if (not res):
                    self.log.error('Mongo client not alive')
                    self.mongoavailable = False
            except Exception as ex:
                self.log.error('Mongo client not alive: %s', ex)
                self.mongoavailable = False
            if (not self.mongoavailable):
                self.mongo_disconnect()
            
        if (not self.mongoavailable):
            try:
                self.mongo = motor.MotorClient(tz_aware=True)
                res = yield motor.Op(self.mongo.open)
                ### maybe authenticate to a database?
                self.mongoavailable = True
                self.app.mongodb = self.mongo[self.app.twopts.mongo_database]
                self.log.info('Mongo client open')
                # Schedule a callback to load up the localization data.
                tornado.ioloop.IOLoop.instance().add_callback(self.load_localization)
            except Exception as ex:
                self.mongoavailable = False
                self.app.mongodb = None
                self.log.error('Mongo client not open: %s', ex)
        
        self.mongotimerbusy = False

    @tornado.gen.coroutine
    def load_localization(self):
        if (self.mongoavailable):
            try:
                self.app.twlocalize = yield twcommon.localize.load_localization(self.app, clientonly=True)
                self.log.info('Localization data loaded.')
            except Exception as ex:
                self.log.warning('Caught exception (loading localization data): %s', ex)
            

    def monitor_tworld_status(self):
        """Check the status of the Tworld connection. If the socket is
        closed (or has never been opened), try to open it.

        This is called once when the app launches, to open the initial
        connection, and every few seconds thereafter.

        The tworldtimerbusy flag protects us from really slow connection
        attempts.
        
        This routine is *not* a coroutine, because it doesn't do anything
        yieldy. Instead, it has an old-fashioned (ugly) callback structure.
        """
        
        if (self.tworldtimerbusy):
            self.log.warning('monitor_tworld_status: already in flight; did a previous call jam?')
            return

        if (self.tworldavailable):
            # Nothing to do
            return

        # We're going to hold this "lock" until the connection attempt
        # fails or definitely succeeds.
        self.tworldtimerbusy = True

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            # We do a sync connect, because I don't understand how the
            # async version works. (IOStream.connect seems to hang forever
            # when the other process is down?)
            sock.connect(('localhost', self.app.twopts.tworld_port))
            sock.setblocking(0)
            tornado.platform.auto.set_close_exec(sock.fileno())
            self.tworld = tornado.iostream.IOStream(sock)
            self.twbuffer = bytearray()
        except Exception as ex:
            self.log.error('Could not open tworld socket: %s', ex)
            self.tworldavailable = False
            self.tworldtimerbusy = False
            return
            
        self.log.info('Tworld socket open')

        # But it won't count as available until we get a response from it.
        try:
            arr = []
            for (connid, conn) in self.app.twconntable.as_dict().items():
                arr.append( { 'connid':connid, 'uid':str(conn.uid), 'email':conn.email } )
            self.tworld.write(wcproto.message(0, {'cmd':'connect', 'connections':arr}))
        except Exception as ex:
            self.log.error('Could not write connect message to tworld socket: %s', ex)
            self.tworld = None
            self.twbuffer = None
            self.tworldavailable = False
            self.tworldtimerbusy = False
            return
        
        self.tworld.read_until_close(self.close_tworld, self.read_tworld_data)
        # Exit, still holding tworldtimerbusy. We'll drop it if the connect
        # pong arrives, or if the socket closes.

    def read_tworld_data(self, dat):
        """Callback from tworld reading handler.
        """
        self.twbuffer.extend(dat)
        while True:
            # This slices a chunk off the buffer and returns it, if a
            # complete chunk is available.
            try:
                ### this unnecessarily de-jsons the message! We only care
                ### about raw, in the common case.
                tup = wcproto.check_buffer(self.twbuffer, namespace=True)
                if not tup:
                    # No more complete messages to pull! (This is the
                    # only return point from this method.)
                    return
            except Exception as ex:
                self.log.warning('Malformed message: %s', ex)
                continue

            try:
                (connid, raw, obj) = tup
                self.handle_tworld_message(connid, raw, obj)
            except Exception as ex:
                self.log.warning('Error handling tworld message', exc_info=True)
            continue

    def handle_tworld_message(self, connid, raw, obj):
        """Handle a single message from tworld, or throw an exception.
        (This does not do anything yieldy.)
        """
        if not self.tworldavailable:
            # Special case: if we're connecting, only accept 'connectok'
            if (connid != 0):
                self.log.warning('Cannot pass message back to client before tworld is available!')
            elif getattr(obj, 'cmd', None) != 'connectok':
                self.log.warning('Cannot handle command before tworld is available!')
            else:
                self.log.info('Tworld socket available')
                self.tworldavailable = True
                self.tworldtimerbusy = False
            return
        
        if (connid != 0):
            # Pass the raw message along to the client. (As UTF-8.)
            try:
                conn = self.app.twconntable.find(connid)
                if not conn.available and obj.cmd != 'error':
                    raise Exception('Connection not available')
                conn.handler.write_message(raw.decode())
            except Exception as ex:
                self.log.error('Unable to pass message back to connection %d (%s): %s', connid, raw[0:50], ex)
            return

        # It's for us.
        cmd = obj.cmd
        
        if cmd == 'playerok':
            # accept the connection
            try:
                conn = self.app.twconntable.find(obj.connid)
                if conn.available:
                    raise Exception('Connection is already available')
                self.log.info('Player connection registered: %s (connid %d)', conn.email, conn.connid)
                conn.available = True
            except Exception as ex:
                self.log.error('Unable to process playerok: %s', ex)
            return
        
        if cmd == 'playernotok':
            # kill the connection
            try:
                conn = self.app.twconntable.find(obj.connid)
                if conn.available:
                    raise Exception('Connection is already available')
                self.log.info('Player connection rejected by Tworld: %s (connid %d)', conn.email, conn.connid)
                errmsg = getattr(obj, 'text', 'Connection rejected by Tworld')
                conn.close(errmsg)
            except Exception as ex:
                self.log.error('Unable to process playernotok: %s', ex)
            return

        if cmd == 'messageall':
            # send a message to every connection
            msgobj = { 'cmd':'message', 'text':obj.text }
            for conn in self.app.twconntable.all():
                try:
                    conn.handler.write_message(msgobj)
                except Exception as ex:
                    self.log.error('Unable to send messageall message: %s', ex)
            return
        
        raise Exception('Tworld message not implemented: %s' % (cmd,))
    

    def close_tworld(self, dat):
        """Callback from tworld reading handler.
        """
        self.log.error('Connection to tworld closed.')
        # All connections we're holding are back to unavailable status.
        for (connid, conn) in self.app.twconntable.as_dict().items():
            conn.available = False
        self.tworld = None
        self.twbuffer = None
        self.tworldavailable = False
        self.tworldtimerbusy = False

        
