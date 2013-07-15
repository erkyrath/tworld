import re

from twcommon.misc import sluggify

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
        nod = interp_node_table.get(key, None)
        if nod is None:
            return '[Unknown key: %s]' % (key,)
        if callable(nod):
            return nod(val)
        if val:
            return '[%s does not accept arguments]' % (key,)
        return nod[0](*nod[1:])

class Interpolate(InterpNode):
    classname = 'Interpolate'
    def __init__(self, expr):
        self.expr = expr
    def __repr__(self):
        return '<Interpolate "%s">' % (self.expr,)
    def __eq__(self, obj):
        return (isinstance(obj, Interpolate) and self.expr == obj.expr)

class If(InterpNode):
    classname = 'If'
    def __init__(self, expr):
        self.expr = expr
    def __repr__(self):
        return '<If "%s">' % (self.expr,)
    def __eq__(self, obj):
        return (isinstance(obj, If) and self.expr == obj.expr)
    
class ElIf(InterpNode):
    classname = 'ElIf'
    def __init__(self, expr):
        self.expr = expr
    def __repr__(self):
        return '<ElIf "%s">' % (self.expr,)
    def __eq__(self, obj):
        return (isinstance(obj, ElIf) and self.expr == obj.expr)
    
class Else(InterpNode):
    classname = 'Else'
    
class End(InterpNode):
    classname = 'End'
    
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

class OpenBracket(InterpNode):
    classname = 'OpenBracket'
    def describe(self):
        return '['

class CloseBracket(InterpNode):
    classname = 'CloseBracket'
    def describe(self):
        return ']'

class PlayerRef(InterpNode):
    classname = 'PlayerRef'
    def __init__(self, key, expr=None):
        self.key = key
        if expr:
            self.expr = expr
        else:
            self.expr = None
    def __repr__(self):
        if self.expr is None:
            return '<PlayerRef "%s">' % (self.key,)
        else:
            return '<PlayerRef "%s" %s>' % (self.key, self.expr)
    def __eq__(self, obj):
        return (isinstance(obj, PlayerRef) and self.key == obj.key and self.expr == obj.expr)

### LineBreak?

interp_node_table = {
    '$para': (ParaBreak,),
    '$openbracket': (OpenBracket,),
    '$closebracket': (CloseBracket,),
    '$if': lambda val: If(val),
    '$elif': lambda val: ElIf(val),
    '$else': (Else,),
    '$end': (End,),
    
    '$name': lambda val: PlayerRef('name', val),
    '$Name': lambda val: PlayerRef('name', val),
    '$we': lambda val: PlayerRef('we', val),
    '$they': lambda val: PlayerRef('we', val),
    '$us': lambda val: PlayerRef('us', val),
    '$them': lambda val: PlayerRef('us', val),
    '$our': lambda val: PlayerRef('our', val),
    '$their': lambda val: PlayerRef('our', val),
    '$ours': lambda val: PlayerRef('ours', val),
    '$theirs': lambda val: PlayerRef('ours', val),
    '$ourself': lambda val: PlayerRef('ourself', val),
    '$themself': lambda val: PlayerRef('ourself', val),
    '$We': lambda val: PlayerRef('We', val),
    '$They': lambda val: PlayerRef('We', val),
    '$Us': lambda val: PlayerRef('Us', val),
    '$Them': lambda val: PlayerRef('Us', val),
    '$Our': lambda val: PlayerRef('Our', val),
    '$Their': lambda val: PlayerRef('Our', val),
    '$Ours': lambda val: PlayerRef('Ours', val),
    '$Theirs': lambda val: PlayerRef('Ours', val),
    '$Ourself': lambda val: PlayerRef('Ourself', val),
    '$Themself': lambda val: PlayerRef('Ourself', val),
    
    '$em': (Style, 'emph'),
    '$/em': (EndStyle, 'emph'),
    '$fixed': (Style, 'fixed'),
    '$/fixed': (EndStyle, 'fixed'),
        ### run this through a site-specific Python hook.
    }

re_bracketgroup = re.compile('[[]+')
re_closeorbarorinterp = re.compile(']|[|][|]?|[[]')
re_twolinebreaks = re.compile('[ \t]*\n[ \t]*\n[ \t\n]*')
re_initdollar = re.compile('\\s*[$]')

def append_text_with_paras(dest, text, start=0, end=None):
    """
    Append literal text to a destination list. A blank line (two or more
    newlines in a row with only whitespace between) is converted into a
    ParaBreak node.
    (This does not care about square brackets; those should be dealt with
    already.)
    """
    if end is None:
        end = len(text)
    if end <= start:
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
    """
    Parse a string into a description list -- a list of strings and
    InterpNodes. This is responsible for finding square brackets and
    turning them into the correct nodes, according to a somewhat ornate
    set of rules. (Note unit tests, below.)
    """
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

        start = start+1
        
        if re_initdollar.match(text, start):
            # Special case: [$foo] is treated the same as [[$foo]]. Not a
            # link, but an interpolation.
            pos = text.find(']', start)
            if (pos < 0):
                raise ValueError('interpolated $symbol missing ]')
            chunk = text[start:pos]
            res.append(InterpNode.parse(chunk))
            start = pos+1
            continue

        # Read a [...] or [...|...] link. This (the first part) may
        # contain a mix of text and interpolations. We may also have
        # a [...||...] link, in which case the second part is pasted
        # into the text as well as the target.

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
                start = match.end()
                doublebar = (start - match.start() > 1)
                pos = text.find(']', start)
                if pos < 0:
                    raise ValueError('link | missing ]')
                chunk = text[start:pos]
                if doublebar:
                    append_text_with_paras(res, ' '+chunk)
                    curlink.target = sluggify(chunk)
                else:
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


# These routines will probably go somewhere else

pronoun_map_we = {
    'he': 'he',
    'she': 'she',
    'it': 'it',
    'they': 'they',
    'name': '', # suffix
    }
pronoun_map_We = { key:val.capitalize() for (key, val) in pronoun_map_we.items() }
pronoun_map_us = {
    'he': 'him',
    'she': 'her',
    'it': 'it',
    'they': 'them',
    'name': '', # suffix
    }
pronoun_map_Us = { key:val.capitalize() for (key, val) in pronoun_map_us.items() }
pronoun_map_our = {
    'he': 'his',
    'she': 'her',
    'it': 'its',
    'they': 'their',
    'name': "'s", # suffix
    }
pronoun_map_Our = { key:val.capitalize() for (key, val) in pronoun_map_our.items() }
pronoun_map_ours = {
    'he': 'his',
    'she': 'hers',
    'it': 'its',
    'they': 'theirs',
    'name': "'s", # suffix
    }
pronoun_map_Ours = { key:val.capitalize() for (key, val) in pronoun_map_ours.items() }
pronoun_map_ourself = {
    'he': 'himself',
    'she': 'herself',
    'it': 'itself',
    'they': 'themself',
    'name': '', # suffix
    }
pronoun_map_Ourself = { key:val.capitalize() for (key, val) in pronoun_map_ourself.items() }

pronoun_map_map = {
    'we': pronoun_map_we,
    'We': pronoun_map_We,
    'us': pronoun_map_us,
    'Us': pronoun_map_Us,
    'our': pronoun_map_our,
    'Our': pronoun_map_Our,
    'ours': pronoun_map_ours,
    'Ours': pronoun_map_Ours,
    'ourself': pronoun_map_ourself,
    'Ourself': pronoun_map_Ourself,
    }

def resolve_pronoun(player, mapkey):
    """
    Work out the pronoun string for a given player and a canonical pronoun.
    ('We', 'us', 'our', etc.)
    The player argument should be a players DB object -- or at least a
    dict containing 'name' and 'pronoun' entries. (None is also allowed.)
    """
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

    def test_pronoun(self):
        player = {'name':'Fred', 'pronoun':'he'}
        self.assertEqual('he', resolve_pronoun(player, 'we'))
        self.assertEqual('him', resolve_pronoun(player, 'us'))
        self.assertEqual('his', resolve_pronoun(player, 'our'))
        self.assertEqual('His', resolve_pronoun(player, 'Our'))
        self.assertEqual('His', resolve_pronoun(player, 'Ours'))
        self.assertEqual('Himself', resolve_pronoun(player, 'Ourself'))

        player = {'name':'Fred', 'pronoun':'she'}
        self.assertEqual('She', resolve_pronoun(player, 'We'))
        self.assertEqual('Her', resolve_pronoun(player, 'Us'))
        self.assertEqual('Her', resolve_pronoun(player, 'Our'))
        self.assertEqual('her', resolve_pronoun(player, 'our'))
        self.assertEqual('hers', resolve_pronoun(player, 'ours'))
        self.assertEqual('herself', resolve_pronoun(player, 'ourself'))

        player = {'name':'Fred', 'pronoun':'name'}
        self.assertEqual('Fred', resolve_pronoun(player, 'we'))
        self.assertEqual('Fred', resolve_pronoun(player, 'us'))
        self.assertEqual('Fred\'s', resolve_pronoun(player, 'our'))
        self.assertEqual('Fred\'s', resolve_pronoun(player, 'Our'))
        self.assertEqual('Fred\'s', resolve_pronoun(player, 'Ours'))
        self.assertEqual('Fred', resolve_pronoun(player, 'Ourself'))

        player = {'name':'Fred', 'pronoun':'they'}
        self.assertEqual('They', resolve_pronoun(player, 'We'))
        self.assertEqual('Them', resolve_pronoun(player, 'Us'))
        self.assertEqual('Their', resolve_pronoun(player, 'Our'))
        self.assertEqual('their', resolve_pronoun(player, 'our'))
        self.assertEqual('theirs', resolve_pronoun(player, 'ours'))
        self.assertEqual('themself', resolve_pronoun(player, 'ourself'))

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
        

if __name__ == '__main__':
    unittest.main()
