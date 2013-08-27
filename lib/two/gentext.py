"""
The code structures for procedural text generation.
"""

import sys
import ast

import twcommon.misc

class GenTextSyntaxError(SyntaxError):
    pass

class GenText(object):
    def __init__(self, nod):
        self.nod = nod
    def dump(self, depth=0, nod=None):
        if depth == 0:
            nod = self.nod
        sys.stdout.write('  '*depth + repr(nod))
        if isinstance(nod, NodeClass):
            nod.dump(depth, self)
        else:
            sys.stdout.write('\n')

class NodeClass(object):
    prefix = b''
    def __repr__(self):
        if not self.prefix:
            return "<%s>" % (self.__class__.__name__,)
        else:
            return "<%s '%s'>" % (self.__class__.__name__, self.prefix.decode(),)
    def dump(self, depth, gentext):
        sys.stdout.write('\n')

class SymbolNode(NodeClass):
    def __init__(self, symbol):
        self.symbol = symbol
    def dump(self, depth, gentext):
        sys.stdout.write(' ')
        sys.stdout.write(self.symbol)
        sys.stdout.write('\n')
    
class SeqNode(NodeClass):
    def __init__(self, *nodes):
        self.nodes = nodes
    def dump(self, depth, gentext):
        sys.stdout.write('\n')
        for nod in self.nodes:
            gentext.dump(depth+1, nod)

class AltNode(NodeClass):
    def __init__(self, *nodes):
        self.nodes = nodes
    def dump(self, depth, gentext):
        sys.stdout.write('\n')
        for nod in self.nodes:
            gentext.dump(depth+1, nod)

class ANode(NodeClass):
    pass

class ParaNode(NodeClass):
    pass

class StopNode(NodeClass):
    pass

class SemiNode(NodeClass):
    pass

class CommaNode(NodeClass):
    pass

bare_node_class_map = {
    'A': ANode,
    'Para': ParaNode, 'PARA': ParaNode,
    'Stop': StopNode, 'STOP': StopNode,
    'Semi': SemiNode, 'SEMI': SemiNode,
    'Comma': CommaNode, 'COMMA': CommaNode,
    }

def evalnode(nod, prefix=b''):
    nodtyp = type(nod)
    
    if nodtyp is ast.Str:
        if not nod.s:
            return None
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

    if nodtyp is ast.Tuple:
        ls = []
        for (ix, subnod) in enumerate(nod.elts):
            pre = ':alt_'+str(ix)
            ls.append(evalnode(subnod, prefix=prefix+pre.encode()))
        res = AltNode(*ls)
        res.prefix = prefix
        return res

    if nodtyp is ast.Name:
        symbol = nod.id
        if symbol == 'None':
            return None
        if symbol in bare_node_class_map:
            cla = bare_node_class_map[symbol]
            # Prefixes not needed for these
            return cla()
        if symbol == twcommon.misc.sluggify(symbol):
            return SymbolNode(symbol)
        raise GenTextSyntaxError('not a special node or database key: %s' % (symbol,))

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
