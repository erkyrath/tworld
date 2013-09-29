"""
To run:   python3 -m tornado.testing twest.test_funcs
(The twest, two, twcommon modules must be in your PYTHON_PATH.)
"""

import logging
import unittest
import ast

from bson.objectid import ObjectId
import tornado.testing

import motor

import twcommon.misc
import two.execute
import two.symbols
import two.task
from two.execute import EvalPropContext
from twcommon.excepts import SymbolError

import twest.mock
from twest.mock import NotFound

class TestEvalAsync(twest.mock.MockAppTestCase):
    mockappargs = { 'propcache':True, 'globals':True }
    
    @tornado.gen.coroutine
    def resetTables(self):
        # Invent some arbitrary objids for the world and instance.
        self.exuid = ObjectId()
        self.exwid = ObjectId()
        self.exiid = ObjectId()
        self.exlocid = ObjectId()
        self.exscid = ObjectId()
        self.loctx = two.task.LocContext(
            uid=self.exuid, wid=self.exwid, scid=self.exscid,
            iid=self.exiid, locid=self.exlocid)
        
        yield motor.Op(self.app.mongodb.worldprop.remove,
                       {})
        yield motor.Op(self.app.mongodb.worldprop.insert,
                       {'wid':self.exwid, 'locid':self.exlocid,
                        'key':'x', 'val':0})
        yield motor.Op(self.app.mongodb.worldprop.insert,
                       {'wid':self.exwid, 'locid':self.exlocid,
                        'key':'w', 'val':'world'})
        yield motor.Op(self.app.mongodb.worldprop.insert,
                       {'wid':self.exwid, 'locid':None,
                        'key':'r', 'val':11})
        yield motor.Op(self.app.mongodb.worldprop.insert,
                       {'wid':self.exwid, 'locid':self.exlocid,
                        'key':'r', 'val':12})
        
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
                        'key':'ls', 'val':[1,2,3]})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':self.exlocid,
                        'key':'map', 'val':{'one':1, 'two':2, 'three':3}})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':None,
                        'key':'r', 'val':13})
        yield motor.Op(self.app.mongodb.instanceprop.insert,
                       {'iid':self.exiid, 'locid':self.exlocid,
                        'key':'r', 'val':14})
        

    @tornado.testing.gen_test
    def test_global_funcs(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)

        res = yield ctx.eval('len("xyzzy")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 5)
        res = yield ctx.eval('len(ls)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('min(5,3,4)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('min([5,3,4])', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('max(5,3,4)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 5)
        
        res = yield ctx.eval('int(6.5)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 6)
        res = yield ctx.eval('int("17")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 17)
        res = yield ctx.eval('str(6)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, '6')
        res = yield ctx.eval('bool(6)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('list((6,7))', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [6,7])
        res = yield ctx.eval('set((7,6))', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {6,7})
        res = yield ctx.eval('dict([(6,7)])', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {6:7})
        
        res = yield ctx.eval('[text("x")]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [{'type': 'text', 'text': 'x'}])
        res = yield ctx.eval('[code("x")]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [{'type': 'code', 'text': 'x'}])
        res = yield ctx.eval('[gentext.gentext("x")]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [{'type': 'gentext', 'text': 'x'}])
        res = yield ctx.eval('ObjectId("5245c6b26b3d30521a6996ec")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ObjectId("5245c6b26b3d30521a6996ec"))

        res = yield ctx.eval('isinstance(True, bool)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance(True, int)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)  # a Python quirk
        res = yield ctx.eval('isinstance(5, (str, int))', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance([], (str, int))', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('isinstance(32, int)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance("X", str)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance(ObjectId("5245c6b26b3d30521a6996ec"), ObjectId)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance({}, dict)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance({1}, set)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance([1], list)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance({"type":"text", "text":"x"}, text)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance({"type":"code", "text":"x"}, code)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance({"type":"gentext", "text":"x"}, gentext.gentext)', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('isinstance({"type":"foo", "text":"x"}, text)', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('isinstance({"type":"foo", "text":"x"}, code)', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('isinstance({"type":"foo", "text":"x"}, gentext.gentext)', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        
        res = yield ctx.eval('realm', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, two.execute.RealmProxy))
        res = yield ctx.eval('locations', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, two.execute.WorldLocationsProxy))
        res = yield ctx.eval('player', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, two.execute.PlayerProxy))
        self.assertEqual(res, self.exuid)

        res = yield ctx.eval('random.choice(["X","Y","Z"])', evaltype=EVALTYPE_CODE)
        self.assertIn(res, ["X","Y","Z"])
        res = yield ctx.eval('random.randint(4, 6)', evaltype=EVALTYPE_CODE)
        self.assertIn(res, [4,5,6])
        res = yield ctx.eval('random.randrange(3)', evaltype=EVALTYPE_CODE)
        self.assertIn(res, [0,1,2])
        res = yield ctx.eval('random.randrange(4, 6)', evaltype=EVALTYPE_CODE)
        self.assertIn(res, [4,5])
        
from two.evalctx import LEVEL_EXECUTE, LEVEL_DISPSPECIAL, LEVEL_DISPLAY, LEVEL_MESSAGE, LEVEL_FLAT, LEVEL_RAW
from two.evalctx import EVALTYPE_SYMBOL, EVALTYPE_RAW, EVALTYPE_CODE, EVALTYPE_TEXT
