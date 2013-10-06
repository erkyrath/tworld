"""
Utility code for parsing the structure of marked-up text objects.
(Strings with square-bracket interpolations.)
"""

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
    set of rules. (Note unit tests.)
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


# Late imports
from twcommon.misc import sluggify


