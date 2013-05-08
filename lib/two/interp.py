import re

def parse(text):
    if type(text) is not str:
        raise ValueError('interpolated text must be string')
    res = []

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
