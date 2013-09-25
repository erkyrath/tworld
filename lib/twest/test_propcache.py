"""
To run:   python3 -m tornado.testing twest.test_propcache
(The twest, two, twcommon modules must be in your PYTHON_PATH.)
"""

import logging
import unittest
import ast

from bson.objectid import ObjectId
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
        # The database and the tests must all run in the global IOLoop.
        return tornado.ioloop.IOLoop.instance()
        
    @tornado.gen.coroutine
    def resetTables(self):
        # Invent some arbitrary objids for the world and instance.
        self.exwid = ObjectId()
        self.exiid = ObjectId()
        self.exlocid = ObjectId()
        
        yield motor.Op(self.app.mongodb.instanceprop.remove,
                       {})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':self.exlocid,
                        'key':'x', 'val':1})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':self.exlocid,
                        'key':'y', 'val':2})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':self.exlocid,
                        'key':'true', 'val':True})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':self.exlocid,
                        'key':'ls', 'val':[1,2,3]})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':self.exlocid,
                        'key':'map', 'val':{'one':1, 'two':2, 'three':3}})
        
    @tornado.gen.coroutine
    def get_db_prop(self, tup):
        query = two.propcache.PropCache.query_for_tuple(tup)
        res = yield motor.Op(self.app.mongodb[tup[0]].find_one, query)
        if res is None:
            return NotFound
        return res['val']

    @tornado.testing.gen_test
    def test_simple_ops(self):
        yield self.resetTables()
        cache = two.propcache.PropCache(self.app)
        deps = set()

        instq = lambda key: ('instanceprop', self.exiid, self.exlocid, key)

        # Get some values.

        res = yield cache.get(instq('x'), dependencies=deps)
        self.assertEqual(res.val, 1)
        self.assertTrue(res.found)
        self.assertFalse(res.dirty)
        self.assertFalse(res.isdirty())
        self.assertEqual(res.key, 'x')
        self.assertFalse(res.mutable)
        self.assertTrue(instq('x') in deps)
        self.assertTrue(cache.get_by_object(res.val) is None)
        
        res = yield cache.get(instq('qqq'), dependencies=deps)
        self.assertTrue(res is None)
        res = yield cache.get(instq('qqq'), dependencies=deps)
        self.assertTrue(res is None)
        self.assertTrue(instq('qqq') in deps)
        # Peek into cache internals for additional testing
        res = cache.propmap[instq('qqq')]
        self.assertFalse(res.found)
        self.assertFalse(res.dirty)
        self.assertFalse(res.isdirty())
        self.assertEqual(res.key, 'qqq')
        
        res = yield cache.get(instq('ls'), dependencies=deps)
        self.assertEqual(res.val, [1,2,3])
        self.assertTrue(res.found)
        self.assertFalse(res.dirty)
        self.assertFalse(res.isdirty())
        self.assertEqual(res.key, 'ls')
        self.assertTrue(res.mutable)
        self.assertTrue(instq('ls') in deps)
        self.assertTrue(cache.get_by_object(res.val) is res)

        res2 = yield cache.get(instq('ls'), dependencies=deps)
        self.assertTrue(res is res2)

        res = yield cache.get(instq('map'), dependencies=deps)
        self.assertEqual(res.val, {'one':1, 'two':2, 'three':3})
        self.assertTrue(res.found)
        self.assertFalse(res.dirty)
        self.assertFalse(res.isdirty())
        self.assertEqual(res.key, 'map')
        self.assertTrue(res.mutable)
        self.assertTrue(instq('map') in deps)
        self.assertTrue(cache.get_by_object(res.val) is res)

        self.assertEqual(cache.dirty_entries(), [])

        # Set some values.

        yield cache.set(instq('y'), 7)
        res = yield cache.get(instq('y'), dependencies=deps)
        self.assertEqual(res.val, 7)
        self.assertTrue(res.isdirty())
        
        res = yield self.get_db_prop(instq('y'))
        self.assertEqual(res, 2)

        yield cache.set(instq('z'), 3)
        res = yield cache.get(instq('z'), dependencies=deps)
        self.assertEqual(res.val, 3)
        self.assertTrue(res.isdirty())
        
        res = yield self.get_db_prop(instq('z'))
        self.assertEqual(res, NotFound)

        self.assertEqual(len(cache.dirty_entries()), 2)

        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])
        
        res = yield cache.get(instq('y'), dependencies=deps)
        self.assertEqual(res.val, 7)
        res = yield self.get_db_prop(instq('y'))
        self.assertEqual(res, 7)
        
        res = yield cache.get(instq('z'), dependencies=deps)
        self.assertEqual(res.val, 3)
        res = yield self.get_db_prop(instq('z'))
        self.assertEqual(res, 3)

        # Delete some values.

        yield cache.delete(instq('x'))
        res = yield cache.get(instq('x'), dependencies=deps)
        self.assertTrue(res is None)

        res = yield self.get_db_prop(instq('x'))
        self.assertEqual(res, 1)
        
        yield cache.delete(instq('qqqq'))
        res = yield cache.get(instq('qqqq'), dependencies=deps)
        self.assertTrue(res is None)
        
        yield cache.delete(instq('map'))
        res = yield cache.get(instq('map'), dependencies=deps)
        self.assertTrue(res is None)

        res = yield self.get_db_prop(instq('map'))
        self.assertEqual(res, {'one':1, 'two':2, 'three':3})
        
        self.assertEqual(len(cache.dirty_entries()), 3)

        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])
        
        res = yield self.get_db_prop(instq('x'))
        self.assertEqual(res, NotFound)
        res = yield self.get_db_prop(instq('qqqq'))
        self.assertEqual(res, NotFound)
        res = yield self.get_db_prop(instq('map'))
        self.assertEqual(res, NotFound)
        
        yield cache.delete(instq('x'))
        res = yield cache.get(instq('x'), dependencies=deps)
        self.assertTrue(res is None)

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
