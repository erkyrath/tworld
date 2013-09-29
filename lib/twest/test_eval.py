"""
To run:   python3 -m tornado.testing twest.test_eval
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

class TestEval(unittest.TestCase):
    def test_optimize_accum(self):
        optimize_accum = two.evalctx.optimize_accum
        
        ls = []
        optimize_accum(ls)
        self.assertEqual(ls, [])
        ls = ['foo']
        optimize_accum(ls)
        self.assertEqual(ls, ['foo'])
        ls = ['foo', 'bar']
        optimize_accum(ls)
        self.assertEqual(ls, ['foobar'])
        ls = ['foo', ' ', 'baz']
        optimize_accum(ls)
        self.assertEqual(ls, ['foo baz'])
        ls = [()]
        optimize_accum(ls)
        self.assertEqual(ls, [()])
        ls = [(), ()]
        optimize_accum(ls)
        self.assertEqual(ls, [(), ()])
        ls = ['x', (), 'y', (), 'z']
        optimize_accum(ls)
        self.assertEqual(ls, ['x', (), 'y', (), 'z'])
        ls = ['x', 'X', (), 'y', 'Y', (), 'z', 'Z']
        optimize_accum(ls)
        self.assertEqual(ls, ['xX', (), 'yY', (), 'zZ'])
        ls = [(), 'foo', '-', 'bar', ()]
        optimize_accum(ls)
        self.assertEqual(ls, [(), 'foo-bar', ()])
        ls = ['x', 'X', (1,), (2,), 'z', 'Z']
        optimize_accum(ls)
        self.assertEqual(ls, ['xX', (1,), (2,), 'zZ'])
        ls = ['x', 'X', 'x', (), 'z', 'Z', 'z']
        optimize_accum(ls)
        self.assertEqual(ls, ['xXx', (), 'zZz'])
        
    def mockResolveDefaults(self, ls):
        res = []
        for val in ls:
            if type(val) is ast.Num:
                res.append(val.n)
            elif type(val) is ast.Str:
                res.append(val.s)
            elif val is None:
                res.append(None)
            else:
                raise Exception('Unknown default arg type')
        return res
            
    def assertSpecIs(self, spec, args=[], kwonlyargs=[], vararg=None, kwarg=None, defaults=[], kw_defaults=[]):
        specargs = [ arg.arg for arg in spec.args ]
        self.assertEqual(specargs, args)
        self.assertEqual(spec.vararg, vararg)
        speckwonlyargs = [ arg.arg for arg in spec.kwonlyargs ]
        self.assertEqual(speckwonlyargs, kwonlyargs)
        self.assertEqual(spec.kwarg, kwarg)
        self.assertEqual(self.mockResolveDefaults(spec.defaults), defaults)
        self.assertEqual(self.mockResolveDefaults(spec.kw_defaults), kw_defaults)
        
    def test_argument_spec(self):
        parse_argument_spec = two.evalctx.parse_argument_spec
        
        spec = parse_argument_spec('')
        self.assertSpecIs(spec, [])
        spec = parse_argument_spec('x')
        self.assertSpecIs(spec, ['x'])
        spec = parse_argument_spec('x=1')
        self.assertSpecIs(spec, ['x'], defaults=[1])
        spec = parse_argument_spec('x, y=1, z="foo"')
        self.assertSpecIs(spec, ['x', 'y', 'z'], defaults=[1, 'foo'])
        spec = parse_argument_spec('*ls')
        self.assertSpecIs(spec, [], vararg='ls')
        spec = parse_argument_spec('**map')
        self.assertSpecIs(spec, [], kwarg='map')
        spec = parse_argument_spec('xyz, *ls, **map')
        self.assertSpecIs(spec, ['xyz'], vararg='ls', kwarg='map')
        spec = parse_argument_spec('xyz=0.5, *ls, **map')
        self.assertSpecIs(spec, ['xyz'], defaults=[0.5], vararg='ls', kwarg='map')
        spec = parse_argument_spec('*ls, x')
        self.assertSpecIs(spec, kwonlyargs=['x'], vararg='ls', kw_defaults=[None])
        spec = parse_argument_spec('*ls, x=5')
        self.assertSpecIs(spec, kwonlyargs=['x'], vararg='ls', kw_defaults=[5])
        spec = parse_argument_spec('x, y=1, *ls, zz=55')
        self.assertSpecIs(spec, ['x', 'y'], kwonlyargs=['zz'], vararg='ls', defaults=[1], kw_defaults=[55])
        spec = parse_argument_spec('*ls, x="bar", **map')
        self.assertSpecIs(spec, kwonlyargs=['x'], vararg='ls', kwarg='map', kw_defaults=['bar'])

        self.assertRaises(SyntaxError, parse_argument_spec, '-')
        self.assertRaises(SyntaxError, parse_argument_spec, '1')
        self.assertRaises(SyntaxError, parse_argument_spec, 'x, x')
        self.assertRaises(SyntaxError, parse_argument_spec, 'x, *x')
        self.assertRaises(SyntaxError, parse_argument_spec, 'x, **x')
        self.assertRaises(SyntaxError, parse_argument_spec, '*x, **x')
        self.assertRaises(SyntaxError, parse_argument_spec, '*ls1, *ls2')
        self.assertRaises(SyntaxError, parse_argument_spec, '**map, x=1')
        self.assertRaises(SyntaxError, parse_argument_spec, ':None;lambda')

    def assertSpecResolves(self, specstr, *args, **kwargs):
        spec = two.evalctx.parse_argument_spec(specstr)
        if spec.defaults:
            spec.defaults = self.mockResolveDefaults(spec.defaults)
        if spec.kw_defaults:
            spec.kw_defaults = self.mockResolveDefaults(spec.kw_defaults)
        res = two.evalctx.resolve_argument_spec(spec, args, kwargs)
        want = 'lambda %s : locals()' % (specstr,)
        want = eval(want)(*args, **kwargs)
        self.assertEqual(res, want)
        
    def assertSpecResolvesRaise(self, specstr, *args, **kwargs):
        spec = two.evalctx.parse_argument_spec(specstr)
        self.assertRaises(TypeError, two.evalctx.resolve_argument_spec, spec, args, kwargs)
        
    def test_argument_resolve_spec(self):
        self.assertSpecResolves('')
        self.assertSpecResolves('x', 3)
        self.assertSpecResolves('x, y', 3, 5)
        self.assertSpecResolvesRaise('x')
        self.assertSpecResolvesRaise('', 3)
        self.assertSpecResolvesRaise('x', 3, 4)
        self.assertSpecResolvesRaise('x, y', 3, 4, 5)
        self.assertSpecResolves('x=5')
        self.assertSpecResolves('x=3', 4)
        self.assertSpecResolves('x=3, y=7')
        self.assertSpecResolves('x=3, y=7', 4)
        self.assertSpecResolves('x=3, y=7', 4, 5)
        self.assertSpecResolvesRaise('x=3', 9, 9)
        self.assertSpecResolves('*ls')
        self.assertSpecResolves('*ls', 1, 2, 3)
        self.assertSpecResolves('x, *ls', 4)
        self.assertSpecResolves('x, *ls', 4, 5)
        self.assertSpecResolves('x=6, *ls')
        self.assertSpecResolves('x=6, *ls', 7)
        self.assertSpecResolves('x=6, *ls', 7, 8)
        self.assertSpecResolves('x', x=3)
        self.assertSpecResolves('x, y', x=5, y=6)
        self.assertSpecResolves('x, y=6', x=5)
        self.assertSpecResolvesRaise('x', 4, x=3)
        self.assertSpecResolvesRaise('x=0', 4, x=3)
        self.assertSpecResolvesRaise('', x=3)
        self.assertSpecResolvesRaise('x=0', x=3, y=4)
        self.assertSpecResolves('**map')
        self.assertSpecResolves('**map', x=1, y=2)
        self.assertSpecResolvesRaise('**map', 1, x=1, y=2)
        self.assertSpecResolves('*ls, **map')
        self.assertSpecResolves('*ls, **map', 8, 9, x=1, y=2)
        self.assertSpecResolves('x, *ls, **map', 8, 9, w=1, q=2)
        self.assertSpecResolves('*ls, x=0')
        self.assertSpecResolves('*ls, x=0', x=4)
        self.assertSpecResolvesRaise('*ls, x', 3)
        self.assertSpecResolvesRaise('*ls, x=0', x=4, z=5)
        
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
    def test_simple_literals(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)
        
        res = yield ctx.eval('3', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('-3.5', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, -3.5)
        res = yield ctx.eval('None', evaltype=EVALTYPE_CODE)
        self.assertTrue(res is None)
        res = yield ctx.eval('True', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"foo"', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'foo')
        res = yield ctx.eval('\'bar\'', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'bar')
        res = yield ctx.eval('"X\xA0\u1234"', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'X\xA0\u1234')
        res = yield ctx.eval('[]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [])
        res = yield ctx.eval('[1, None, "bar"]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1, None, 'bar'])
        res = yield ctx.eval('()', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, ())
        res = yield ctx.eval('{}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {})
        res = yield ctx.eval('{"x":"yy", "one":1}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {'x':'yy', 'one':1})
        res = yield ctx.eval('{1, 2, 3}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, set([1, 2, 3]))
        
    @tornado.testing.gen_test
    def test_simple_props(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)

        res = yield ctx.eval('x', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 1)
        res = yield ctx.eval('r', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 14)
        res = yield ctx.eval('ls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3])
        res = yield ctx.eval('map', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {'one':1, 'two':2, 'three':3})
        
        res = yield ctx.eval('_', evaltype=EVALTYPE_CODE)
        self.assertTrue(res is self.app.global_symbol_table)
        res = yield ctx.eval('player', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, two.execute.PlayerProxy))
        res = yield ctx.eval('random', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, two.symbols.ScriptNamespace))
        res = yield ctx.eval('random.choice', evaltype=EVALTYPE_CODE)
        self.assertTrue(isinstance(res, two.symbols.ScriptFunc))

        with self.assertRaises(SymbolError):
            yield ctx.eval('xyzzy', evaltype=EVALTYPE_CODE)
        with self.assertRaises(KeyError):
            yield ctx.eval('random.xyzzy', evaltype=EVALTYPE_CODE)

    @tornado.testing.gen_test
    def test_simple_ops(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)

        res = yield ctx.eval('1+5', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 6)
        res = yield ctx.eval('x+5', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 6)
        res = yield ctx.eval('x+y', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        
        res = yield ctx.eval('1-5', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, -4)
        res = yield ctx.eval('2*7', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 14)
        res = yield ctx.eval('7/2', evaltype=EVALTYPE_CODE)
        self.assertAlmostEqual(res, 3.5)
        res = yield ctx.eval('7//2', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('7**2', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 49)
        res = yield ctx.eval('7%3', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 1)
        res = yield ctx.eval('5&6', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 4)
        res = yield ctx.eval('5|6', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 7)
        res = yield ctx.eval('5^6', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('5<<1', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 10)
        res = yield ctx.eval('5>>1', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 2)
        
        res = yield ctx.eval('"xy"+"ZW"', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'xyZW')
        res = yield ctx.eval('"x"*3', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'xxx')
        res = yield ctx.eval('[1,2]+[3,4]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,3,4])
        res = yield ctx.eval('"%s:%s"%(1,"x")', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, '1:x')

        res = yield ctx.eval('True and False and True', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, False)
        res = yield ctx.eval('False or True or False', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('True and False and nosuch', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, False)
        res = yield ctx.eval('False or True or nosuch', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)

        with self.assertRaises(SymbolError):
            res = yield ctx.eval('True and nosuch', evaltype=EVALTYPE_CODE)
        with self.assertRaises(SymbolError):
            res = yield ctx.eval('False or nosuch', evaltype=EVALTYPE_CODE)

        res = yield ctx.eval('3 if True else 4', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('3 if False else 4', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 4)
        res = yield ctx.eval('3 if True else nosuch', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('nosuch if False else 4', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 4)

        res = yield ctx.eval('3 < 4', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('3 > 4', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('3 <= 3', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('3 >= 3', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('5 <= 3', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('5 >= 3', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        
        res = yield ctx.eval('True is True', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('True is False', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('True is not False', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('[] is []', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('[] == []', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('{2,1} == {1,2}', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('1 != 2', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('1 in [1,2,3]', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('5 in {1,2,3}', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('1 in {1:11}', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        res = yield ctx.eval('"z" not in "xyzzy"', evaltype=EVALTYPE_CODE)
        self.assertFalse(res)
        res = yield ctx.eval('5 not in [1,2,3]', evaltype=EVALTYPE_CODE)
        self.assertTrue(res)
        
    @tornado.testing.gen_test
    def test_comprehensions(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)
        
        res = yield ctx.eval('[_x+1 for _x in ls]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [2,3,4])
        res = yield ctx.eval('[_x+1 for _x in [0,1,2,3] if _x != 2]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,2,4])
        res = yield ctx.eval('[_x+_y for _x in [0,1,2,3] for _y in [5,6,7]]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [5, 6, 7, 6, 7, 8, 7, 8, 9, 8, 9, 10])
        res = yield ctx.eval('[_x+_y for _x in [0,1,2,3] if _x%2 for _y in [5,6,7]]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [6, 7, 8, 8, 9, 10])
        res = yield ctx.eval('[_x+_y for _x in [0,1,2,3] for _y in [5,6,7] if _x%2]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [6, 7, 8, 8, 9, 10])
        res = yield ctx.eval('[_x+_y for _x in [0,1,2,3] if _x%2 for _y in [5,6,7] if _y==6]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [7,9])
        res = yield ctx.eval('[(_y,_x) for _x,_y in ["XY", (7,8), (9,10)]]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [('Y','X'), (8,7), (10,9)])

        task.resetticks()

        res = yield ctx.eval('{_x for _x in ls}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1,2,3})
        res = yield ctx.eval('{_x|1 for _x in ls}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1,3})
        res = yield ctx.eval('{_x for _x in [1,2,3,4,1] if _x%2}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1,3})
        res = yield ctx.eval('{_x+_y for _x in [0,1,2,3] for _y in [5,6,7]}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {5, 6, 7, 8, 9, 10})
        
        res = yield ctx.eval('{_x:11 for _x in ls}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {1:11, 2:11, 3:11})
        res = yield ctx.eval('{_x:_x+1 for _x in ls if _x==3}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {3:4})
        res = yield ctx.eval('{(_x,_y):(_x+_y) for _x in [1,2] for _y in [5,6,7]}', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {(2,7): 9, (1,5): 6, (2,6): 8, (1,6): 7, (1,7): 8, (2,5): 7})
        
    @tornado.testing.gen_test
    def test_assignments(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        task.set_writable()
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)
        
        res = yield ctx.eval('z = 7\nz', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 7)
        res = yield ctx.eval('x1,x2 = 1,2\n[x2,x1]', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [2,1])
        res = yield ctx.eval('ls[1] = 7\nls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,7,3])
        res = yield ctx.eval('ls[0:2] = [6,5,4]\nls', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [6,5,4,3])
        res = yield ctx.eval('map["one"] = "ONE"\nmap', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, {'one':'ONE', 'two':2, 'three':3})
        res = yield ctx.eval('z1=z2=_z3=9\nz1,z2,_z3', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, (9,9,9))
        
    @tornado.testing.gen_test
    def test_statements(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        ctx = EvalPropContext(task, loctx=self.loctx, level=LEVEL_EXECUTE)
        
        res = yield ctx.eval('_tmp = 7\n_tmp', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 7)
        res = yield ctx.eval('_tmp = [1,2,3]\n_tmp[1] = 7\n_tmp', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,7,3])

        with self.assertRaises(NameError):
            res = yield ctx.eval('_tmp = 7\ndel _tmp\n_tmp', evaltype=EVALTYPE_CODE)
        res = yield ctx.eval('_tmp = [1,2,3]\ndel _tmp[1]\n_tmp', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, [1,3])

        res = yield ctx.eval('pass', evaltype=EVALTYPE_CODE)
        self.assertIsNone(res)
        
        res = yield ctx.eval('return 17', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 17)
        res = yield ctx.eval('return 17\nreturn 18', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 17)
        
        res = yield ctx.eval('_x = 0\nwhile True:\n _x = _x+1\n if _x >= 3:\n  return _x', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('_x = 0\nwhile True:\n _x = _x+1\n if _x >= 3:\n  break\nreturn _x', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        
        res = yield ctx.eval('if True:\n return 3\nelse:\n return 4', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('if False:\n return 3\nelse:\n return 4', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 4)

        res = yield ctx.eval('if True:\n return 3\nelse:\n return nosuch', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('if False:\n return nosuch\nelse:\n return 4', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 4)

        res = yield ctx.eval('_sum = 0\nfor _x in ls:\n _sum = _sum + _x\n_sum', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 6)
        res = yield ctx.eval('for _x in ls:\n if _x == 2:\n  return _x', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 2)
        res = yield ctx.eval('_sum = 0\nfor _x in ls:\n if _x == 2:\n  continue\n _sum = _sum + _x\n_sum', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 4)
        
from two.evalctx import LEVEL_EXECUTE, LEVEL_DISPSPECIAL, LEVEL_DISPLAY, LEVEL_MESSAGE, LEVEL_FLAT, LEVEL_RAW
from two.evalctx import EVALTYPE_SYMBOL, EVALTYPE_RAW, EVALTYPE_CODE, EVALTYPE_TEXT
