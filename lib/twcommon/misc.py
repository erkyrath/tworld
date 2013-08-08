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

def gen_bool_parse(val):
    """Convert a string, as a human might type it, to a boolean. Unrecognized
    values raise an exception.
    """
    val = val.strip()
    if not val:
        return False
    try:
        return bool(int(val))
    except:
        pass
    ch = val[0]
    if ch in {'t', 'T', 'y', 'Y'}:
        return True
    if ch in {'f', 'F', 'n', 'N'}:
        return False
    raise ValueError('"%s" does not look like a boolean' % (val,))
    
def now():
    """Utility function: return "now" as an aware UTC datetime object.
    """
    return datetime.datetime.now(datetime.timezone.utc)

def gen_datetime_format(obj):
    """Utility function: convert a datetime to a clean-looking string.
    (No timezone part; no time part if there is none.)
    """
    obj = obj.replace(tzinfo=None)
    if obj.hour == 0 and obj.minute == 0 and obj.second == 0 and obj.microsecond == 0:
        return obj.strftime('%Y-%m-%d')
    else:
        return str(obj)

def gen_datetime_parse(val):
    """Utility function: convert a simple string (as produced by
    gen_datetime_format) into an aware UTC datetime object.
    """
    try:
        res = datetime.datetime.strptime(val, '%Y-%m-%d')
        return res.replace(tzinfo=datetime.timezone.utc)
    except:
        pass
    try:
        res = datetime.datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
        return res.replace(tzinfo=datetime.timezone.utc)
    except:
        pass
    try:
        res = datetime.datetime.strptime(val, '%Y-%m-%d %H:%M:%S.%f')
        return res.replace(tzinfo=datetime.timezone.utc)
    except:
        pass
    raise Exception('Date-time format not recognized: %s' % (val,))

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

    def test_genboolparse(self):
        self.assertEqual(gen_bool_parse(''), False)
        self.assertEqual(gen_bool_parse('  '), False)
        self.assertEqual(gen_bool_parse('0'), False)
        self.assertEqual(gen_bool_parse('1'), True)
        self.assertEqual(gen_bool_parse('2'), True)
        self.assertEqual(gen_bool_parse('01'), True)
        self.assertEqual(gen_bool_parse('t'), True)
        self.assertEqual(gen_bool_parse('true'), True)
        self.assertEqual(gen_bool_parse('  TRUE  '), True)
        self.assertEqual(gen_bool_parse('f'), False)
        self.assertEqual(gen_bool_parse(' false '), False)
        self.assertEqual(gen_bool_parse('False'), False)
        self.assertEqual(gen_bool_parse('yes'), True)
        self.assertEqual(gen_bool_parse('Y'), True)
        self.assertEqual(gen_bool_parse('no'), False)
        self.assertEqual(gen_bool_parse('N'), False)
        self.assertRaises(ValueError, gen_bool_parse, 'x')
        self.assertRaises(ValueError, gen_bool_parse, '?')
        self.assertRaises(ValueError, gen_bool_parse, '1.1')
        self.assertRaises(ValueError, gen_bool_parse, '.')

    def test_gendatetime(self):
        date1 = datetime.datetime(year=2013, month=7, day=16, tzinfo=datetime.timezone.utc)
        self.assertEqual(gen_datetime_parse('2013-07-16'), date1)
        self.assertEqual(gen_datetime_format(date1), '2013-07-16')
        
        date2 = datetime.datetime(year=2001, month=1, day=1, hour=2, minute=3, second=5, tzinfo=datetime.timezone.utc)
        self.assertEqual(gen_datetime_parse('2001-01-01 02:03:05'), date2)
        self.assertEqual(gen_datetime_format(date2), '2001-01-01 02:03:05')
        
        date3 = datetime.datetime(year=2199, month=12, day=31, hour=23, minute=59, second=59, microsecond=123456, tzinfo=datetime.timezone.utc)
        self.assertEqual(gen_datetime_parse('2199-12-31 23:59:59.123456'), date3)
        self.assertEqual(gen_datetime_format(date3), '2199-12-31 23:59:59.123456')

        date4 = now()
        self.assertEqual(date4, gen_datetime_parse(gen_datetime_format(date4)))
    
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
