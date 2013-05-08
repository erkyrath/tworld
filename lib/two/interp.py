
def parse(text):
    if type(text) is not str:
        raise ValueError('interpolated text must be string')
    res = []

ident_char_set = set()
ident_char_set.add('_')
for ch in range(ord('a'), ord('z')+1):
    ident_char_set.add(chr(ch))
for ch in range(ord('0'), ord('9')+1):
    ident_char_set.add(chr(ch))
ident_char_plus_space_set = ident_char_set | set([' '])

def sluggify(text):
    text = text.lower()
    ls = [ ch for ch in text if ch in ident_char_plus_space_set ]
    while (ls and ls[-1] == ' '):
        ls.pop()
    while (ls and ls[0] == ' '):
        ls.pop(0)
    return ''.join(ls)
