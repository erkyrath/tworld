"""
To run:   python3 -m tornado.testing twest.test_interp
(The twest, twcommon modules must be in your PYTHON_PATH.)
"""

import unittest

from twcommon.interp import parse
from twcommon.interp import Interpolate, Link, EndLink, ParaBreak, PlayerRef, Style, EndStyle

class TestInterpModule(unittest.TestCase):

    def test_parse(self):
        ls = parse('hello')
        self.assertEqual(ls, ['hello'])
        
        ls = parse('[[hello]]')
        self.assertEqual(ls, [Interpolate('hello')])

        ls = parse('One [[two]] three[[four]][[five]].')
        self.assertEqual(ls, ['One ', Interpolate('two'), ' three', Interpolate('four'), Interpolate('five'), '.'])
        
        ls = parse('[[ x = [] ]]')
        self.assertEqual(ls, [Interpolate('x = []')])

        ls = parse('[hello]')
        self.assertEqual(ls, [Link('hello'), 'hello', EndLink()])

        ls = parse('[Go to sleep.]')
        self.assertEqual(ls, [Link('go_to_sleep'), 'Go to sleep.', EndLink()])

        ls = parse('One [two] three[FOUR|half][FIVE].')
        self.assertEqual(ls, ['One ', Link('two'), 'two', EndLink(), ' three', Link('half'), 'FOUR', EndLink(), Link('five'), 'FIVE', EndLink(), '.'])
        
        ls = parse('[One [[two]] three[[four]][[five]].| foobar ]')
        self.assertEqual(ls, [Link('foobar'), 'One ', Interpolate('two'), ' three', Interpolate('four'), Interpolate('five'), '.', EndLink()])

        ls = parse('[hello||world]')
        self.assertEqual(ls, [Link('world'), 'hello', ' world', EndLink()])

        ls = parse('[Bottle of || red wine].')
        self.assertEqual(ls, [Link('red_wine'), 'Bottle of ', '  red wine', EndLink(), '.'])

        ls = parse('One.\nTwo.')
        self.assertEqual(ls, ['One.\nTwo.'])

        ls = parse('One.\n\nTwo.[[$para]]Three.')
        self.assertEqual(ls, ['One.', ParaBreak(), 'Two.', ParaBreak(), 'Three.'])

        ls = parse('\nOne. \n \n Two.\n\n\nThree. \n\t\n  ')
        self.assertEqual(ls, ['\nOne.', ParaBreak(), 'Two.', ParaBreak(), 'Three.', ParaBreak()])

        ls = parse('[||Link] to [this||and\n\nthat].')
        self.assertEqual(ls, [Link('link'), ' Link', EndLink(), ' to ', Link('and_that'), 'this', ' and', ParaBreak(), 'that', EndLink(), '.'])

        ls = parse('[foo|http://eblong.com/]')
        self.assertEqual(ls, [Link('http://eblong.com/', True), 'foo', EndLink(True)])

        ls = parse('One [foo| http://eblong.com/ ] two.')
        self.assertEqual(ls, ['One ', Link('http://eblong.com/', True), 'foo', EndLink(True), ' two.'])

        ls = parse('[[name]] [[$name]] [[ $name ]].')
        self.assertEqual(ls, [Interpolate('name'), ' ', PlayerRef('name'), ' ', PlayerRef('name'), '.'])
        
        ls = parse('This is an [[$em]]italic[[$/em]] word.')
        self.assertEqual(ls, ['This is an ', Style('emph'), 'italic', EndStyle('emph'), ' word.'])

        ls = parse('An [$em]italic[ $/em ] word.[$para]Yeah.')
        self.assertEqual(ls, ['An ', Style('emph'), 'italic', EndStyle('emph'), ' word.', ParaBreak(), 'Yeah.'])


        self.assertRaises(ValueError, parse, '[bar')
        self.assertRaises(ValueError, parse, '[[bar')
        self.assertRaises(ValueError, parse, '[ [x] ]')
