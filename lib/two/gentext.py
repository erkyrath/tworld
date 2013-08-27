"""
The code structures for procedural text generation.
"""

import ast

class GenTextSyntaxError(SyntaxError):
    pass

class GenText(object):
    def __init__(self, nod):
        self.nod = nod

class NodeClass(object):
    prefix = b''
    pass

class SeqNode(NodeClass):
    def __init__(self, *nodes):
        self.nodes = nodes
    def __repr__(self):
        ls = [ repr(nod) for nod in self.nodes ]
        return '<SeqNode %s: %s>' % (self.prefix, ', '.join(ls))

def evalnode(nod, prefix=b''):
    nodtyp = type(nod)
    
    if nodtyp is ast.Str:
        return nod.s
        
    if nodtyp is ast.Num:
        return str(nod.n)
        
    if nodtyp is ast.List:
        ls = []
        for (ix, subnod) in enumerate(nod.elts):
            pre = ':seq_'+str(ix)
            ls.append(evalnode(subnod, prefix=prefix+pre.encode()))
        res = SeqNode(*ls)
        res.prefix = prefix
        return res

    if nodtyp is ast.Name:
        symbol = nod.id
        if symbol == 'None':
            return None
        raise Exception('### name not implemented')

    raise GenTextSyntaxError('Expression type not implemented: %s' % (nodtyp.__name__,))
        
def parse(text, originlabel='<gentext>'):
    tree = ast.parse(text, filename=originlabel)
    assert type(tree) is ast.Module

    if not tree.body:
        res = None
    elif len(tree.body) == 1:
        if type(tree.body[0]) is not ast.Expr:
            raise GenTextSyntaxError('statements not permitted')
        res = evalnode(tree.body[0].value)
    else:
        ls = []
        for (ix, nod) in enumerate(tree.body):
            if type(nod) is not ast.Expr:
                raise GenTextSyntaxError('statements not permitted')
            pre = ':seq_'+str(ix)
            ls.append(evalnode(nod.value, prefix=pre.encode()))
        res = SeqNode(*ls)

    return GenText(res)
