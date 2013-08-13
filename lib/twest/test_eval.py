"""
To run:   python3 -m tornado.testing twest.test_eval
(The twest, two, twcommon modules must be in your PYTHON_PATH.)

This is just a sketch of how unit tests should go. Ultimately I will
need to connect to mongodb (in a test database), and mock up entries
for the world, instance, player, etc.
"""

import logging
import unittest
import tornado.testing

from bson.objectid import ObjectId

import twcommon.misc
import two.execute
import two.task
from two.execute import EvalPropContext

class MockApplication:
    def __init__(self):
        self.log = logging.getLogger('tworld')


class TestEval(tornado.testing.AsyncTestCase):
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
