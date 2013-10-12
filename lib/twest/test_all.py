"""
Unit test runner.

To run:   python3 -m twest.test_all
(The twest, two, twcommon modules must be in your PYTHON_PATH.
MongoDB must be running; these tests run in (and trash) the 'testdb'
collection.)

This is a simplified version of the runner in tornado.testing.
"""

import sys
import unittest
import tornado.options
import tornado.testing

testlist = [
    'twest.test_interp',
    'twest.test_eval',
    'twest.test_funcs',
    'twest.test_propcache',
    'twcommon.misc',
    'two.grammar',
    ]

if __name__ == '__main__':

    # Sets up some logging stuff. Plus we may use the options someday.
    tornado.options.parse_command_line()
    
    argv = [sys.argv[0]] + testlist
    kwargs = {}
    unittest.main(module=None, argv=argv, **kwargs)
