import re

re_bracketgroup = re.compile('[[]+')
re_closeorbarorinterp = re.compile(']|[|]|[[]')

class Interpolate(object):
    def __init__(self, expr):
        self.expr = expr
    def __repr__(self):
        return '<Interpolate "%s">' % (self.expr,)

class Link(object):
    def __init__(self, target=None):
        self.target = target
    def __repr__(self):
        return '<Link "%s">' % (self.target,)
        
class EndLink(object):
    pass
    def __repr__(self):
        return '<EndLink>'

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
    ### Maybe turn space to _ first, then remove extra underscores? But several *real* underscores in a row should not collapse. I think we're turning punctuation to space, trim, remove extra, then to _.
    text = text.lower()
    text = re_nonidentchars.sub(' ', text)
    text = re_extrawhite.sub(' ', text)
    text = text.strip()
    text = text.replace(' ', '_')
    if not text or re_startdigit.match(text):
        text = '_' + text
    return text

### Unit test
