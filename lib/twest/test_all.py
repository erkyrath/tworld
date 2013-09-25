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
import tornado.testing

testlist = [
    'twest.test_eval',
    'twest.test_propcache',
    ]

if __name__ == '__main__':
    argv = [sys.argv[0]] + testlist
    kwargs = {}
    unittest.main(module=None, argv=argv, **kwargs)
