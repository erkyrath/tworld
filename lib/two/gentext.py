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

call_node_class_map = {
    'Seq': SeqNode,
    'Alt': AltNode,
    }

def evalnode(nod, prefix=b''):
    nodtyp = type(nod)

    # We handle simple types (int, float, str, bool, None) as themselves.
    # This is because we use the same evaluator for node arguments, some
    # of which are flags or strings or numbers.
    #
    # On the other hand, we turn lists and tuples into SeqNode and AltNode
    # objects. Hope I don't need those as arguments anywhere.
    
    if nodtyp is ast.Str:
        return nod.s
        
    if nodtyp is ast.Num:
        return nod.n
        
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
        if symbol == 'True':
            return True
        if symbol == 'False':
            return False
        if symbol in bare_node_class_map:
            cla = bare_node_class_map[symbol]
            # Prefixes not needed for these
            return cla()
        if symbol in call_node_class_map:
            raise GenTextSyntaxError('special node requires arguments: %s' % (symbol,))
        if symbol == twcommon.misc.sluggify(symbol):
            return SymbolNode(symbol)
        raise GenTextSyntaxError('not a special node or database key: %s' % (symbol,))

    if nodtyp is ast.Call:
        if type(nod.func) is not ast.Name:
            raise GenTextSyntaxError('only literals may be called')
        symbol = nod.func.id
        if symbol in bare_node_class_map:
            cla = bare_node_class_map[symbol]
            # Prefixes not needed for these
            return cla()
        if symbol in call_node_class_map:
            cla = call_node_class_map[symbol]
            ### arguments
            args = []
            for (ix, subnod) in enumerate(nod.args):
                pre = ':arg_'+str(ix)
                args.append(evalnode(subnod, prefix=prefix+pre.encode()))
            if nod.starargs:
                raise GenTextSyntaxError('*args not supported')
            kwargs = {}
            for subnod in nod.keywords:
                pre = ':kwarg_'+subnod.arg
                kwargs[subnod.arg] = evalnode(subnod.value, prefix=prefix+pre.encode())
            if nod.kwargs:
                raise GenTextSyntaxError('**kwargs not supported')
            res = cla(*args, **kwargs)
            res.prefix = prefix
            return res
        raise GenTextSyntaxError('not a special node: %s()' % (symbol,))

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
