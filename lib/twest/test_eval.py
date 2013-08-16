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

class MockApplication:
    def __init__(self):
        self.log = logging.getLogger('tworld')

class TestEval(unittest.TestCase):
    def assertSpecIs(self, spec, args=[], kwonlyargs=[], vararg=None, kwarg=None, defaults=[], kw_defaults=[]):
        specargs = [ arg.arg for arg in spec.args ]
        self.assertEqual(specargs, args)
        self.assertEqual(spec.vararg, vararg)
        speckwonlyargs = [ arg.arg for arg in spec.kwonlyargs ]
        self.assertEqual(speckwonlyargs, kwonlyargs)
        self.assertEqual(spec.kwarg, kwarg)
        for (specdef, defv) in zip(spec.defaults, defaults):
            if type(specdef) is ast.Num:
                self.assertEqual(specdef.n, defv)
            elif type(specdef) is ast.Str:
                self.assertEqual(specdef.s, defv)
            else:
                raise Exception('Unknown default arg type')
        for (specdef, defv) in zip(spec.kw_defaults, kw_defaults):
            if type(specdef) is ast.Num:
                self.assertEqual(specdef.n, defv)
            elif type(specdef) is ast.Str:
                self.assertEqual(specdef.s, defv)
            else:
                raise Exception('Unknown default arg type')
        
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
        spec = parse_argument_spec('*ls, x=5')
        self.assertSpecIs(spec, kwonlyargs=['x'], vararg='ls', kw_defaults=[5])
        spec = parse_argument_spec('x, y=1, *ls, zz=55')
        self.assertSpecIs(spec, ['x', 'y'], kwonlyargs=['zz'], vararg='ls', defaults=[1], kw_defaults=[55])
        spec = parse_argument_spec('*ls, x="bar", **map')
        self.assertSpecIs(spec, kwonlyargs=['x'], vararg='ls', kwarg='map', kw_defaults=['bar'])

class TestEvalAsync(tornado.testing.AsyncTestCase):
    @tornado.testing.gen_test
    def test_simple_literals(self):
        app = MockApplication()
        task = two.task.Task(app, None, 1, 2, twcommon.misc.now())
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
