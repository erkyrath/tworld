import datetime
import re
import unicodedata

# The maximum length of an editable description, such as a player desc
# or editstr line.
MAX_DESCLINE_LENGTH = 256

class SuiGeneris(object):
    """Factory for when you want an object distinguishable from all other
    objects.
    """
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return '<%s>' % (self.name,)

def now():
    """Utility function: return "now" as an aware UTC datetime object.
    """
    return datetime.datetime.now(datetime.timezone.utc)

def is_typed_dict(obj, typ):
    """Returns true if obj is a dict and has a field 'type'=typ.
    """
    return (type(obj) is dict and obj.get('type', None) == typ)

# Regexps for sluggify
re_nonidentchars = re.compile('[^a-z0-9_ ]+')
re_extrawhite = re.compile('  +')
re_startdigit = re.compile('^[0-9]')

def sluggify(text):
    """
    Convert an arbitrary string to a valid Python (2) identifier that
    'reads the same'. We preserve letters and digits, while lowercasing
    and converting other characters to underscores. We try to avoid too
    many underscores in a row, but also try to keep them meaningful. (So
    'dr who' and 'Dr__Who' sluggify differently.)
    See also re_valididentifier in tweblib/handlers.py.
    ### Would be nice to follow Py3 identifier rules here, for Unicode.
    """
    text = text.lower()
    text = unicodedata.normalize('NFKD', text)  # Split off accent marks
    text = re_nonidentchars.sub(' ', text)  # Punctuation to spaces
    text = re_extrawhite.sub(' ', text)     # Remove redundant spaces
    text = text.strip()
    text = text.replace(' ', '_')
    if not text or re_startdigit.match(text):
        # Must not be empty or start with a digit
        text = '_' + text
    return text


import unittest

class TestInterpModule(unittest.TestCase):
    
    def test_sluggify(self):
        tests = [
            ('', '_'), (' ', '_'), ('  ', '_'), ('  ', '_'),
            ('_', '_'), ('__', '__'), ('___', '___'),
            ('.', '_'), ('..', '_'), ('. . .', '_'),
            (' _ ', '_'), (' _  _ ', '___'),
            ('a', 'a'), ('Hello', 'hello'), ('  one  two  ', 'one_two'),
            ('Dr. Who?', 'dr_who'), ('Dr__who', 'dr__who'),
            ('x\xE4 \xF8b', 'xa_b'), ('x\u24E4\xB9\uFF0A\uFF21y', 'xu1_ay'),
            ('a-Z_0-9', 'a_z_0_9'), ('95', '_95'), ('.001a', '_001a'),
            ]
        for (val, res) in tests:
            self.assertEqual(sluggify(val), res)


if __name__ == '__main__':
    unittest.main()
