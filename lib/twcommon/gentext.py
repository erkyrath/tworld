"""
The code structures for procedural text generation.
"""

import sys
import re
import hashlib
import struct
import ast

import twcommon.misc

import tornado.gen

# Check whether a string starts with a vowel.
re_vowelstart = re.compile('^[aeiou]', re.IGNORECASE)

# Used as a placeholder for the root argument of recursive functions.
RootPlaceholder = twcommon.misc.SuiGeneris('RootPlaceholder')

class GenTextSyntaxError(SyntaxError):
    pass

class GenText(object):
    """Represents a complete parsed {gentext} object. This is just a thin
    wrapper around a node, or tree of nodes.

    (A node may be a NodeClass object or a native type, so it's handy
    to have this wrapper.)
    """
    
    def __init__(self, nod):
        self.nod = nod
        
    def dump(self, depth=0, nod=RootPlaceholder):
        """Print out the contents of the node tree. For debugging only.
        """
        if nod is RootPlaceholder:
            nod = self.nod
        sys.stdout.write('  '*depth + repr(nod))
        if isinstance(nod, NodeClass):
            nod.dump(depth, self)
        else:
            sys.stdout.write('\n')

    @staticmethod
    def setup_context(ctx, capstart=True):
        """Prepare an EvalPropContext for text generation.

        (This, and the following, are static methods because they don't
        depend on any of the GenText's state. They operate solely on the
        evalctx. Logically they're evalctx methods, but I put them here
        to keep the generation code together.)
        """
        assert (not ctx.gentexting)
        # The seed should already be set
        assert (ctx.genseed is not None)
        ctx.gentexting = True
        ctx.genparams = {}
        ctx.gendocap = False
        if (capstart):
            ctx.gentextstate = BeginNode
        else:
            ctx.gentextstate = RunOnNode

    @staticmethod
    def final_context(ctx, stopend=True):
        """End text generation in an EvalPropContext, applying the final
        stop (if required). Clear out all the state variables.
        """
        assert (ctx.gentexting)
        if stopend and ctx.gentextstate is not 'BEGIN':
            ctx.accum.append('.')
        ctx.genparams = None
        ctx.gentextstate = None
        ctx.gendocap = False
        ctx.gentexting = False

    @staticmethod
    def append_context(ctx, val):
        """Add one element to an EvalPropContext. The value must be a
        (nonempty) string or a static NodeClass. This relies on, and
        modifies, the ctx state variables (gentextstate and gendocap).
        The upshot is to (probably) add a new string to ctx.accum, or
        perhaps a paragraph break marker.

        This algorithm is occult, and I'm sorry for that. It's not logically
        *that* complicated; but it has a lot of interacting cases.
        """
        if isinstance(val, NodeClass):
            nodtyp = type(val)
            if nodtyp in (RunOnNode, CommaNode, SemiNode, StopNode, ParaNode):
                # Retain the more severe break form.
                if ctx.gentextstate.precedence < nodtyp.precedence:
                    ctx.gentextstate = nodtyp
                return
        else:
            assert (type(val) is str and len(val) > 0)
            nodtyp = WordNode
            
        ctx.gendocap = False
        
        if ctx.gentextstate in (BeginNode, StopNode, ParaNode):
            if ctx.gentextstate is StopNode:
                ctx.accum.append('. ')
            elif ctx.gentextstate is ParaNode:
                ctx.accum.append('.')
                ctx.accum.append(['para']) # see interp.ParaBreak
            ctx.gendocap = True
        elif ctx.gentextstate is SemiNode:
            ctx.accum.append('; ')
        elif ctx.gentextstate is CommaNode:
            ctx.accum.append(', ')
        elif ctx.gentextstate is RunOnNode:
            pass
        elif ctx.gentextstate is RunOnCapNode:
            ctx.gendocap = True
        elif ctx.gentextstate is ANode:
            if nodtyp is AFormNode:
                ctx.accum.append(' ')
            elif nodtyp is AnFormNode:
                ctx.accum.append('n ')
            elif nodtyp is WordNode and re_vowelstart.match(val):
                ctx.accum.append('n ')
            else:
                ctx.accum.append(' ')
        else:
            ctx.accum.append(' ')
            
        if nodtyp is ANode:
            if ctx.gendocap:
                ctx.accum.append('A')
            else:
                ctx.accum.append('a')
            ctx.gentextstate = ANode
        elif nodtyp in (AFormNode, AnFormNode):
            if ctx.gendocap:
                ctx.gentextstate = RunOnCapNode
            else:
                ctx.gentextstate = RunOnNode
        elif nodtyp is WordNode:
            if ctx.gendocap:
                ctx.accum.append(val[0].upper())
                ctx.accum.append(val[1:])
            else:                   
                ctx.accum.append(val)
            ctx.gentextstate = WordNode
        else:
            ctx.accum.append('[Unsupported NodeClass: %s]' % (nodtyp.__name__,))
            

    @tornado.gen.coroutine
    def perform(self, ctx, propname, nod=RootPlaceholder):
        """Generate text (to ctx.accum). This is yieldy, since it may have
        to check properties.

        The propname should be a bytes; it will be prepended to node
        prefixes.

        This calls append_context(), or else it calls NodeClass implementations
        that call append_context().
        """
        if nod is RootPlaceholder:
            nod = self.nod

        if nod is None:
            return
        if not isinstance(nod, NodeClass):
            val = str(nod)
            if val:
                self.append_context(ctx, val)
            return
        yield nod.perform(ctx, propname, self)

class NodeClass(object):
    """Virtual base class for gentext nodes -- the ones that aren't
    native types, that is.
    """
    prefix = b''
    
    def __repr__(self):
        if not self.prefix:
            return "<%s>" % (self.__class__.__name__,)
        else:
            return "<%s '%s'>" % (self.__class__.__name__, self.prefix.decode(),)
    def dump(self, depth, gentext):
        """For debugging only. Overridden by subclasses to display themselves
        to stdout. The output must include a newline.
        """
        sys.stdout.write('\n')

    def computeseed(self, seed, propname):
        """Generate a pseudo-random number based on the seed, propname,
        and prefix. The arguments must be byteses. The result is (should
        be) an unsigned 32-bit integer with uniform distribution.

        I'm not sure this is speedy. But I don't know a good alternative
        either.
        """
        hash = hashlib.md5()
        hash.update(seed)
        hash.update(propname)
        hash.update(self.prefix)
        res = struct.unpack('!I', hash.digest()[-4:])
        return res[0]

    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        """Do the work of the node, which boils down to calling
        append_context(), or maybe perform() recursively on subnodes.
        """
        gentext.append_context(ctx, '[Unimplemented NodeClass: %s]' % (repr(self),))
        
class SymbolNode(NodeClass):
    """A bare (lowercase) symbol, which will be looked up as a property.
    """
    def __init__(self, symbol):
        self.symbol = symbol
    def dump(self, depth, gentext):
        sys.stdout.write(' ')
        sys.stdout.write(self.symbol)
        sys.stdout.write('\n')
    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        res = yield ctx.evalobj(self.symbol)
        if res is not ctx._Accumulated: ### terrible
            if res is not None:
                val = str(res)
                if val:
                    gentext.append_context(ctx, val)
    
class SeqNode(NodeClass):
    """A sequence of subnodes; they are all rendered in sequence.
    """
    def __init__(self, *nodes):
        self.nodes = nodes
    def dump(self, depth, gentext):
        sys.stdout.write('\n')
        for nod in self.nodes:
            gentext.dump(depth+1, nod)
            
    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        for nod in self.nodes:
            yield gentext.perform(ctx, propname, nod)

class AltNode(NodeClass):
    """A set of subnodes; one is selected at random.
    """
    def __init__(self, *nodes):
        self.nodes = nodes
    def dump(self, depth, gentext):
        sys.stdout.write('\n')
        for nod in self.nodes:
            gentext.dump(depth+1, nod)
            
    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        count = len(self.nodes)
        if not count:
            return
        if count == 1:
            nod = self.nodes[0]
        else:
            seed = self.computeseed(ctx.genseed, propname)
            nod = self.nodes[seed % count]
        yield gentext.perform(ctx, propname, nod)

        
class StaticNodeClass(NodeClass):
    """Subclass for nodes that just represent themselves, literally,
    in the output stream.

    The precedence field lets us string several together (a STOP
    next to a COMMA, for example) and keep the most severe break.
    """
    precedence = 0
    
    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        gentext.append_context(ctx, self)
        
class BeginNode(StaticNodeClass):
    # Not generateable
    precedence = 10
    pass

class WordNode(StaticNodeClass):
    # Not generateable
    pass

class ANode(StaticNodeClass):
    pass

class AFormNode(StaticNodeClass):
    pass

class AnFormNode(StaticNodeClass):
    pass

class RunOnNode(StaticNodeClass):
    pass
    
class RunOnCapNode(StaticNodeClass):
    # Not generateable
    pass
    
class ParaNode(StaticNodeClass):
    precedence = 4
    pass

class StopNode(StaticNodeClass):
    precedence = 3
    pass

class SemiNode(StaticNodeClass):
    precedence = 2
    pass

class CommaNode(StaticNodeClass):
    precedence = 1
    pass

bare_node_class_map = {
    '_': RunOnNode,
    'A': ANode, 'An': ANode, 'AN': ANode,
    'AForm': AFormNode, 'AFORM': AFormNode, 
    'AnForm': AnFormNode, 'ANFORM': AnFormNode, 
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
    """Convert an ast (syntax tree) node into a GenText node. The result
    may be a native type (int, str, bool, None) or a NodeClass object.

    Raises GenTextSyntaxError on failure.
    """
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
    """Given a block of text, break it down into a GenText() node. Raises
    SyntaxError (or subclass GenTextSyntaxError) on failure.

    This starts by calling ast.parse; the GenText syntax is Python syntax.
    (The semantics are totally not Python.)
    """
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

