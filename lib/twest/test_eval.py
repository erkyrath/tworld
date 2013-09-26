"""
To run:   python3 -m tornado.testing twest.test_eval
(The twest, two, twcommon modules must be in your PYTHON_PATH.)

This is just a sketch of how unit tests should go. Ultimately I will
need to connect to mongodb (in a test database), and mock up entries
for the world, instance, player, etc.
"""

import logging
import unittest
import ast

from bson.objectid import ObjectId
import tornado.testing

import twcommon.misc
import two.execute
import two.task
from two.execute import EvalPropContext

import twest.mock
from twest.mock import NotFound

class MockApplication:
    def __init__(self):
        self.log = logging.getLogger('tworld')

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
    
    @tornado.testing.gen_test
    def test_simple_literals(self):
        yield self.resetTables()
        
        task = two.task.Task(self.app, None, 1, 2, twcommon.misc.now())
        loctx = two.task.LocContext(uid=ObjectId())
        ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)
        
        res = yield ctx.eval('3', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 3)
        res = yield ctx.eval('-3.5', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, -3.5)
        res = yield ctx.eval('True', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, True)
        res = yield ctx.eval('"foo"', evaltype=EVALTYPE_CODE)
        self.assertEqual(res, 'foo')
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
        

from two.evalctx import LEVEL_EXECUTE, LEVEL_DISPSPECIAL, LEVEL_DISPLAY, LEVEL_MESSAGE, LEVEL_FLAT, LEVEL_RAW
from two.evalctx import EVALTYPE_SYMBOL, EVALTYPE_RAW, EVALTYPE_CODE, EVALTYPE_TEXT
