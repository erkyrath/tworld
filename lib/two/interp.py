import re

class InterpNode(object):
    def describe(self):
        return repr(self)

class Interpolate(InterpNode):
    def __init__(self, expr):
        self.expr = expr
    def __repr__(self):
        return '<Interpolate "%s">' % (self.expr,)
    def __eq__(self, obj):
        return (isinstance(obj, Interpolate) and self.expr == obj.expr)
    def __ne__(self, obj):
        return not (isinstance(obj, Interpolate) and self.expr == obj.expr)

class Link(InterpNode):
    def __init__(self, target=None):
        self.target = target
    def __repr__(self):
        return '<Link "%s">' % (self.target,)
    def __eq__(self, obj):
        return (isinstance(obj, Link) and self.target == obj.target)
    def __ne__(self, obj):
        return not (isinstance(obj, Link) and self.target == obj.target)
    def describe(self):
        return ['link', self.target]
        
class EndLink(InterpNode):
    def __repr__(self):
        return '<EndLink>'
    def __eq__(self, obj):
        return (isinstance(obj, EndLink))
    def __ne__(self, obj):
        return not (isinstance(obj, EndLink))
    def describe(self):
        return ['/link']

class ParaBreak(InterpNode):
    def __repr__(self):
        return '<ParaBreak>'
    def __eq__(self, obj):
        return (isinstance(obj, ParaBreak))
    def __ne__(self, obj):
        return not (isinstance(obj, ParaBreak))

### LineBreak
### If, Else, Elif, End

re_bracketgroup = re.compile('[[]+')
re_closeorbarorinterp = re.compile(']|[|]|[[]')

def parse(text):
    if type(text) is not str:
        raise ValueError('interpolated text must be string')
    res = []
    start = 0
    curlink = None
    
    while (start < len(text)):
        match = re_bracketgroup.search(text, start)
        if not match:
            pos = len(text)
        else:
            pos = match.start()
        if (pos > start):
            res.append(text[start:pos])
        if not match:
            break
        start = pos
        numbrackets = match.end() - start
        
        if numbrackets == 2:
            # Read a complete top-level [[...]] interpolation.
            start = start+2
            pos = text.find(']]', start)
            if (pos < 0):
                raise ValueError('interpolated text missing ]]')
            chunk = text[start:pos].strip()
            res.append(Interpolate(chunk))
            start = pos+2
            continue

        # Read a [...] or [...|...] link. This (the first part) may
        # contain a mix of text and interpolations.
        start = start+1
        linkstart = start
        assert curlink is None
        curlink = Link()
        res.append(curlink)
        
        while (start < len(text)):
            match = re_closeorbarorinterp.search(text, start)
            if not match:
                raise ValueError('link missing ]')
            pos = match.start()
            if text[pos] == ']':
                if pos > start:
                    res.append(text[start:pos])
                chunk = text[linkstart:pos]
                curlink.target = sluggify(chunk)
                curlink = None
                res.append(EndLink())
                start = pos+1
                break
            if text[pos] == '|':
                if pos > start:
                    res.append(text[start:pos])
                start = pos+1
                pos = text.find(']', start)
                if pos < 0:
                    raise ValueError('link | missing ]')
                chunk = text[start:pos]
                curlink.target = chunk.strip()
                curlink = None
                res.append(EndLink())
                start = pos+1
                break
            if text[pos] == '[' and pos+1 < len(text) and text[pos+1] != '[':
                raise ValueError('links cannot be nested')
            # [[ inside the [
            # Read a complete top-level [[...]] interpolation.
            if pos > start:
                res.append(text[start:pos])
            start = pos+2
            pos = text.find(']]', start)
            if (pos < 0):
                raise ValueError('interpolated text in link missing ]]')
            chunk = text[start:pos].strip()
            res.append(Interpolate(chunk))
            start = pos+2
            continue
        
    return res

re_nonidentchars = re.compile('[^a-z0-9_ ]+')
re_extrawhite = re.compile('  +')
re_startdigit = re.compile('^[0-9]')

def sluggify(text):
    ### Would be nice to follow Py3 identifier rules here, for Unicode.
    text = text.lower()
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
            ('a-Z_0-9', 'a_z_0_9'), ('95', '_95'), ('.001a', '_001a'),
            ]
        for (val, res) in tests:
            self.assertEqual(sluggify(val), res)

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

        self.assertRaises(ValueError, parse, '[bar')
        self.assertRaises(ValueError, parse, '[[bar')
        self.assertRaises(ValueError, parse, '[ [x] ]')
        

if __name__ == '__main__':
    unittest.main()
