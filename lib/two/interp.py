import re

class InterpNode(object):
    """Base class for special objects parsed out of a string by the
    parse() method.
    """
    def __repr__(self):
        return '<%s>' % (self.classname,)
    
    def __eq__(self, obj):
        return (isinstance(obj, InterpNode) and self.classname == obj.classname)
    def __ne__(self, obj):
        return not self.__eq__(obj)
    def describe(self):
        return repr(self)
    
    @staticmethod
    def parse(expr):
        """An interpolated expression that starts with a dollar sign is
        a special token. Parse it and return the appropriate InterpNode
        object. If it doesn't start with $, it's an Interpolate object.
        """
        expr = expr.strip()
        if not expr.startswith('$'):
            return Interpolate(expr)
        key, dummy, val = expr.partition(' ')
        val = val.strip()
        # This could probably be more efficient
        if key == '$para':
            return ParaBreak()
        if key == '$name' or key == '$Name':
            return PlayerRef('name') ### val may be an expression
        if key == '$we':
            return PlayerRef('we')
        if key == '$us':
            return PlayerRef('us')
        if key == '$our':
            return PlayerRef('our')
        if key == '$ours':
            return PlayerRef('ours')
        if key == '$ourself':
            return PlayerRef('ourself')
        if key == '$We':
            return PlayerRef('We')
        if key == '$Our':
            return PlayerRef('Our')
        if key == '$em':
            return Style('emph')
        if key == '$/em':
            return EndStyle('emph')
        if key == '$fixed':
            return Style('fixed')
        if key == '$/fixed':
            return EndStyle('fixed')
        return '[Unknown key: %s]' % (key,)

class Interpolate(InterpNode):
    classname = 'Interpolate'
    def __init__(self, expr):
        self.expr = expr
    def __repr__(self):
        return '<Interpolate "%s">' % (self.expr,)
    def __eq__(self, obj):
        return (isinstance(obj, Interpolate) and self.expr == obj.expr)

class Link(InterpNode):
    classname = 'Link'
    def __init__(self, target=None, external=False):
        self.target = target
        self.external = external
    def __repr__(self):
        if not self.external:
            return '<Link "%s">' % (self.target,)
        else:
            return '<Link (ext) "%s">' % (self.target,)
    def __eq__(self, obj):
        return (isinstance(obj, Link) and self.target == obj.target and self.external == obj.external)

    @staticmethod
    def looks_url_like(val):
        val = val.strip()
        if val.startswith('http:'):
            return True
        return False
        
class EndLink(InterpNode):
    classname = 'EndLink'
    def __init__(self, external=False):
        self.external = external
    def __eq__(self, obj):
        return (isinstance(obj, EndLink) and self.external == obj.external)

    def describe(self):
        if not self.external:
            return ['/link']
        else:
            return ['/exlink']

class Style(InterpNode):
    classname = 'Style'
    def __init__(self, key=None):
        self.key = key
    def __repr__(self):
        return '<Style "%s">' % (self.key,)
    def __eq__(self, obj):
        return (isinstance(obj, Style) and self.key == obj.key)
    def describe(self):
        return ['style', self.key]

class EndStyle(InterpNode):
    classname = 'EndStyle'
    def __init__(self, key=None):
        self.key = key
    def __repr__(self):
        return '<EndStyle "%s">' % (self.key,)
    def __eq__(self, obj):
        return (isinstance(obj, EndStyle) and self.key == obj.key)
    def describe(self):
        return ['/style', self.key]

class ParaBreak(InterpNode):
    classname = 'ParaBreak'
    def describe(self):
        return ['para']

class PlayerRef(InterpNode):
    classname = 'PlayerRef'
    def __init__(self, key, expr=None):
        self.key = key
        self.expr = expr
    def __repr__(self):
        if self.expr is None:
            return '<PlayerRef "%s">' % (self.key,)
        else:
            return '<PlayerRef "%s" %s>' % (self.key, self.expr)
    def __eq__(self, obj):
        return (isinstance(obj, PlayerRef) and self.key == obj.key and self.expr == obj.expr)

### LineBreak
### If, Else, Elif, End

re_bracketgroup = re.compile('[[]+')
re_closeorbarorinterp = re.compile(']|[|]|[[]')
re_twolinebreaks = re.compile('[ \t]*\n[ \t]*\n[ \t\n]*')

def append_text_with_paras(dest, text, start, end):
    if (end <= start):
        return

    text = text[start:end]

    ls = re_twolinebreaks.split(text)
    if len(ls) <= 1:
        # No double line breaks found.
        dest.extend(ls)
        return

    first = True
    for el in ls:
        if first:
            first = False
        else:
            dest.append(ParaBreak())
        if el:
            dest.append(el)

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
        append_text_with_paras(res, text, start, pos)
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
            chunk = text[start:pos]
            res.append(InterpNode.parse(chunk))
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
                append_text_with_paras(res, text, start, pos)
                chunk = text[linkstart:pos]
                if Link.looks_url_like(chunk):
                    curlink.target = chunk.strip()
                    curlink.external = True
                else:
                    curlink.target = sluggify(chunk)
                res.append(EndLink(curlink.external))
                curlink = None
                start = pos+1
                break
            if text[pos] == '|':
                append_text_with_paras(res, text, start, pos)
                start = pos+1
                pos = text.find(']', start)
                if pos < 0:
                    raise ValueError('link | missing ]')
                chunk = text[start:pos]
                curlink.target = chunk.strip()
                curlink.external = Link.looks_url_like(chunk)
                res.append(EndLink(curlink.external))
                curlink = None
                start = pos+1
                break
            if text[pos] == '[' and pos+1 < len(text) and text[pos+1] != '[':
                raise ValueError('links cannot be nested')
            # [[ inside the [
            # Read a complete top-level [[...]] interpolation.
            append_text_with_paras(res, text, start, pos)
            start = pos+2
            pos = text.find(']]', start)
            if (pos < 0):
                raise ValueError('interpolated text in link missing ]]')
            chunk = text[start:pos]
            res.append(InterpNode.parse(chunk))
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

# These routines will probably go somewhere else

pronoun_map_we = {
    'he': 'he',
    'she': 'she',
    'it': 'it',
    'they': 'they',
    'name': '', # suffix
    }
pronoun_map_We = {
    'he': 'He',
    'she': 'She',
    'it': 'It',
    'they': 'They',
    'name': '', # suffix
    }
pronoun_map_us = {
    'he': 'him',
    'she': 'her',
    'it': 'it',
    'they': 'them',
    'name': '', # suffix
    }
pronoun_map_our = {
    'he': 'his',
    'she': 'her',
    'it': 'its',
    'they': 'their',
    'name': "'s", # suffix
    }
pronoun_map_Our = {
    'he': 'His',
    'she': 'Her',
    'it': 'Its',
    'they': 'Their',
    'name': "'s", # suffix
    }
pronoun_map_ours = {
    'he': 'his',
    'she': 'hers',
    'it': 'its',
    'they': 'theirs',
    'name': "'s", # suffix
    }
pronoun_map_ourself = {
    'he': 'himself',
    'she': 'herself',
    'it': 'itself',
    'they': 'themself',
    'name': '', # suffix
    }
pronoun_map_map = {
    'we': pronoun_map_we,
    'We': pronoun_map_We,
    'us': pronoun_map_us,
    'our': pronoun_map_our,
    'Our': pronoun_map_Our,
    'ours': pronoun_map_ours,
    'ourself': pronoun_map_ourself,
    }

def resolve_pronoun(player, mapkey):
    if not player:
        player = { 'name': 'nobody', 'pronoun': 'it' }
    map = pronoun_map_map[mapkey]
    if player['pronoun'] == 'name':
        # Add the suffix to the player's name
        return player['name'] + map['name']
    res = map.get(player['pronoun'], None)
    if not res:
        res = map.get('it')
    return res

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

        ls = parse('One.\nTwo.')
        self.assertEqual(ls, ['One.\nTwo.'])

        ls = parse('One.\n\nTwo.[[$para]]Three.')
        self.assertEqual(ls, ['One.', ParaBreak(), 'Two.', ParaBreak(), 'Three.'])

        ls = parse('\nOne. \n \n Two.\n\n\nThree. \n\t\n  ')
        self.assertEqual(ls, ['\nOne.', ParaBreak(), 'Two.', ParaBreak(), 'Three.', ParaBreak()])

        ls = parse('[foo|http://eblong.com/]')
        self.assertEqual(ls, [Link('http://eblong.com/', True), 'foo', EndLink(True)])

        ls = parse('One [foo| http://eblong.com/ ] two.')
        self.assertEqual(ls, ['One ', Link('http://eblong.com/', True), 'foo', EndLink(True), ' two.'])

        ls = parse('[[name]] [[$name]] [[ $name ]].')
        self.assertEqual(ls, [Interpolate('name'), ' ', PlayerRef('name'), ' ', PlayerRef('name'), '.'])
        

        self.assertRaises(ValueError, parse, '[bar')
        self.assertRaises(ValueError, parse, '[[bar')
        self.assertRaises(ValueError, parse, '[ [x] ]')
        

if __name__ == '__main__':
    unittest.main()
