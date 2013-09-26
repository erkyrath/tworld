import logging

import tornado.gen
import tornado.ioloop
import tornado.testing
import motor

import twcommon.misc
import two.propcache

NotFound = twcommon.misc.SuiGeneris('NotFound')

class MockApplication:
    def __init__(self):
        self.log = logging.getLogger('tworld')

        # Set up a mongo connection. This can't be yieldy, because it's
        # called from setUpClass().
        self.client = motor.MotorClient(tz_aware=True).open_sync()
        self.mongodb = self.client['testdb']

        # Set up a propcache, which is needed to evaluate property expressions.
        self.propcache = two.propcache.PropCache(self)

    def disconnect(self):
        self.client.disconnect()

class MockAppTestCase(tornado.testing.AsyncTestCase):
    @classmethod
    def setUpClass(cla):
        cla.app = MockApplication()
        #cla.app.log.info('Set up MockApplication')

    @classmethod
    def tearDownClass(cla):
        #cla.app.log.info('Tear down MockApplication')
        cla.app.disconnect()
        cla.app = None

    def get_new_ioloop(self):
        # The database and the tests must all run in the global IOLoop.
        return tornado.ioloop.IOLoop.instance()
        
    @tornado.gen.coroutine
    def get_db_prop(self, tup):
        query = two.propcache.PropCache.query_for_tuple(tup)
        res = yield motor.Op(self.app.mongodb[tup[0]].find_one, query)
        if res is None:
            return NotFound
        return res['val']

    @tornado.gen.coroutine
    def resetTables(self):
        # This will probably be overridden for each test case to do more
        # setup.
        yield motor.Op(self.app.mongodb.instanceprop.remove,
                       {})
