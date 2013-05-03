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
                    self.log.error('monitor_mongo_status: Mongo client not alive')
                    self.mongoavailable = False
            except Exception as ex:
                self.log.error('monitor_mongo_status: Mongo client not alive: %s', ex)
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
                self.log.info('monitor_mongo_status: Mongo client open')
            except Exception as ex:
                self.mongoavailable = False
                self.app.mongodb = None
                self.log.error('monitor_mongo_status: Mongo client not open: %s', ex)
        
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
        except Exception as ex:
            self.log.error('monitor_tworld_status: Could not open tworld socket: %s', ex)
            self.tworldavailable = False
            self.tworldtimerbusy = False
            return
            
        self.log.info('monitor_tworld_status: Tworld socket open')

        # But it won't count as available until we get a response from it.
        try:
            ### grab connection list from conntable
            self.tworld.write(wcproto.message(wcproto.msgtype.connect, 0, {'cmd':'connect', 'connections':[]}))
        except Exception as ex:
            self.log.error('monitor_tworld_status: Could not write connect message to tworld socket: %s', ex)
            self.tworld = None
            self.tworldavailable = False
            self.tworldtimerbusy = False
            return
        
        self.tworld.read_until_close(self.close_tworld, self.read_tworld_data)
        # Exit, still holding tworldtimerbusy. We'll drop it if the connect
        # pong arrives, or if the socket closes.

    def read_tworld_data(self, dat):
        self.log.info('### tworld read data: %s', dat)

    def close_tworld(self, dat):
        self.log.error('Connection to tworld closed.')
        self.tworld = None
        self.tworldavailable = False
        self.tworldtimerbusy = False