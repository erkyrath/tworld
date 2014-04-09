"""
The code structures for procedural text generation.
"""

import sys
import hashlib
import struct
import ast

import twcommon.misc

import tornado.gen

# Used as a placeholder for the root argument of recursive functions.
RootPlaceholder = twcommon.misc.SuiGeneris('RootPlaceholder')

class GenTextSyntaxError(SyntaxError):
    pass

class GenText(object):
    """Represents a complete parsed {gentext} object. This is just a thin
    wrapper around a node, or tree of nodes.

    (A node may be a GenNodeClass object or a native type, so it's handy
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
        if isinstance(nod, GenNodeClass):
            nod.dump(depth, self)
        else:
            sys.stdout.write('\n')

    @staticmethod
    def setup_context(ctx):
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
        ctx.gencount = 0
        ctx.genparams = {}

    @staticmethod
    def final_context(ctx):
        """End text generation in an EvalPropContext, applying the final
        stop (if required). Clear out all the state variables.
        """
        assert (ctx.gentexting)
        ctx.gencount = None
        ctx.genparams = None
        ctx.gentexting = False

    @tornado.gen.coroutine
    def perform(self, ctx, propname, nod=RootPlaceholder):
        """Generate text (to ctx.accum). This is yieldy, since it may have
        to check properties.

        The propname should be a bytes; it will be prepended to node
        prefixes.

        This calls accum_append(), or else it calls GenNodeClass
        implementations that call accum_append().
        """
        ctx.task.tick()
        
        if nod is RootPlaceholder:
            nod = self.nod

        if nod is None:
            return
        if not isinstance(nod, GenNodeClass):
            val = str(nod)
            if val:
                ctx.accum_append(val)
            return
        yield nod.perform(ctx, propname, self)

class GenNodeClass(object):
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

    def computeseed(self, ctx, propname):
        """Generate a pseudo-random number based on the context, propname,
        and prefix. The ctx.seed, propname, and prefix must be byteses.
        The result is (should be) an unsigned 32-bit integer with uniform
        distribution.

        I'm not sure this is speedy. But I don't know a good alternative
        either.
        """
        count = str(ctx.gencount).encode()
        ctx.gencount += 1
        
        hash = hashlib.md5()
        hash.update(ctx.genseed)
        hash.update(count)
        hash.update(propname)
        hash.update(self.prefix)
        res = struct.unpack('!I', hash.digest()[-4:])
        return res[0]

    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        """Do the work of the node, which boils down to calling
        accum_append(), or maybe perform() recursively on subnodes.
        """
        ctx.accum_append('[Unimplemented GenNodeClass: %s]' % (repr(self),))
        
class SymbolNode(GenNodeClass):
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
        if not (res is None or res == ''):
            ctx.accum_append(str(res))
    
class SeqNode(GenNodeClass):
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

class AltNode(GenNodeClass):
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
            seed = self.computeseed(ctx, propname)
            nod = self.nodes[seed % count]
        yield gentext.perform(ctx, propname, nod)

        
class ShuffleNode(GenNodeClass):
    """A set of subnodes; one is selected at random, but avoiding repeats
    where possible.
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
            yield gentext.perform(ctx, propname, nod)
            return

        shufflekey = propname+self.prefix
        ls = ctx.genparams.get(shufflekey, None)
        if ls is None:
            ls = list(range(count))
        if len(ls) == 1:
            index = ls[0]
            ls = list(range(count))
            ls.remove(index)
        else:
            seed = self.computeseed(ctx, propname)
            index = ls.pop(seed % len(ls))
        ctx.genparams[shufflekey] = ls
        nod = self.nodes[index]
        yield gentext.perform(ctx, propname, nod)

class WeightNode(GenNodeClass):
    """A set of subnodes; one is selected at random, according to
    weights.
    """
    def __init__(self, *nodes):
        self.nodes = []
        self.total = 0.0
        for ix in range(0, len(nodes), 2):
            wgt = float(nodes[ix])
            if wgt < 0:
                raise Exception('Weight: entry is negative')
            nod = nodes[ix+1]
            self.nodes.append( (wgt, nod) )
            self.total = self.total + wgt
        if self.total < 0:
            raise Exception('Weight: total is negative')
    def dump(self, depth, gentext):
        sys.stdout.write('\n')
        for (wgt, nod) in self.nodes:
            sys.stdout.write('%s%f' % ('  '*depth, wgt,))
            gentext.dump(depth+1, nod)
            
    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        seed = self.computeseed(ctx, propname)
        val = ((seed % 65535) / 65535.0) * self.total
        total = 0.0
        selnod = self.nodes[-1][1]
        for (wgt, nod) in self.nodes:
            if (val < total + wgt):
                selnod = nod
                break
            total = total + wgt
        yield gentext.perform(ctx, propname, selnod)

        
class OptNode(GenNodeClass):
    """One subnode, which has a given probability of appearing.
    """
    def __init__(self, val, nod):
        self.chance = val
        self.node = nod
    def dump(self, depth, gentext):
        sys.stdout.write('\n')
        gentext.dump(depth+1, self.node)

    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        seed = self.computeseed(ctx, propname)
        if ((seed % 65535) / 65535.0) < self.chance:
            yield gentext.perform(ctx, propname, self.node)
        
class SetKeyNode(GenNodeClass):
    """Set a generation parameter. Also takes an optional subnode.
    """
    def __init__(self, key, val, nod=None):
        self.key = key
        self.value = val
        self.node = nod
    def dump(self, depth, gentext):
        sys.stdout.write('%s = %s\n' % (self.key, repr(self.value)))
        if self.node is not None:
            gentext.dump(depth+1, self.node)

    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        val = self.value
        if isinstance(val, SymbolNode):
            val = yield ctx.evalobj(val.symbol)
        ctx.genparams[self.key] = val
        if self.node is not None:
            yield gentext.perform(ctx, propname, self.node)
            
class IfKeyNode(GenNodeClass):
    """Select one of two subnodes, based on a generation parameter.
    """
    def __init__(self, key, val, truenod, falsenod=None):
        self.key = key
        self.value = val
        self.truenode = truenod
        self.falsenode = falsenod
    def dump(self, depth, gentext):
        sys.stdout.write('%s == %s\n' % (self.key, repr(self.value)))
        gentext.dump(depth+1, self.truenode)
        gentext.dump(depth+1, self.falsenode)

    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        if ctx.genparams.get(self.key, None) == self.value:
            if self.truenode is not None:
                yield gentext.perform(ctx, propname, self.truenode)
        else:
            if self.falsenode is not None:
                yield gentext.perform(ctx, propname, self.falsenode)

class SwitchKeyNode(GenNodeClass):
    """Select one of a set of subnodes, based on a generation parameter.
    """
    def __init__(self, key, *nodes):
        self.key = key
        self.switch = {}
        self.childlist = []
        self.elsenode = None
        for ix in range(0, len(nodes)-1, 2):
            key = nodes[ix]
            nod = nodes[ix+1]
            self.switch[key] = nod
            self.childlist.append( (key, nod) )
        if (len(nodes) % 2):
            self.elsenode = nodes[-1]
    def dump(self, depth, gentext):
        sys.stdout.write('%s\n' % (self.key,))
        for (key, nod) in self.childlist:
            sys.stdout.write('%s%s' % ('  '*depth, key,))
            gentext.dump(depth+1, nod)
        sys.stdout.write('%s%s' % ('  '*depth, '(else)',))
        gentext.dump(depth+1, self.elsenode)
            
    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        val = ctx.genparams.get(self.key, None)
        if val in self.switch:
            nod = self.switch[val]
            yield gentext.perform(ctx, propname, nod)
        else:
            if self.elsenode:
                yield gentext.perform(ctx, propname, self.elsenode)

class StaticNodeClass(GenNodeClass):
    """Subclass for nodes that just represent themselves, literally,
    in the output stream.

    The precedence field lets us string several together (a STOP
    next to a COMMA, for example) and keep the most severe break.
    """
    precedence = 0
    
    @tornado.gen.coroutine
    def perform(self, ctx, propname, gentext):
        ctx.accum_append(self)
        
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
    # Not generateable (default behavior in non-cooked mode)
    precedence = 0
    pass
    
class RunOnExplicitNode(StaticNodeClass):
    # Generated by _ token; higher priority than WordNode
    precedence = 1
    pass
    
class RunOnCapNode(StaticNodeClass):
    # Not generateable
    pass
    
class ParaNode(StaticNodeClass):
    precedence = 5
    pass

class StopNode(StaticNodeClass):
    precedence = 4
    pass

class SemiNode(StaticNodeClass):
    precedence = 3
    pass

class CommaNode(StaticNodeClass):
    precedence = 2
    pass

bare_node_class_map = {
    '_': RunOnExplicitNode,
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
    'Shuffle': ShuffleNode,
    'Opt': OptNode,
    'Weight': WeightNode,
    'SetKey': SetKeyNode,
    'IfKey': IfKeyNode,
    'SwitchKey': SwitchKeyNode,
    }

ast_NameConstant = object()   # Pre-3.4: create a do-nothing object
if hasattr(ast, 'NameConstant'):
    # Python 3.4 and up: we need a reference to this new node type
    ast_NameConstant = ast.NameConstant

def evalnode(nod, prefix=b''):
    """Convert an ast (syntax tree) node into a GenText node. The result
    may be a native type (int, str, bool, None) or a GenNodeClass object.

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

    if nodtyp is ast_NameConstant:
        return nod.value

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

