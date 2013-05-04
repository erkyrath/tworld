"""
Manage the connections to the MongoDB server and the Tworld server.
"""

import socket

import tornado.gen
import tornado.ioloop
import tornado.iostream

import motor

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


    @tornado.gen.coroutine
    def monitor_mongo_status(self):
        if (self.mongotimerbusy):
            self.log.warning('monitor_mongo_status: already in flight; did a previous call jam?')
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
                self.mongo.disconnect()
                self.mongo = None
                self.app.mongodb = None
            
        if (not self.mongoavailable):
            try:
                self.mongo = motor.MotorClient()
                res = yield motor.Op(self.mongo.open)
                ### maybe authenticate to a database?
                self.mongoavailable = True
                self.app.mongodb = self.mongo[self.app.twopts.mongo_database]
                self.log.info('Mongo client open')
            except Exception as ex:
                self.mongoavailable = False
                self.app.mongodb = None
                self.log.error('Mongo client not open: %s', ex)
        
        self.mongotimerbusy = False


    def monitor_tworld_status(self):
        # This routine is *not* a coroutine, because it doesn't do anything
        # yieldy.
        
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
            ### grab connection list from conntable
            self.tworld.write(wcproto.message(0, {'cmd':'connect', 'connections':[]}))
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
        self.twbuffer.extend(dat)
        while True:
            # This slices a chunk off the buffer and returns it, if a
            # complete chunk is available.
            try:
                ### this unnecessarily de-jsons the message! We only care
                ### about raw, unless connid turns out to be zero.
                tup = wcproto.check_buffer(self.twbuffer, namespace=True)
                if not tup:
                    return
            except Exception as ex:
                self.log.info('Malformed message: %s', ex)
                continue
            
            (connid, raw, obj) = tup

            # Special case: if we're connecting, only accept 'connectok'
            if not self.tworldavailable:
                if (connid != 0):
                    self.log.warning('Cannot pass message back to client before tworld is available!')
                elif getattr(obj, 'cmd', None) != 'connectok':
                    self.log.warning('Cannot handle command before tworld is available!')
                else:
                    self.log.info('Tworld socket available')
                    self.tworldavailable = True
                    self.tworldtimerbusy = False
                continue
            
            if (connid != 0):
                # Pass the raw message along to the client.
                try:
                    conn = self.app.twconntable.find(connid)
                    if not conn.available:
                        raise Exception('Connection not yet available')
                    conn.write_message(raw)
                except Exception as ex:
                    self.log.error('Unable to pass message back to connection %d (%s): %s', connid, raw[0:50], ex)
            else:
                # It's for us.
                try:
                    cmd = obj.cmd
                    raise Exception('### no server commands are implemented')
                except Exception as ex:
                    self.log.error('Problem handling server command (%s): %s', raw[0:50], ex)
        

    def close_tworld(self, dat):
        self.log.error('Connection to tworld closed.')
        self.tworld = None
        self.twbuffer = None
        self.tworldavailable = False
        self.tworldtimerbusy = False
