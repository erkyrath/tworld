"""
To run:   python3 -m tornado.testing twest.test_propcache
(The twest, two, twcommon modules must be in your PYTHON_PATH.)
"""

import datetime
import logging
import unittest
import ast

from bson.objectid import ObjectId
import tornado.gen
import tornado.testing
import motor

import twcommon.misc
import two.propcache

import twest.mock
from twest.mock import NotFound

class TestPropcache(twest.mock.MockAppTestCase):
    
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
        
    @tornado.testing.gen_test
    def test_simple_ops(self):
        yield self.resetTables()
        
        # Fresh propcache for each test (don't use app.propcache).
        cache = two.propcache.PropCache(self.app)
        deps = set()

        instq = lambda key: ('instanceprop', self.exiid, self.exlocid, key)

        # Get some values.

        res = yield cache.get(instq('x'), dependencies=deps)
        self.assertEqual(res.val, 1)
        self.assertTrue(res.found)
        self.assertFalse(res.dirty)
        self.assertFalse(res.haschanged())
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
        self.assertFalse(res.haschanged())
        self.assertEqual(res.key, 'qqq')
        
        res = yield cache.get(instq('ls'), dependencies=deps)
        self.assertEqual(res.val, [1,2,3])
        self.assertTrue(res.found)
        self.assertFalse(res.dirty)
        self.assertFalse(res.haschanged())
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
        self.assertFalse(res.haschanged())
        self.assertEqual(res.key, 'map')
        self.assertTrue(res.mutable)
        self.assertTrue(instq('map') in deps)
        self.assertTrue(cache.get_by_object(res.val) is res)

        self.assertEqual(cache.note_changed_entries(), [])
        self.assertEqual(cache.dirty_entries(), [])

        # Set some values.

        yield cache.set(instq('y'), 7)
        res = yield cache.get(instq('y'), dependencies=deps)
        self.assertEqual(res.val, 7)
        self.assertTrue(res.dirty)
        self.assertFalse(res.haschanged())
        
        res = yield self.get_db_prop(instq('y'))
        self.assertEqual(res, 2)

        yield cache.set(instq('z'), 3)
        res = yield cache.get(instq('z'), dependencies=deps)
        self.assertEqual(res.val, 3)
        self.assertTrue(res.dirty)
        self.assertFalse(res.haschanged())
        
        res = yield self.get_db_prop(instq('z'))
        self.assertEqual(res, NotFound)

        self.assertEqual(cache.note_changed_entries(), [])
        self.assertEqual(len(cache.dirty_entries()), 2)

        self.assertEqual(cache.note_changed_entries(), [])
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

        yield cache.set(instq('listtuple'), (1,2,3))
        res = yield cache.get(instq('listtuple'), dependencies=deps)
        self.assertEqual(res.val, (1,2,3))
        
        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])

        res = yield self.get_db_prop(instq('listtuple'))
        self.assertEqual(res, [1,2,3])
        
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
        
        self.assertEqual(cache.note_changed_entries(), [])
        self.assertEqual(len(cache.dirty_entries()), 3)

        self.assertEqual(cache.note_changed_entries(), [])
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

    @tornado.testing.gen_test
    def test_mutable_values(self):
        yield self.resetTables()
        
        # Fresh propcache for each test (don't use app.propcache).
        cache = two.propcache.PropCache(self.app)

        instq = lambda key: ('instanceprop', self.exiid, self.exlocid, key)

        res = yield cache.get(instq('ls'))
        self.assertFalse(res.haschanged())

        ls = res.val
        ls.append(4)
        
        self.assertFalse(res.dirty)
        self.assertTrue(res.haschanged())
        
        res2 = yield cache.get(instq('ls'))
        self.assertEqual(res2.val, [1,2,3,4])
        
        res = yield self.get_db_prop(instq('ls'))
        self.assertEqual(res, [1,2,3])

        self.assertEqual(len(cache.note_changed_entries()), 1)
        self.assertEqual(len(cache.dirty_entries()), 1)

        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])
        
        res = yield self.get_db_prop(instq('ls'))
        self.assertEqual(res, [1,2,3,4])
        
        res2 = yield cache.get(instq('ls'))
        self.assertEqual(res2.val, [1,2,3,4])
        
        res = yield cache.get(instq('map'))
        map = res.val
        self.assertTrue(cache.get_by_object(map) is res)

        ls[0] = 'zero'
        map['zero'] = 'ZERO'

        self.assertTrue(cache.get_by_object(map) is res)
        self.assertEqual(len(cache.note_changed_entries()), 2)
        self.assertEqual(len(cache.dirty_entries()), 2)

        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])
        
        res2 = yield cache.get(instq('ls'))
        self.assertEqual(res2.val, ['zero',2,3,4])
        res2 = yield cache.get(instq('map'))
        self.assertEqual(res2.val, {'one':1, 'two':2, 'three':3, 'zero':'ZERO'})

        res = yield self.get_db_prop(instq('ls'))
        self.assertEqual(res, ['zero',2,3,4])
        res = yield self.get_db_prop(instq('map'))
        self.assertEqual(res, {'one':1, 'two':2, 'three':3, 'zero':'ZERO'})
        
        map['tt'] = 44
        yield cache.set(instq('map'), {'tt':33})
        map['tt'] = 55

        self.assertEqual(cache.note_changed_entries(), []) ####
        self.assertEqual(len(cache.dirty_entries()), 1)

        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])
        
        res2 = yield cache.get(instq('map'))
        self.assertEqual(res2.val, {'tt':33})
        self.assertFalse(res2.val is map)

        res = yield self.get_db_prop(instq('map'))
        self.assertEqual(res, {'tt':33})
        
    @tornado.testing.gen_test
    def test_prop_aliasing(self):
        yield self.resetTables()
        
        # Fresh propcache for each test (don't use app.propcache).
        cache = two.propcache.PropCache(self.app)

        instq = lambda key: ('instanceprop', self.exiid, self.exlocid, key)

        # x = True; y = True; del x; del y

        yield cache.set(instq('xx'), True)
        yield cache.set(instq('yy'), True)
        yield cache.delete(instq('xx'))
        yield cache.delete(instq('yy'))

        res = yield cache.get(instq('xx'))
        self.assertTrue(res is None)
        res = yield cache.get(instq('yy'))
        self.assertTrue(res is None)
        
        self.assertTrue(cache.get_by_object(True) is None)

        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])

        # _t = []; x = _t; y = _t; del x; del y
        
        ls = [2,3,4]
        yield cache.set(instq('xxx'), ls)
        yield cache.set(instq('yyy'), ls)

        res = cache.get_by_object(ls)  # might get either prop
        self.assertTrue(res.val is ls)
        self.assertTrue(res.key in ('xxx', 'yyy'))
        
        yield cache.delete(instq('xxx'))
        yield cache.delete(instq('yyy'))
        
        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])

        res = yield cache.get(instq('xxx'))
        self.assertTrue(res is None)
        res = yield cache.get(instq('yyy'))
        self.assertTrue(res is None)
        
        # _t = []; x = _t; y = _t; _t.append(1)

        ls = [2,3,4]
        yield cache.set(instq('xx'), ls)
        yield cache.set(instq('yy'), ls)

        ls.append(1)
        
        res = yield cache.get(instq('xx'))
        self.assertEqual(res.val, [2,3,4,1])
        res = yield cache.get(instq('yy'))
        self.assertEqual(res.val, [2,3,4,1])
        
        ls.insert(0, -1)
        
        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])

        res = yield cache.get(instq('xx'))
        self.assertEqual(res.val, [-1,2,3,4,1])
        res = yield cache.get(instq('yy'))
        self.assertEqual(res.val, [-1,2,3,4,1])

        # _t = {}; x = _t; y = _t; x['one'] = 1
        
        map = {}
        yield cache.set(instq('map'), map)
        yield cache.set(instq('map2'), map)

        map['one'] = 1
        
        self.assertEqual(cache.note_changed_entries(), [])
        yield cache.write_all_dirty()
        self.assertEqual(cache.dirty_entries(), [])

        res = yield cache.get(instq('map'))
        self.assertEqual(res.val, {'one':1})
        res = yield cache.get(instq('map2'))
        self.assertEqual(res.val, {'one':1})
        
        
class TestCheckWritable(unittest.TestCase):
    def test_checkwritable(self):
        checkwritable = two.propcache.checkwritable

        checkwritable(None)
        checkwritable(True)
        checkwritable(False)
        checkwritable(1)
        checkwritable(-1)
        checkwritable(1.5)
        checkwritable('x')
        checkwritable("xyzzy")
        checkwritable(b'x')
        checkwritable(ObjectId())
        checkwritable(twcommon.misc.now())
        checkwritable(())
        checkwritable((1, 2, 3))
        checkwritable([])
        checkwritable([None, True, 5, "x", ObjectId()])
        checkwritable({})
        checkwritable({'none':None, 'int':1, 'list':[], 'tuple':()})
        checkwritable({'x$y':'$x'})

        with self.assertRaises(TypeError):
            checkwritable(object())
        with self.assertRaises(TypeError):
            checkwritable(set())
        with self.assertRaises(TypeError):
            checkwritable(datetime.timedelta())
        with self.assertRaises(TypeError):
            checkwritable([[[object()]]])
        with self.assertRaises(TypeError):
            checkwritable([1, 2, 3, self])
        with self.assertRaises(TypeError):
            checkwritable({1:2})
        with self.assertRaises(TypeError):
            checkwritable({'x.y':1})
        with self.assertRaises(TypeError):
            checkwritable({'$x':1})

        loopobj = []
        loopobj.append(loopobj)
        with self.assertRaises(TypeError):
            checkwritable(loopobj)
            
        loopobj = {}
        loopobj['key'] = loopobj
        with self.assertRaises(TypeError):
            checkwritable(loopobj)
            
            
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

        loopobj = []
        loopobj.append(loopobj)
        with self.assertRaises(TypeError):
            deepcopy(loopobj)
            
        loopobj = {}
        loopobj['key'] = loopobj
        with self.assertRaises(TypeError):
            deepcopy(loopobj)

