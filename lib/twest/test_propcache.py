import logging
import unittest
import ast

from bson.objectid import ObjectId
import tornado.gen
import tornado.ioloop
import tornado.testing
import motor

import two.propcache

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

    def get_new_ioloop(self):
        return tornado.ioloop.IOLoop.instance()
        
    @tornado.gen.coroutine
    def resetTables(self):
        yield motor.Op(self.app.mongodb.instanceprop.remove,
                       {})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'key':'x', 'val':1})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'key':'y', 'val':2})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'key':'ls', 'val':[1,2,3]})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'key':'map', 'val':{'one':1, 'two':2, 'three':3}})

    @tornado.testing.gen_test
    def test_simple(self):
        yield self.resetTables()

        ### _t = []; x = _t; y = _t; del x; del y
        ### x = True; y = True; del x; del y
        ### _t = []; x = _t; y = _t; _t.append(1)
        ### _t = {}; x = _t; y = _t; x['one'] = 1
        
class TestDeepCopy(unittest.TestCase):
    def test_deepcopy(self):
        deepcopy = two.propcache.deepcopy
        
        val = None
        self.assertTrue(deepcopy(val) is val)
        val = True
        self.assertTrue(deepcopy(val) is val)
        val = 5
        self.assertTrue(deepcopy(val) is val)
        val = -2.5
        self.assertTrue(deepcopy(val) is val)
        val = ObjectId()
        self.assertTrue(deepcopy(val) is val)

        val = []
        res = deepcopy(val)
        self.assertFalse(val is res)
        self.assertEqual(val, res)
        val.append(1)
        self.assertNotEqual(val, res)
        
        val = {}
        res = deepcopy(val)
        self.assertFalse(val is res)
        self.assertEqual(val, res)

        val = [1, [2, {}], {'x':'y', 'z':[1,2]}]
        res = deepcopy(val)
        self.assertFalse(val is res)
        self.assertEqual(val, res)
        self.assertTrue(val[0] is res[0])
        self.assertFalse(val[1] is res[1])
        self.assertEqual(val[1], res[1])
        self.assertFalse(val[2] is res[2])
        self.assertEqual(val[2], res[2])
        self.assertFalse(val[2]['z'] is res[2]['z'])
        self.assertEqual(val[2]['z'], res[2]['z'])
