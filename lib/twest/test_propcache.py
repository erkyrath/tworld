### This doesn't work. (The test hangs trying to deal with mongodb.)

import logging
import unittest
import ast

from bson.objectid import ObjectId
import tornado.gen
import tornado.testing
import motor

class MockApplication:
    def __init__(self):
        self.log = logging.getLogger('tworld')

        # Set up a mongo connection. This can't be yieldy, because it's
        # called from setUpClass().
        self.client = motor.MotorClient(tz_aware=True).open_sync()
        self.mongodb = self.client['testdb']

    def disconnect(self):
        self.client.disconnect()

class TestPropcache(tornado.testing.AsyncTestCase):
    @classmethod
    def setUpClass(cla):
        cla.app = MockApplication()
        cla.app.log.info('Set up MockApplication')

    @classmethod
    def tearDownClass(cla):
        #cla.app.log.info('Tear down MockApplication')
        cla.app.disconnect()
        cla.app = None

    @tornado.gen.coroutine
    def resetTables(self):
        self.app.log.info('### B %s %s', self.app.mongodb, self.app.mongodb['instanceprop'])
        yield motor.Op(self.app.mongodb['instanceprop'].remove,
                       {})
        self.app.log.info('### C')
        yield motor.Op(self.app.mongodb['instanceprop'].insert,
                       {'key':'x', 'val':1})
        self.app.log.info('### D')

    #@tornado.testing.gen_test
    def test_simple(self):
        ### I think this can't be made to work in Motor 0.1.1?
        self.app.log.info('### A')
        #yield self.resetTables()
        def func(result, error):
            self.app.log.info('### ok')
            self.stop()
        self.app.mongodb['instanceprop'].remove({}, callback=func)
        self.app.log.info('### waiting...')
        self.wait()

        ### _t = []; x = _t; y = _t; del x; del y
        ### x = True; y = True; del x; del y
        
