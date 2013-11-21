"""
To run:   python3 -m tornado.testing twest.test_funcs
(The twest, two, twcommon modules must be in your PYTHON_PATH.)
"""

import datetime
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

    @tornado.testing.gen_test
    def test_type_methods_list(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)

        res = yield ctx.eval('_ls=[1,2,3]\n_ls.append(4);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3,4])
        res = yield ctx.eval('_ls=[1,2,3]\n_ls.clear();_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [])
        res = yield ctx.eval('_ls=[1,2,3]\n_ls2=_ls.copy();_ls[0]=0;_ls2', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3])
        res = yield ctx.eval('[1,2,3,2].count(2)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 2)
        res = yield ctx.eval('_ls=[1,2,3]\n_ls.extend([4,5]);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3,4,5])
        res = yield ctx.eval('[5,4,3].index(4)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 1)
        res = yield ctx.eval('_ls=[1,2,3]\n_ls.insert(0,4);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [4,1,2,3])
        res = yield ctx.eval('_ls=[1,2,3]\n_ls.pop();_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2])
        res = yield ctx.eval('_ls=[1,2,3]\n_ls.remove(2);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,3])
        res = yield ctx.eval('_ls=[3,2,1]\n_ls.reverse();_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3])
        
        task.resetticks()

        res = yield ctx.eval('_ls=[3,1,2]\n_ls.sort();_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3])
        res = yield ctx.eval('_ls=[3,1,2]\nlist.sort(_ls);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3])
        res = yield ctx.eval('_ls=[3,1,2]\n_ls.sort(reverse=True);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [3,2,1])
        res = yield ctx.eval('_ls=[3,1,2]\nlist.sort(_ls,reverse=True);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [3,2,1])
        res = yield ctx.eval('_ls=[-1,2,-3,4]\n_ls.sort(key=str);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [-1,-3,2,4])
        res = yield ctx.eval('_ls=[-1,2,-3,4]\nlist.sort(_ls,key=str);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [-1,-3,2,4])
        res = yield ctx.eval('_ls=[-1,2,-3,4]\n_ls.sort(key=str,reverse=True);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [4,2,-3,-1])
        res = yield ctx.eval('_ls=[-1,2,-3,4]\nlist.sort(_ls,key=str,reverse=True);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [4,2,-3,-1])
        res = yield ctx.eval('_ls=[-1,-3,2,4]\n_func=code("x*x",args="x")\n_ls.sort(key=_func);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [-1,2,-3,4])
        res = yield ctx.eval('_ls=[-1,-3,2,4]\n_func=code("x*x",args="x")\nlist.sort(_ls,key=_func);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [-1,2,-3,4])
        res = yield ctx.eval('_ls=[-1,-3,2,4]\n_func=code("x*x",args="x")\n_ls.sort(key=_func,reverse=True);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [4,-3,2,-1])
        res = yield ctx.eval('_ls=[-1,-3,2,4]\n_func=code("x*x",args="x")\nlist.sort(_ls,key=_func,reverse=True);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [4,-3,2,-1])
        
        res = yield ctx.eval('_ls=["d","C","b","A"]\n_ls.sort(key=str.upper);_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ['A','b','C','d'])
        res = yield ctx.eval('_ls=["d","p","q","x","y"]\n_ls.sort(key=functools.partial(str.index,"xyzpdq"));_ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ['x','y','p','d','q'])
        
        with self.assertRaises(TypeError):
            res = yield ctx.eval('_ls=[1]\n_ls.sort(key=foo);_ls', locals={'foo':open}, evaltype=EVALTYPE_CODE)
        with self.assertRaises(TypeError):
            res = yield ctx.eval('_ls=[1]\n_ls.sort(key=foo);_ls', locals={'foo':123}, evaltype=EVALTYPE_CODE)
        
    @tornado.testing.gen_test
    def test_type_methods_dict(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)

        res = yield ctx.eval('_map={1:11,2:22}\n_map.clear();_map', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {})
        res = yield ctx.eval('_map={1:11,2:22}\n_map2=_map.copy();_map[3]=0;_map2', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1:11,2:22})
        res = yield ctx.eval('dict.fromkeys([1,2,3],4)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1:4,2:4,3:4})
        res = yield ctx.eval('{1:11,2:22,3:33}.get(2)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 22)
        res = yield ctx.eval('list({1:11}.items())', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [(1, 11)])
        res = yield ctx.eval('list({1:11}.keys())', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1])
        res = yield ctx.eval('{1:11,2:22,3:33}.pop(2)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 22)
        res = yield ctx.eval('_map={1:11,2:22,3:33};_map.pop(2);_map', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1:11,3:33})
        res = yield ctx.eval('{1:11}.popitem()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, (1,11))
        res = yield ctx.eval('_map={1:11,2:22};_map.setdefault(3,33)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 33)
        res = yield ctx.eval('_map={1:11,2:22};_map.update({3:33});_map', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1:11,2:22,3:33})
        res = yield ctx.eval('list({1:11}.values())', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [11])
        
    @tornado.testing.gen_test
    def test_type_methods_string(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)
        
        res = yield ctx.eval('"foo bar".capitalize()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'Foo bar')
        res = yield ctx.eval('"Foo BAR".casefold()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'foo bar')
        res = yield ctx.eval('"foo bar".center(9)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ' foo bar ')
        res = yield ctx.eval('"foo bar".count("o")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 2)
        res = yield ctx.eval('"foo bar".endswith("ar")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"foo bar".find("a")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 5)
        res = yield ctx.eval('"foo bar".index("a")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 5)
        res = yield ctx.eval('"foo bar".isalnum()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, False)
        res = yield ctx.eval('"foobar".isalpha()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"1235".isdecimal()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"1235x".isdigit()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, False)
        res = yield ctx.eval('"Foo_bar".isidentifier()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"foo bar".islower()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"1235".isnumeric()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"foo bar".isprintable()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"foo bar".isspace()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, False)
        res = yield ctx.eval('"Foo Bar".istitle()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"Foo Bar".isupper()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, False)
        res = yield ctx.eval('",".join(["x","y","zz"])', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'x,y,zz')
        res = yield ctx.eval('"foo bar".ljust(9)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'foo bar  ')
        res = yield ctx.eval('"Foo BAR".lower()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'foo bar')
        res = yield ctx.eval('" foo ".lstrip()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'foo ')
        res = yield ctx.eval('"x,y,z".partition(",")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ('x', ',', 'y,z') )
        res = yield ctx.eval('"foo bar".replace("o","z")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'fzz bar')
        res = yield ctx.eval('"foo bar".rfind("o")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 2)
        res = yield ctx.eval('"foo bar".rindex("o")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 2)
        res = yield ctx.eval('"foo bar".rjust(9)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, '  foo bar')
        res = yield ctx.eval('"x,y,z".rpartition(",")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ('x,y', ',', 'z') )
        res = yield ctx.eval('"x,y,z".rsplit(",")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ['x', 'y', 'z'] )
        res = yield ctx.eval('" foo ".rstrip()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ' foo')
        res = yield ctx.eval('"x,y,z".split(",")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ['x', 'y', 'z'] )
        res = yield ctx.eval('"x\\ny\\nz".splitlines()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ['x', 'y', 'z'] )
        res = yield ctx.eval('"foo bar".startswith("fo")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('" foo ".strip()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'foo')
        res = yield ctx.eval('"Foo BAR".swapcase()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'fOO bar')
        res = yield ctx.eval('"foo bar".title()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'Foo Bar')
        res = yield ctx.eval('"foo bar".upper()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'FOO BAR')
        res = yield ctx.eval('"foo bar".zfill(9)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, '00foo bar')

        # Miscellaneous cases
        res = yield ctx.eval('str.upper("foo bar")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'FOO BAR')
        
        with self.assertRaises(twcommon.excepts.ExecSandboxException):
            res = yield ctx.eval('"x".__class__', evaltype=EVALTYPE_CODE)
        with self.assertRaises(twcommon.excepts.ExecSandboxException):
            res = yield ctx.eval('str.__class__', evaltype=EVALTYPE_CODE)
        with self.assertRaises(twcommon.excepts.ExecSandboxException):
            res = yield ctx.eval('"x".nosuchattr', evaltype=EVALTYPE_CODE)
        with self.assertRaises(twcommon.excepts.ExecSandboxException):
            res = yield ctx.eval('str.nosuchattr', evaltype=EVALTYPE_CODE)
        with self.assertRaises(twcommon.excepts.ExecSandboxException):
            res = yield ctx.eval('"x".format', evaltype=EVALTYPE_CODE)
        with self.assertRaises(twcommon.excepts.ExecSandboxException):
            res = yield ctx.eval('str.format', evaltype=EVALTYPE_CODE)

    @tornado.testing.gen_test
    def test_datetime(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)

        res = yield ctx.eval('datetime.now', evaltype=EVALTYPE_CODE)
        self.assertTrue(res is task.starttime)
        res = yield ctx.eval('datetime.datetime(2013,5,1)', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, datetime.datetime))
        self.assertEqual(res, datetime.datetime(year=2013, month=5, day=1, tzinfo=datetime.timezone.utc))
        res = yield ctx.eval('datetime.datetime(year=2013, month=5, day=2, hour=3, minute=4, second=5, microsecond=500000)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, datetime.datetime(year=2013, month=5, day=2, hour=3, minute=4, second=5, microsecond=500000, tzinfo=datetime.timezone.utc))
        
        res = yield ctx.eval('datetime.now.year', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.year)
        res = yield ctx.eval('datetime.now.month', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.month)
        res = yield ctx.eval('datetime.now.day', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.day)
        res = yield ctx.eval('datetime.now.hour', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.hour)
        res = yield ctx.eval('datetime.now.minute', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.minute)
        res = yield ctx.eval('datetime.now.second', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.second)
        res = yield ctx.eval('datetime.now.microsecond', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.microsecond)
        res = yield ctx.eval('datetime.now.min', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.min)
        res = yield ctx.eval('datetime.now.max', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.max)
        res = yield ctx.eval('datetime.now.resolution', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, task.starttime.resolution)

        res = yield ctx.eval('datetime.timedelta()', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, datetime.timedelta))
        self.assertEqual(res, datetime.timedelta())
        res = yield ctx.eval('datetime.timedelta(days=1, seconds=2, milliseconds=3)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, datetime.timedelta(days=1, seconds=2, milliseconds=3))
        res = yield ctx.eval('datetime.timedelta(hours=1, minutes=2, weeks=3)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, datetime.timedelta(hours=1, minutes=2, weeks=3))
        res = yield ctx.eval('datetime.timedelta(hours=1, minutes=2, weeks=3).total_seconds()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 1818120)
        res = yield ctx.eval('datetime.timedelta().min', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, datetime.timedelta().min)
        res = yield ctx.eval('datetime.timedelta().max', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, datetime.timedelta().max)
        res = yield ctx.eval('datetime.timedelta().resolution', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, datetime.timedelta().resolution)
        
    @tornado.testing.gen_test
    def test_partial(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        task.set_writable()
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)

        res = yield ctx.eval('functools.partial(int)()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 0)
        res = yield ctx.eval('functools.partial(int, "10")()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 10)
        res = yield ctx.eval('functools.partial(int)("11")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 11)
        res = yield ctx.eval('functools.partial(int, "10", 4)()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 4)
        res = yield ctx.eval('functools.partial(int)("11", 4)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 5)
        res = yield ctx.eval('functools.partial(int, "12")(4)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 6)
        res = yield ctx.eval('functools.partial(int, "10", base=5)()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 5)
        res = yield ctx.eval('functools.partial(int)("11", base=5)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 6)
        res = yield ctx.eval('functools.partial(int, "12")(base=5)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 7)
        
        res = yield ctx.eval('propint = code("int(x, base=base)", args="x, base=None")', evaltype=EVALTYPE_CODE)
        res = yield ctx.eval('functools.partial(propint, "10", base=6)()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 6)
        res = yield ctx.eval('functools.partial(propint)("11", base=6)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 7)
        res = yield ctx.eval('functools.partial(propint, "12")(base=6)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 8)

        res = yield ctx.eval('functools.partial(ObjectId, "528d3862689e9d17a7a96473")()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ObjectId('528d3862689e9d17a7a96473'))
        res = yield ctx.eval('functools.partial(ObjectId)("528d3862689e9d17a7a96474")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ObjectId('528d3862689e9d17a7a96474'))
        
        res = yield ctx.eval('functools.partial(location)()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, self.exlocid)
        res = yield ctx.eval('functools.partial(location)(None)', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, self.exlocid)

        with self.assertRaises(TypeError):
            res = yield ctx.eval('functools.partial(foo)()', locals={'foo':open}, evaltype=EVALTYPE_CODE)

        
from two.evalctx import LEVEL_EXECUTE, LEVEL_DISPSPECIAL, LEVEL_DISPLAY, LEVEL_MESSAGE, LEVEL_FLAT, LEVEL_RAW
from two.evalctx import EVALTYPE_SYMBOL, EVALTYPE_RAW, EVALTYPE_CODE, EVALTYPE_TEXT
