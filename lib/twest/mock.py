"""
Infrastructure for unit tests.
"""

import logging

import tornado.gen
import tornado.ioloop
import tornado.testing
import motor

import twcommon.misc
import two.propcache
import two.symbols

NotFound = twcommon.misc.SuiGeneris('NotFound')

class MockApplication:
    """
    Mock for the Tworld Application class. This contains a DB connection.
    Depending on the setup arguments, it builds various other components
    for itself as well.
    """
    def __init__(self, propcache=False, globals=False):
        self.log = logging.getLogger('tworld')

        # Set up a mongo connection. This can't be yieldy, because it's
        # called from setUpClass().
        self.client = motor.MotorClient(tz_aware=True).open_sync()
        self.mongodb = self.client['testdb']

        if propcache:
            # Set up a propcache, which is needed to evaluate property expressions.
            self.propcache = two.propcache.PropCache(self)

        if globals:
            # Set up the global symbol table.
            self.global_symbol_table = two.symbols.define_globals()

    def disconnect(self):
        self.client.disconnect()

class MockAppTestCase(tornado.testing.AsyncTestCase):
    """
    Base class for Tworld test cases that need an Application to run in.
    The mockappargs dict determines the setup parameters of the
    MockApplication.
    """
    mockappargs = {}
    
    @classmethod
    def setUpClass(cla):
        cla.app = MockApplication(**cla.mockappargs)
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
