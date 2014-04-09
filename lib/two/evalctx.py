"""
The context object for evaluating script code. Most of the implementation
of TworldPy lives in the EvalPropContext module.
"""

import re
import random
import ast
import operator
import itertools

import tornado.gen
import bson
from bson.objectid import ObjectId
import motor

import twcommon.misc
from twcommon.excepts import MessageException, ErrorMessageException
from twcommon.excepts import SymbolError, ExecRunawayException, ExecSandboxException
from twcommon.excepts import ReturnException, LoopBodyException, BreakException, ContinueException
import two.task

# Options for evaluating a thingy -- what kind of thingy is it?
EVALTYPE_SYMBOL = 0 # name of a symbol to look up
EVALTYPE_RAW = 1    # raw value
EVALTYPE_CODE = 2   # string containing code
EVALTYPE_TEXT = 3   # string containing marked-up text
EVALTYPE_GENTEXT = 4 # string containing gentext code

# Bitmask capability flags
EVALCAP_RUN     = 0x01  # do anything at all
EVALCAP_DATAMOD = 0x02  # cause data changes
EVALCAP_MOVE    = 0x04  # move the player
EVALCAP_ALL     = 0x07  # all of above

# Evaluation levels
LEVEL_EXECUTE = 5
LEVEL_DISPSPECIAL = 4
LEVEL_DISPLAY = 3
LEVEL_MESSAGE = 2
LEVEL_FLAT = 1
LEVEL_RAW = 0

# Regexp: Check whether a string starts with a vowel.
re_vowelstart = re.compile('^[aeiou]', re.IGNORECASE)

class EvalPropFrame:
    """One stack frame in the EvalPropContext. Note that depth starts at 1.

    The locals map, if provided, is used "live" (not copied).

    We add a stack frame for every function call, {code} invocation, and
    {text} interpolation. Nested sub-contexts have their own stack
    list, so we don't create a frame in that case, but the sub-context
    parentdepth field will be one higher than our total depth.
    """
    def __init__(self, depth, locals=None):
        self.depth = depth
        if locals is None:
            self.locals = {}
        else:
            self.locals = locals
    def __repr__(self):
        return '<EvalPropFrame depth=%d>' % (self.depth,)

class EvalPropContext(object):
    """EvalPropContext is a context for evaluating one symbol, piece of code,
    or piece of marked-up text, during a task.

    ("EvalPropContext" is a misnomer at this point. The item being evaluated
    may not be a property.)

    When setting up an EvalPropContext you must provide a LocContext, which
    is the identity and location of the player who is the center of the
    action. (Sorry about all the "context"s.) Or you can provide an existing
    EvalPropContext to clone.
    """

    # We'll push contexts on here as we nest them. (It is occasionally
    # necessary to find the "current" context without a handy reference.)
    context_stack = []

    @staticmethod
    def get_current_context():
        if not EvalPropContext.context_stack:
            raise Exception('get_current_context: no current context!')
        return EvalPropContext.context_stack[-1]

    # Used as a long-running counter in build_action_key.
    link_code_counter = 0

    @staticmethod
    def build_action_key():
        """Return a random (hex digit) string which will never repeat.
        Okay, it is vastly unlikely to repeat.
        """
        EvalPropContext.link_code_counter = EvalPropContext.link_code_counter + 1
        return str(EvalPropContext.link_code_counter) + hex(random.getrandbits(32))[2:]
    
    def __init__(self, task, parent=None, loctx=None, parentdepth=0, forbid=None, level=LEVEL_MESSAGE):
        """Caller must provide either parent (an EvalPropContext) or
        a loctx and parentdepth. If there is an effective parent context,
        parentdepth should be ctx.parentdepth+ctx.depth+1. If not, leave
        it as zero.

        The forbid argument is a bitmask of EVALCAPs which this context
        cannot do. The parent's restrictions are also inherited.

        ### A way to pass in argument bindings?
        """
        self.task = task
        self.app = self.task.app

        assert (parent or loctx)
        assert not (parent and loctx)
        
        if parent is not None:
            assert self.task == parent.task
            self.parentdepth = parent.parentdepth + parent.depth + 1
            self.loctx = parent.loctx
            self.uid = parent.uid
            self.caps = parent.caps
        elif loctx is not None:
            self.parentdepth = parentdepth
            self.loctx = loctx
            self.uid = loctx.uid
            self.caps = EVALCAP_ALL

        # What kind of evaluation is going on.
        self.level = level

        # Any caps modifications.
        if forbid:
            self.caps &= (~forbid)
        if level < LEVEL_EXECUTE:
            self.caps &= (~(EVALCAP_DATAMOD|EVALCAP_MOVE))

        # Execution context state.
        self.frame = None
        self.frames = None
        self.accum = None
        self.cooked = False
        self.textstate = RunOnNode

        # Text generation state.
        self.gentexting = False
        self.genseed = None
        self.gencount = None
        self.genparams = None

        # Accumulating the state dependencies and action keys for the
        # client.
        self.linktargets = None
        self.dependencies = None

    @property
    def depth(self):
        """Shortcut implementation of ctx.depth.
        """
        if self.frame:
            assert len(self.frames) == self.frame.depth
        else:
            assert len(self.frames) == 0
        return len(self.frames)
    @depth.setter
    def depth(self, val):
        raise Exception('EvalPropContext.depth is immutable')

    def updateacdepends(self, ctx):
        """Merge in the actions and dependencies from a subcontext.        
        """
        assert self.accum is not None, 'EvalPropContext.accum should not be None here'
        if ctx.linktargets:
            self.linktargets.update(ctx.linktargets)
        if ctx.dependencies:
            self.dependencies.update(ctx.dependencies)

    @tornado.gen.coroutine
    def eval(self, key, evaltype=EVALTYPE_SYMBOL, locals=None):
        """Look up and return a symbol, in this context. If EVALTYPE_TEXT,
        the argument is treated as an already-looked-up {text} value
        (a string with interpolations). If EVALTYPE_CODE, the argument
        is treated as a snippet of {code}. If EVALTYPE_RAW, the argument
        must be a dict object with a meaningful type field.

        The locals (if provided) form the initial locals dict for any
        invoked stack frame. These currently must be symbols beginning
        with underscore. ###generalize for function {code} args?
        The locals dict is used "live", not copied.

        This is the top-level entry point to Doing Stuff in this context.
        
        After the call, dependencies will contain the symbol (and any
        others checked when putting together the result).

        The result type depends on the level:

        RAW: Python object direct from Mongo.
        FLAT: A string. ({text} objects produce strings directly, without
        interpolation or interpretation.)
        MESSAGE: A string. ({text} objects produce strings from the flattened,
        de-styled, de-linked description.)
        DISPLAY: A string or, for {text} objects, a description.
        DISPSPECIAL: A string; for {text}, a description; for other {}
            objects, special client objects. (Used only for focus.)
        EXECUTE: The returned type or, for {text} objects, a description.

        (A description is an array of strings and tag-arrays, JSONable and
        passable to the client.)

        For the {text} case, this also accumulates a set of link-targets
        which are found in links in the description. Dependencies are
        also accumulated.
        """
        self.task.tick()
        if not (self.caps & EVALCAP_RUN):
            raise Exception('EvalPropContext does not have permissions to do anything!')
        
        # Initialize per-invocation fields.
        self.accum = None
        self.cooked = False
        self.textstate = RunOnNode
        self.linktargets = None
        self.dependencies = set()
        self.wasspecial = False

        # These will be filled in if and when a gentext starts.
        self.gentexting = False
        self.genseed = None
        self.gencount = None
        self.genparams = None

        # We start with no frames and a depth of zero. (When we add frames,
        # the self.frame will always be the current stack frame, which is
        # the last entry of self.frames.)
        self.frame = None
        self.frames = []

        try:
            EvalPropContext.context_stack.append(self)
            res = yield self.evalobj(key, evaltype=evaltype, locals=locals)
        finally:
            assert (self.depth == 0) and (self.frame is None), 'EvalPropContext did not pop all the way!'
            assert (EvalPropContext.context_stack[-1] is self), 'EvalPropContext.context_stack did not nest properly!'
            EvalPropContext.context_stack.pop()

        # At this point, if the value was a {text}, the accum will contain
        # the desired description.
        
        if (self.level == LEVEL_RAW):
            return res
        if (self.level == LEVEL_FLAT):
            if twcommon.misc.is_typed_dict(res, 'text'):
                res = res.get('text', '')
            return str_or_null(res)
        if (self.level == LEVEL_MESSAGE):
            if self.accum:
                # Skip all styles, links, etc. Just paste together strings.
                return ''.join([ val for val in self.accum if type(val) is str ]) + str_or_null(res)
            return str_or_null(res)
        if (self.level == LEVEL_DISPLAY):
            if self.accum:
                if not (res is None or res == ''):
                    self.accum.append(str(res))
                optimize_accum(self.accum)
                return self.accum
            return str_or_null(res)
        if (self.level == LEVEL_DISPSPECIAL):
            if self.wasspecial:
                return res
            if self.accum:
                if not (res is None or res == ''):
                    self.accum.append(str(res))
                optimize_accum(self.accum)
                return self.accum
            return str_or_null(res)
        if (self.level == LEVEL_EXECUTE):
            if self.accum:
                if not (res is None or res == ''):
                    self.accum.append(str(res))
                optimize_accum(self.accum)
                return self.accum
            return res
        raise Exception('unrecognized eval level: %d' % (self.level,))
        
    @tornado.gen.coroutine
    def evalobj(self, key, evaltype=EVALTYPE_SYMBOL, symbol=None, locals=None):
        """Look up a symbol, adding it to the accumulated content. If the
        result contains interpolated strings, this calls itself recursively.

        For EVALTYPE_SYMBOL, the key is the symbol (and the symbol argument
        is ignored). For other types, the symbol may be provided as handy
        context.

        Returns an object, or fills out a description array and returns that.
        (The latter only at MESSAGE/DISPLAY/DISPSPECIAL/EXECUTE level.)

        The top-level call to evalobj() may set up the description accumulator
        and linktargets. Lower-level calls use the existing ones.

        A call to here will increment the stack depth *if* it goes into a
        code/text interpolation. For static data values, nothing recursive
        happens and the stack is left alone.
        """
        self.task.tick()
        
        if evaltype == EVALTYPE_SYMBOL:
            symbol = key
            res = yield two.symbols.find_symbol(self.app, self.loctx, key, dependencies=self.dependencies)
        elif evaltype == EVALTYPE_TEXT:
            res = { 'type':'text', 'text':key }
        elif evaltype == EVALTYPE_GENTEXT:
            res = { 'type':'gentext', 'text':key }
        elif evaltype == EVALTYPE_CODE:
            res = { 'type':'code', 'text':key }
        elif evaltype == EVALTYPE_RAW:
            res = key
        else:
            raise Exception('evalobj: unknown evaltype %s' % (evaltype,))

        objtype = None
        if type(res) is dict:
            objtype = res.get('type', None)

        if self.depth == 0 and objtype:
            assert self.accum is None, 'EvalPropContext.accum should be None at depth zero'
            self.accum = []
            self.linktargets = {}
        
        if self.depth == 0 and self.level == LEVEL_DISPSPECIAL and objtype == 'selfdesc':
            assert self.accum is not None, 'EvalPropContext.accum should not be None here'
            try:
                world = yield motor.Op(self.app.mongodb.worlds.find_one,
                                       {'_id':self.loctx.wid},
                                       {'instancing':1})
                if not (world and world.get('instancing', None) == 'solo'):
                    return 'You may only edit your appearance in a solo world.'
                extratext = None
                val = res.get('text', None)
                if val:
                    # Look up the extra text in a separate context.
                    ctx = EvalPropContext(self.task, parent=self, level=LEVEL_DISPLAY)
                    extratext = yield ctx.eval(val, evaltype=EVALTYPE_TEXT)
                    self.updateacdepends(ctx)
                player = yield motor.Op(self.app.mongodb.players.find_one,
                                        {'_id':self.uid},
                                        {'name':1, 'pronoun':1, 'desc':1})
                if not player:
                    return 'There is no such person.'
                specres = ['selfdesc',
                           player.get('name', '???'),
                           player.get('pronoun', 'it'),
                           player.get('desc', '...'),
                           extratext]
                self.wasspecial = True
                return specres
            except Exception as ex:
                self.task.log.warning('Caught exception (selfdesc): %s', ex, exc_info=self.app.debugstacktraces)
                return '[Exception: %s]' % (ex,)
                
        if self.depth == 0 and self.level == LEVEL_DISPSPECIAL and objtype == 'editstr':
            assert self.accum is not None, 'EvalPropContext.accum should not be None here'
            try:
                if 'key' not in res:
                    raise Exception('No key given for editstr.')
                level = yield two.execute.scope_access_level(self.app, self.uid, self.loctx.wid, self.loctx.scid)
                if level < res.get('editaccess', ACC_MEMBER):
                    return self.app.localize('message.widget_no_access')
                extratext = None
                val = res.get('label', None)
                if val:
                    # Look up the extra text in a separate context.
                    ctx = EvalPropContext(self.task, parent=self, level=LEVEL_DISPLAY)
                    extratext = yield ctx.eval(val, evaltype=EVALTYPE_TEXT)
                    self.updateacdepends(ctx)
                # Look up the current symbol value.
                editkey = 'editstr' + EvalPropContext.build_action_key()
                self.linktargets[editkey] = ('editstr', res['key'], res.get('text', None), res.get('otext', None))
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_FLAT)
                curvalue = yield ctx.eval(res['key'])
                specres = ['editstr',
                           editkey,
                           curvalue,
                           extratext]
                self.wasspecial = True
                return specres
            except Exception as ex:
                self.task.log.warning('Caught exception (editstr): %s', ex, exc_info=self.app.debugstacktraces)
                return '[Exception: %s]' % (ex,)

        if not(objtype in ('text', 'gentext', 'code')
               and self.level in (LEVEL_MESSAGE, LEVEL_DISPLAY, LEVEL_DISPSPECIAL, LEVEL_EXECUTE)):
            # For most cases, the type returned by the database is the
            # type we want.
            return res

        # But at MESSAGE/DISPLAY/EXEC level, a {text} object is parsed out;
        # a {code} object is executed. Note that read-only code can be
        # executed at lower levels; even local-var assignments would be
        # okay. EXEC is only necessary for changing the world (db) state,
        # or triggering panics/events/etc.

        assert self.accum is not None, 'EvalPropContext.accum should not be None here'
        if objtype == 'text':
            # We prefer to catch interpolation errors as low as possible,
            # so that they will appear inline in a logical spot.
            try:
                origframe = self.frame  # may be None
                self.frame = EvalPropFrame(self.depth+1, locals=locals)
                self.frames.append(self.frame)
                if self.parentdepth+self.depth > self.task.STACK_DEPTH_LIMIT:
                    self.task.log.error('ExecRunawayException: User script exceeded depth limit!')
                    raise ExecRunawayException('Script ran too deep; aborting!')
                yield self.interpolate_text(res.get('text', ''))
                return None
            except LoopBodyException as ex:
                raise Exception('"%s" outside loop' % (ex.statement,))
            except ReturnException as ex:
                return ex.returnvalue
            except ExecRunawayException:
                raise  # Let this through
            except Exception as ex:
                self.task.log.warning('Caught exception (interpolating): %s', ex, exc_info=self.app.debugstacktraces)
                return '[Exception: %s]' % (ex,)
            finally:
                self.frames.pop()
                self.frame = origframe
        elif objtype == 'gentext':
            # We prefer to catch interpolation errors as low as possible,
            # so that they will appear inline in a logical spot.
            try:
                origframe = self.frame  # may be None
                self.frame = EvalPropFrame(self.depth+1, locals=locals)
                self.frames.append(self.frame)
                if self.parentdepth+self.depth > self.task.STACK_DEPTH_LIMIT:
                    self.task.log.error('ExecRunawayException: User script exceeded depth limit!')
                    raise ExecRunawayException('Script ran too deep; aborting!')
                if symbol is None:
                    # We may be able to identify the object's property name
                    # from the propcache.
                    ent = self.app.propcache.get_by_object(res)
                    if ent:
                        symbol = ent.key
                if symbol is None:
                    raise Exception('Temporary variable cannot generate text')
                if self.genseed is None:
                    try:
                        self.genseed = str(self.loctx.iid).encode()
                    except:
                        self.genseed = b'???'
                tree = twcommon.gentext.parse(res.get('text', ''))
                toplevel = (not self.gentexting)
                if toplevel:
                    tree.setup_context(self)
                try:
                    yield tree.perform(self, symbol.encode())
                finally:
                    if toplevel:
                        tree.final_context(self)
                return None
            except LoopBodyException as ex:
                raise Exception('"%s" outside loop' % (ex.statement,))
            except ReturnException as ex:
                return ex.returnvalue
            except ExecRunawayException:
                raise  # Let this through
            except Exception as ex:
                self.task.log.warning('Caught exception (text-generating): %s', ex, exc_info=self.app.debugstacktraces)
                return '[Exception: %s]' % (ex,)
            finally:
                self.frames.pop()
                self.frame = origframe
        elif objtype == 'code':
            # We let execution errors bubble up to the top level.
            try:
                origframe = self.frame  # may be None
                self.frame = EvalPropFrame(self.depth+1, locals=locals)
                self.frames.append(self.frame)
                if self.parentdepth+self.depth > self.task.STACK_DEPTH_LIMIT:
                    self.task.log.error('ExecRunawayException: User script exceeded depth limit!')
                    raise ExecRunawayException('Script ran too deep; aborting!')
                newres = yield self.execute_code(res.get('text', ''), originlabel=key)
                return newres
            except LoopBodyException as ex:
                raise Exception('"%s" outside loop' % (ex.statement,))
            except ReturnException as ex:
                return ex.returnvalue
            finally:
                self.frames.pop()
                self.frame = origframe
        else:
            return '[Unhandled object type: %s]' % (objtype,)

    @tornado.gen.coroutine
    def execute_code(self, text, originlabel=None):
        """Execute a pile of (already-looked-up) script code.
        """
        self.task.tick()

        ### This originlabel stuff is pretty much wrong. Also slow.
        ### And unnecessary, now that the build interface test-parses?
        if originlabel:
            if type(originlabel) is dict and 'text' in originlabel:
                originlabel = originlabel['text']
            originlabel = '"%.20s"' % (originlabel,)
        else:
            originlabel = '<script>'
            
        tree = ast.parse(text, filename=originlabel)
        assert type(tree) is ast.Module

        res = None
        for nod in tree.body:
            res = yield self.execcode_statement(nod)
        return res

    @tornado.gen.coroutine
    def execcode_statement(self, nod):
        self.task.tick()
        nodtyp = type(nod)
        if nodtyp is ast.Expr:
            res = yield self.execcode_expr(nod.value)
            if res is not None and type(res) is dict and 'type' in res:
                # Top-level expression has returned a typed dict. Try
                # invoking it.
                symbol = None
                if type(nod.value) is ast.Name:
                    symbol = nod.value.id
                res = yield self.invoke_typed_dict(res, symbol)
                return res
            return res
        # Use lookup table for most cases. The lookup table winds up containing
        # unbound method handlers, so we need to pass self.
        han = self.execcode_statement_handlers.get(nodtyp, None)
        if han:
            res = yield han(self, nod)
            return res
        if nodtyp is ast.Pass:
            return None
        raise NotImplementedError('Script statement type not implemented: %s' % (nodtyp.__name__,))

    @tornado.gen.coroutine
    def execcode_expr_store(self, nod):
        """Does not evaluate a complete expression. Instead, returns a
        wrapper object with load(), store(), and delete() methods.
        (The load() accessor supports augment "x += 1" operations.)
        (The nod.ctx lets us know whether store/augment or delete is
        coming up; but the way our proxies work, we don't much care.)
        """
        assert type(nod.ctx) is not ast.Load, 'target of assignment has Load context'
        nodtyp = type(nod)
        if nodtyp is ast.Name:
            return two.execute.BoundNameProxy(nod.id)
        if nodtyp is ast.Attribute:
            argument = yield self.execcode_expr(nod.value)
            key = nod.attr
            if isinstance(argument, two.execute.PropertyProxyMixin):
                return two.execute.BoundPropertyProxy(argument, key)
            raise ExecSandboxException('%s.%s: setattr not allowed' % (type(argument).__name__, key))
        if nodtyp is ast.Subscript:
            argument = yield self.execcode_expr(nod.value)
            subnod = nod.slice
            subtyp = type(subnod)
            if subtyp is ast.Index:
                subscript = yield self.execcode_expr(subnod.value)
            elif subtyp is ast.Slice:
                lower = None
                if subnod.lower is not None:
                    lower = yield self.execcode_expr(subnod.lower)
                upper = None
                if subnod.upper is not None:
                    upper = yield self.execcode_expr(subnod.upper)
                if subnod.step is None:
                    subscript = slice(lower, upper)
                else:
                    step = yield self.execcode_expr(subnod.step)
                    subscript = slice(lower, upper, step)
            else:
                raise NotImplementedError('Unsupported subscript type: %s' % (subtyp.__name__,))
            if isinstance(argument, two.execute.PropertyProxyMixin):
                # Special case: property proxies can be accessed by subscript.
                return two.execute.BoundPropertyProxy(argument, subscript)
            return two.execute.BoundSubscriptProxy(argument, subscript)
        if nodtyp in (ast.Tuple, ast.List):
            ls = []
            for subnod in nod.elts:
                val = yield self.execcode_expr_store(subnod)
                ls.append(val)
            return two.execute.MultiBoundProxy(ls)
        raise NotImplementedError('Script store-expression type not implemented: %s' % (nodtyp.__name__,))
        
        
    @tornado.gen.coroutine
    def execcode_expr(self, nod):
        self.task.tick()
        nodtyp = type(nod)
        if nodtyp is ast.Str:
            return nod.s
        if nodtyp is ast.Num:
            return nod.n  # covers floats and ints
        # Use lookup table for most cases. The lookup table winds up containing
        # unbound method handlers, so we need to pass self.
        han = self.execcode_expr_handlers.get(nodtyp, None)
        if han:
            res = yield han(self, nod)
            return res
        raise NotImplementedError('Script expression type not implemented: %s' % (nodtyp.__name__,))

    @tornado.gen.coroutine
    def execcode_list(self, nod):
        ls = []
        for subnod in nod.elts:
            val = yield self.execcode_expr(subnod)
            ls.append(val)
        return ls

    @tornado.gen.coroutine
    def execcode_tuple(self, nod):
        ls = []
        for subnod in nod.elts:
            val = yield self.execcode_expr(subnod)
            ls.append(val)
        return tuple(ls)

    @tornado.gen.coroutine
    def execcode_set(self, nod):
        ls = []
        for subnod in nod.elts:
            val = yield self.execcode_expr(subnod)
            ls.append(val)
        return set(ls)

    @tornado.gen.coroutine
    def execcode_dict(self, nod):
        keyls = []
        for subnod in nod.keys:
            val = yield self.execcode_expr(subnod)
            keyls.append(val)
        valls = []
        for subnod in nod.values:
            val = yield self.execcode_expr(subnod)
            valls.append(val)
        return dict(zip(keyls, valls))

    map_unaryop_operators = {
        ast.Not: operator.not_,
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
        }
        
    @tornado.gen.coroutine
    def execcode_unaryop(self, nod):
        optyp = type(nod.op)
        argval = yield self.execcode_expr(nod.operand)
        opfunc = self.map_unaryop_operators.get(optyp, None)
        if not opfunc:
            raise NotImplementedError('Script unaryop type not implemented: %s' % (optyp.__name__,))
        return opfunc(argval)

    # These operators are actually polymorphic. Add includes concat,
    # mod includes string-format, and so on.
    map_binop_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.FloorDiv: operator.floordiv,
        ast.BitAnd: operator.and_,
        ast.BitOr: operator.or_,
        ast.BitXor: operator.xor,
        ast.LShift: operator.lshift,
        ast.RShift: operator.rshift,
        }
        
    @tornado.gen.coroutine
    def execcode_binop(self, nod):
        optyp = type(nod.op)
        leftval = yield self.execcode_expr(nod.left)
        rightval = yield self.execcode_expr(nod.right)
        opfunc = self.map_binop_operators.get(optyp, None)
        if not opfunc:
            raise NotImplementedError('Script binop type not implemented: %s' % (optyp.__name__,))
        return opfunc(leftval, rightval)
        
    @tornado.gen.coroutine
    def execcode_boolop(self, nod):
        optyp = type(nod.op)
        assert len(nod.values) > 0
        if optyp is ast.And:
            for subnod in nod.values:
                val = yield self.execcode_expr(subnod)
                if not val:
                    return val
            return val
        if optyp is ast.Or:
            for subnod in nod.values:
                val = yield self.execcode_expr(subnod)
                if val:
                    return val
            return val
        raise NotImplementedError('Script boolop type not implemented: %s' % (optyp.__name__,))

    map_compare_operators = {
        ast.Is: operator.is_,
        ast.IsNot: operator.is_not,
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        # We don't use operator.contains, because its arguments are reversed
        # for some forsaken reason.
        ast.In: lambda x,y:(x in y),
        ast.NotIn: lambda x,y:(x not in y),
        }
    
    @tornado.gen.coroutine
    def execcode_compare(self, nod):
        leftval = yield self.execcode_expr(nod.left)
        for (op, subnod) in zip(nod.ops, nod.comparators):
            rightval = yield self.execcode_expr(subnod)
            optyp = type(op)
            opfunc = self.map_compare_operators.get(optyp, None)
            if not opfunc:
                raise NotImplementedError('Script compare type not implemented: %s' % (optyp.__name__,))
            res = opfunc(leftval, rightval)
            if not res:
                return res
            leftval = rightval
        return True

    @tornado.gen.coroutine
    def execcode_ifexp(self, nod):
        val = yield self.execcode_expr(nod.test)
        if val:
            res = yield self.execcode_expr(nod.body)
        else:
            res = yield self.execcode_expr(nod.orelse)
        return res
    
    @tornado.gen.coroutine
    def execcode_listcomp(self, nod):
        targets = []
        iters = []
        ifss = []
        for comp in nod.generators:
            target = yield self.execcode_expr_store(comp.target)
            iter = yield self.execcode_expr(comp.iter)
            ifs = comp.ifs
            targets.append(target)
            iters.append(iter)
            ifss.append(ifs)
        res = []
        for tup in itertools.product(*iters):
            flag = True
            for target, val, ifs in zip(targets, tup, ifss):
                yield target.store(self, self.loctx, val)
                for ifnod in ifs:
                    flag = yield self.execcode_expr(ifnod)
                    if not flag:
                        break
                if not flag:
                    break
            if flag:
                val = yield self.execcode_expr(nod.elt)
                res.append(val)
        return res
        
    @tornado.gen.coroutine
    def execcode_setcomp(self, nod):
        targets = []
        iters = []
        ifss = []
        for comp in nod.generators:
            target = yield self.execcode_expr_store(comp.target)
            iter = yield self.execcode_expr(comp.iter)
            ifs = comp.ifs
            targets.append(target)
            iters.append(iter)
            ifss.append(ifs)
        res = set()
        for tup in itertools.product(*iters):
            flag = True
            for target, val, ifs in zip(targets, tup, ifss):
                yield target.store(self, self.loctx, val)
                for ifnod in ifs:
                    flag = yield self.execcode_expr(ifnod)
                    if not flag:
                        break
                if not flag:
                    break
            if flag:
                val = yield self.execcode_expr(nod.elt)
                res.add(val)
        return res
        
    @tornado.gen.coroutine
    def execcode_dictcomp(self, nod):
        targets = []
        iters = []
        ifss = []
        for comp in nod.generators:
            target = yield self.execcode_expr_store(comp.target)
            iter = yield self.execcode_expr(comp.iter)
            ifs = comp.ifs
            targets.append(target)
            iters.append(iter)
            ifss.append(ifs)
        res = {}
        for tup in itertools.product(*iters):
            flag = True
            for target, val, ifs in zip(targets, tup, ifss):
                yield target.store(self, self.loctx, val)
                for ifnod in ifs:
                    flag = yield self.execcode_expr(ifnod)
                    if not flag:
                        break
                if not flag:
                    break
            if flag:
                keyval = yield self.execcode_expr(nod.key)
                valueval = yield self.execcode_expr(nod.value)
                res[keyval] = valueval
        return res
        
    @tornado.gen.coroutine
    def execcode_attribute(self, nod):
        argument = yield self.execcode_expr(nod.value)
        key = nod.attr
        # The real getattr() is way too powerful to offer up.
        if isinstance(argument, two.symbols.ScriptNamespace):
            (res, yieldy) = argument.getyieldy(key)
            if yieldy:
                res = yield res()
            return res
        if isinstance(argument, two.execute.PropertyProxyMixin):
            res = yield argument.getprop(self, self.loctx, key)
            return res
        return two.symbols.type_getattr_perform(self.app, argument, key)

    @tornado.gen.coroutine
    def execcode_subscript(self, nod):
        argument = yield self.execcode_expr(nod.value)
        subnod = nod.slice
        subtyp = type(subnod)
        if subtyp is ast.Index:
            subscript = yield self.execcode_expr(subnod.value)
        elif subtyp is ast.Slice:
            lower = None
            if subnod.lower is not None:
                lower = yield self.execcode_expr(subnod.lower)
            upper = None
            if subnod.upper is not None:
                upper = yield self.execcode_expr(subnod.upper)
            if subnod.step is None:
                subscript = slice(lower, upper)
            else:
                step = yield self.execcode_expr(subnod.step)
                subscript = slice(lower, upper, step)
        else:
            raise NotImplementedError('Unsupported subscript type: %s' % (subtyp.__name__,))
        if isinstance(argument, two.execute.PropertyProxyMixin):
            # Special case: property proxies can be accessed by subscript.
            res = yield argument.getprop(self, self.loctx, subscript)
            return res
        return argument[subscript]

    @tornado.gen.coroutine
    def execcode_call(self, nod):
        funcval = yield self.execcode_expr(nod.func)
        args = []
        for subnod in nod.args:
            val = yield self.execcode_expr(subnod)
            args.append(val)
        if nod.starargs:
            starargs = yield self.execcode_expr(nod.starargs)
            args.extend(starargs)
        kwargs = {}
        for subnod in nod.keywords:
            val = yield self.execcode_expr(subnod.value)
            kwargs[subnod.arg] = val
        if nod.kwargs:
            starargs = yield self.execcode_expr(nod.kwargs)
            # Python semantics say we should reject duplicate kwargs here
            kwargs.update(starargs)
            
        if isinstance(funcval, two.symbols.ScriptCallable):
            if not funcval.yieldy:
                return funcval.func(*args, **kwargs)
            else:
                res = yield funcval.yieldfunc(*args, **kwargs)
                return res
        if funcval and twcommon.misc.is_typed_dict(funcval, 'code'):
            # {code} dicts are considered callable by courtesy.
            argspec = funcval.get('args', None)
            if not argspec:
                locals = None
                if args or kwargs:
                    raise TypeError('code property does not take arguments, but was given %d' % (len(args)+len(kwargs),))
            else:
                argspec = parse_argument_spec(argspec)
                yield self.replace_argspec_defaults(argspec)
                locals = resolve_argument_spec(argspec, args, kwargs)
            val = funcval.get('text', None)
            if not val:
                return None
            newval = yield self.evalobj(val, evaltype=EVALTYPE_CODE, locals=locals)
            return newval
        if not two.symbols.type_callable(funcval):
            raise TypeError('%s is not callable' % (type(funcval).__name__))
        return funcval(*args, **kwargs)
    
    @tornado.gen.coroutine
    def exec_call_object(self, funcval, args, kwargs):
        # This is the object-calling code above, broken out into a separate
        # function. Some built-in functions need this.
        # (We could factor out the above code into a call here, but I
        # begrudge the minuscule speed cost.)
        if isinstance(funcval, two.symbols.ScriptCallable):
            if not funcval.yieldy:
                return funcval.func(*args, **kwargs)
            else:
                res = yield funcval.yieldfunc(*args, **kwargs)
                return res
        if funcval and twcommon.misc.is_typed_dict(funcval, 'code'):
            # {code} dicts are considered callable by courtesy.
            argspec = funcval.get('args', None)
            if not argspec:
                locals = None
                if args or kwargs:
                    raise TypeError('code property does not take arguments, but was given %d' % (len(args)+len(kwargs),))
            else:
                argspec = parse_argument_spec(argspec)
                yield self.replace_argspec_defaults(argspec)
                locals = resolve_argument_spec(argspec, args, kwargs)
            val = funcval.get('text', None)
            if not val:
                return None
            newval = yield self.evalobj(val, evaltype=EVALTYPE_CODE, locals=locals)
            return newval
        if not two.symbols.type_callable(funcval):
            raise TypeError('%s is not callable' % (type(funcval).__name__))
        return funcval(*args, **kwargs)
        
    @tornado.gen.coroutine
    def execcode_name(self, nod):
        symbol = nod.id
        res = yield two.symbols.find_symbol(self.app, self.loctx, symbol, locals=self.frame.locals, dependencies=self.dependencies)
        return res

    @tornado.gen.coroutine
    def execcode_nameconstant(self, nod):
        # Python 3.4 and later
        return nod.value

    @tornado.gen.coroutine
    def execcode_if(self, nod):
        testval = yield self.execcode_expr(nod.test)
        if testval:
            body = nod.body
        else:
            body = nod.orelse
        res = None
        for nod in body:
            res = yield self.execcode_statement(nod)
        return res
        
    @tornado.gen.coroutine
    def execcode_while(self, nod):
        while True:
            testval = yield self.execcode_expr(nod.test)
            if not testval:
                break
            try:
                for subnod in nod.body:
                    res = yield self.execcode_statement(subnod)
            except ContinueException:
                pass
            except BreakException:
                return
        for subnod in nod.orelse:
            res = yield self.execcode_statement(subnod)
        
    @tornado.gen.coroutine
    def execcode_for(self, nod):
        target = yield self.execcode_expr_store(nod.target)
        iter = yield self.execcode_expr(nod.iter)
        for val in iter:
            yield target.store(self, self.loctx, val)
            try:
                for subnod in nod.body:
                    res = yield self.execcode_statement(subnod)
            except ContinueException:
                pass
            except BreakException:
                return
        for subnod in nod.orelse:
            res = yield self.execcode_statement(subnod)
        
    @tornado.gen.coroutine
    def execcode_return(self, nod):
        if nod.value is None:
            val = None
        else:
            val = yield self.execcode_expr(nod.value)
        raise ReturnException(returnvalue=val)
        
    @tornado.gen.coroutine
    def execcode_break(self, nod):
        raise BreakException
        
    @tornado.gen.coroutine
    def execcode_continue(self, nod):
        raise ContinueException
        
    @tornado.gen.coroutine
    def execcode_assign(self, nod):
        val = yield self.execcode_expr(nod.value)
        for tarnod in nod.targets:
            target = yield self.execcode_expr_store(tarnod)
            yield target.store(self, self.loctx, val)
        return None

    @tornado.gen.coroutine
    def execcode_augassign(self, nod):
        optyp = type(nod.op)
        opfunc = self.map_binop_operators.get(optyp, None)
        if not opfunc:
            raise NotImplementedError('Script augop type not implemented: %s' % (optyp.__name__,))
        target = yield self.execcode_expr_store(nod.target)
        rightval = yield self.execcode_expr(nod.value)

        leftval = yield target.load(self, self.loctx)
        val = opfunc(leftval, rightval)
        
        yield target.store(self, self.loctx, val)
        return None

    @tornado.gen.coroutine
    def execcode_delete(self, nod):
        for subnod in nod.targets:
            target = yield self.execcode_expr_store(subnod)
            yield target.delete(self, self.loctx)
        return None

    # Some lookup tables of node handlers
    execcode_expr_handlers = {
        ast.Name: execcode_name,
        ast.List: execcode_list,
        ast.Tuple: execcode_tuple,
        ast.Set: execcode_set,
        ast.Dict: execcode_dict,
        ast.UnaryOp: execcode_unaryop,
        ast.BinOp: execcode_binop,
        ast.BoolOp: execcode_boolop,
        ast.Compare: execcode_compare,
        ast.IfExp: execcode_ifexp,
        ast.ListComp: execcode_listcomp,
        ast.SetComp: execcode_setcomp,
        ast.DictComp: execcode_dictcomp,
        ast.Attribute: execcode_attribute,
        ast.Subscript: execcode_subscript,
        ast.Call: execcode_call,
        }
    if (hasattr(ast, 'NameConstant')):
        # Only exists in Python 3.4 and up
        execcode_expr_handlers[ast.NameConstant] = execcode_nameconstant

    execcode_statement_handlers = {
        ast.Assign: execcode_assign,
        ast.AugAssign: execcode_augassign,
        ast.Delete: execcode_delete,
        ast.If: execcode_if,
        ast.While: execcode_while,
        ast.For: execcode_for,
        ast.Return: execcode_return,
        ast.Break: execcode_break,
        ast.Continue: execcode_continue,
        }

    @tornado.gen.coroutine
    def replace_argspec_defaults(self, argspec):
        if argspec.defaults:
            ls = []
            for val in argspec.defaults:
                newval = yield self.execcode_expr(val)
                ls.append(newval)
            argspec.defaults = ls
        if argspec.kw_defaults:
            ls = []
            for val in argspec.kw_defaults:
                newval = yield self.execcode_expr(val)
                ls.append(newval)
            argspec.kw_defaults = ls
        return
        
    @tornado.gen.coroutine
    def invoke_typed_dict(self, res, symbol=None):
        restype = res.get('type', None)
        uid = self.uid

        if self.level != LEVEL_EXECUTE:
            # If we're not in an action, we invoke text/code snippets.
            if restype == 'text':
                val = res.get('text', None)
                if not val:
                    return ''
                newval = yield self.evalobj(val, evaltype=EVALTYPE_TEXT, symbol=symbol)
                return newval
            if restype == 'gentext':
                val = res.get('text', None)
                if not val:
                    return ''
                newval = yield self.evalobj(val, evaltype=EVALTYPE_GENTEXT, symbol=symbol)
                return newval
            if restype == 'code':
                argspec = res.get('args', None)
                if not argspec:
                    locals = None
                else:
                    argspec = parse_argument_spec(argspec)
                    yield self.replace_argspec_defaults(argspec)
                    locals = resolve_argument_spec(argspec, [], {})
                val = res.get('text', None)
                if not val:
                    return None
                newval = yield self.evalobj(val, evaltype=EVALTYPE_CODE, locals=locals, symbol=symbol)
                return newval
            # All other special objects are returned as-is.
            return res
        
        if restype in ('text', 'gentext', 'selfdesc', 'editstr'):
            # Set focus to this symbol-name
            if not symbol:
                raise ErrorMessageException('typed dict (%s) cannot be focussed; not a bare symbol' % (restype,))
            yield motor.Op(self.app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':symbol}})
            self.task.set_dirty(uid, DIRTY_FOCUS)
            return None

        if restype == 'portlist':
            # Set focus to an ugly special-case array
            ### We should get the symbol name into the focus dependencies!
            plistkey = res.get('plistkey', None)
            if not plistkey:
                raise ErrorMessageException('portlist property has no plistkey')
            plist = yield motor.Op(self.app.mongodb.portlists.find_one,
                                   {'wid':self.loctx.wid, 'key':plistkey, 'type':'world'},
                                   {'_id':1})
            if not plist:
                raise ErrorMessageException('portlist not found: %s' % (plistkey,))
            plistid = plist['_id']
            
            level = yield two.execute.scope_access_level(self.app, self.uid, self.loctx.wid, self.loctx.scid)
            if level < res.get('readaccess', ACC_VISITOR):
                raise MessageException(self.app.localize('message.widget_no_access'))
            editable = (level >= res.get('editaccess', ACC_MEMBER))
            extratext = res.get('text', None)

            focusportid = None
            if res.get('focus', False):
                focusport = yield motor.Op(self.app.mongodb.portals.find_one,
                                           {'plistid':plistid, 'iid':None},
                                           {'_id':1})
                if focusport:
                    focusportid = focusport['_id']
            withback = (focusportid is None)
            arr = ['portlist', plistid, editable, extratext, withback, focusportid]
            yield motor.Op(self.app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':arr}})
            self.task.set_dirty(uid, DIRTY_FOCUS)
            return None

        if restype == 'code':
            argspec = res.get('args', None)
            if not argspec:
                locals = None
            else:
                argspec = parse_argument_spec(argspec)
                yield self.replace_argspec_defaults(argspec)
                locals = resolve_argument_spec(argspec, [], {})
            val = res.get('text', None)
            if not val:
                return None
            newval = yield self.evalobj(val, evaltype=EVALTYPE_CODE, locals=locals)
            return newval

        if restype == 'event':
            # Display an event.
            yield self.perform_event(res.get('text', None), True, res.get('otext', None), True)
            return None

        if restype == 'panic':
            # Panic the player out.
            yield self.perform_panic(res.get('text', None), True, res.get('otext', None), True)
            return None

        if restype == 'move':
            # Move the player.
            lockey = res.get('loc', None)
            if not lockey:
                raise Exception('Move has no location')
            location = yield motor.Op(self.app.mongodb.locations.find_one,
                                      {'wid':self.loctx.wid, 'key':lockey},
                                      {'_id':1})
            if not location:
                raise KeyError('No such location: %s' % (lockey,))

            yield self.perform_move(location['_id'], res.get('text', None), True, res.get('oleave', None), True, res.get('oarrive', None), True)
            return None

        raise ErrorMessageException('Code invoked unsupported property type: %s' % (restype,))

    @tornado.gen.coroutine
    def interpolate_text(self, text):
        """Evaluate a bunch of (already-looked-up) interpolation markup.
        """
        self.task.tick()
        
        nodls = twcommon.interp.parse(text)
        
        # While trawling through nodls, we may encounter $if/$end
        # nodes. This keeps track of them. Specifically: a 0 value
        # means "within a true conditional"; 1 means "within a
        # false conditional"; 2 means "in an else/elif after a true
        # conditional."
        suppstack = []
        # We suppress output if any value in suppstack is nonzero.
        # It's easiest to track sum(suppstack), so that's what this is.
        suppressed = 0
        
        for nod in nodls:
            if not (isinstance(nod, InterpNode)):
                # String.
                if nod and not suppressed:
                    self.accum_append(nod, raw=True)
                continue
            
            nodkey = nod.classname
            # This switch statement might be better off as a method
            # lookup table. But only if it gets long.

            if nodkey == 'If':
                if suppressed:
                    # Can't get any more suppressed.
                    suppstack.append(0)
                    continue
                try:
                    ifval = yield self.evalobj(nod.expr, evaltype=EVALTYPE_CODE)
                except LookupError: # includes SymbolError
                    ifval = None
                except AttributeError:
                    ifval = None
                if ifval:
                    suppstack.append(0)
                else:
                    suppstack.append(1)
                    suppressed += 1
                continue
                    
            if nodkey == 'ElIf':
                if len(suppstack) == 0:
                    self.accum_append('[$elif without matching $if]')
                    continue
                if not suppressed:
                    # We follow a successful "if". Suppress now.
                    suppstack[-1] = 2
                    suppressed = sum(suppstack)
                    continue
                if suppstack[-1] == 2:
                    # We had a successful "if" earlier, so no change.
                    continue
                # We follow an unsuccessful "if". Maybe suppress.
                try:
                    ifval = yield self.evalobj(nod.expr, evaltype=EVALTYPE_CODE)
                except LookupError: # includes SymbolError
                    ifval = None
                except AttributeError:
                    ifval = None
                if ifval:
                    suppstack[-1] = 0
                else:
                    suppstack[-1] = 1
                suppressed = sum(suppstack)
                continue
                    
            if nodkey == 'End':
                if len(suppstack) == 0:
                    self.accum_append('[$end without matching $if]')
                    continue
                suppstack.pop()
                suppressed = sum(suppstack)
                continue

            if nodkey == 'Else':
                if len(suppstack) == 0:
                    self.accum_append('[$else without matching $if]')
                    continue
                val = suppstack[-1]
                if val == 1:
                    val = 0
                else:
                    val = 2
                suppstack[-1] = val
                suppressed = sum(suppstack)
                continue

            # The rest of these nodes cannot affect the suppression
            # state.
            if suppressed:
                continue
            
            if nodkey == 'Link':
                # Non-printing element, append directly
                if not nod.external:
                    ackey = EvalPropContext.build_action_key()
                    self.linktargets[ackey] = nod.target
                    self.accum.append( ['link', ackey] )
                else:
                    self.accum.append( ['exlink', nod.target] )
                continue
            
            if nodkey == 'Interpolate':
                try:
                    subres = yield self.evalobj(nod.expr, evaltype=EVALTYPE_CODE)
                except LookupError: # includes SymbolError:
                    continue
                except AttributeError:
                    continue
                # {text} objects have already added their contents to
                # the accum array.
                if not (subres is None or subres == ''):
                    # Anything not a {text} object gets interpolated as
                    # a string.
                    self.accum_append(str(subres), raw=True)
                continue
            
            if nodkey == 'PlayerRef':
                if nod.expr:
                    uid = yield self.evalobj(nod.expr, evaltype=EVALTYPE_CODE)
                    if isinstance(uid, two.execute.PlayerProxy):
                        uid = uid.uid
                    else:
                        uid = ObjectId(uid)
                else:
                    uid = self.uid
                    
                player = yield motor.Op(self.app.mongodb.players.find_one,
                                        {'_id':uid},
                                        {'name':1, 'pronoun':1})
                if not player:
                    self.accum.append('[No such player]')
                    continue
                if nod.key == 'name':
                    self.accum_append(player['name'], raw=True)
                else:
                    self.accum_append(two.grammar.resolve_pronoun(player, nod.key), raw=True)
                continue

            if nodkey == 'OpenBracket':
                self.accum_append('[', raw=True)
                continue

            if nodkey == 'CloseBracket':
                self.accum_append(']', raw=True)
                continue

            # Otherwise...
            # Non-printing element, append directly
            self.accum.append(nod.describe())

        # End of nodls interaction.
        if len(suppstack) > 0:
            self.accum.append('[$if without matching $end]')
            
        # We used raw mode, but if the ctx is in cooked mode, we'll fake
        # in WordNode state at the end.
        if self.cooked and self.textstate is twcommon.gentext.RunOnNode:
            self.textstate = twcommon.gentext.WordNode

    @tornado.gen.coroutine
    def perform_event(self, text, texteval, otext, otexteval):
        if self.level != LEVEL_EXECUTE:
            raise Exception('Events may only occur in action code')
        if text:
            if texteval:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                val = yield ctx.eval(text, evaltype=EVALTYPE_TEXT)
            else:
                val = text
            self.task.write_event(self.uid, val)
        if otext:
            others = yield self.task.find_locale_players(notself=True)
            if otexteval:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                val = yield ctx.eval(otext, evaltype=EVALTYPE_TEXT)
            else:
                val = otext
            self.task.write_event(others, val)

    @tornado.gen.coroutine
    def perform_event_player(self, uid, text, texteval, otext, otexteval):
        if self.level != LEVEL_EXECUTE:
            raise Exception('Events may only occur in action code')
        if text:
            if texteval:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                val = yield ctx.eval(text, evaltype=EVALTYPE_TEXT)
            else:
                val = text
            self.task.write_event(uid, val)
        if otext:
            others = yield self.task.find_locale_players(uid=uid, notself=True)
            if otexteval:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                val = yield ctx.eval(otext, evaltype=EVALTYPE_TEXT)
            else:
                val = otext
            self.task.write_event(others, val)

    @tornado.gen.coroutine
    def perform_panic(self, text, texteval, otext, otexteval, player=None):
        if self.level != LEVEL_EXECUTE:
            raise Exception('Panics may only occur in action code')
        if not (self.caps & EVALCAP_MOVE):
            raise Exception('Panics not permitted in this code')

        if player is None:
            playeruid = self.uid
        else:
            playeruid = player.uid
            
        player = yield motor.Op(self.app.mongodb.players.find_one,
                                {'_id':playeruid},
                                {'name':1})
        if not player:
            raise Exception('No such player')
        playername = player['name']

        playstate = yield motor.Op(self.app.mongodb.playstate.find_one,
                                   {'_id':playeruid})
        if playstate['iid'] != self.loctx.iid:
            raise Exception('Player is not in the current instance')

        # We must now construct a loctx for the moving player.
        if playeruid == self.uid:
            # The simple (old-fashioned) case.
            loctx = self.loctx
        else:
            # We know the player is in our instance, so this is not
            # too bad.
            loctx = two.task.LocContext(
                playeruid, wid=self.loctx.wid, scid=self.loctx.scid,
                iid=playstate['iid'], locid=playstate['locid'])

        msg = text
        if msg:
            if texteval:
                ctx = EvalPropContext(self.task, loctx=loctx, level=LEVEL_MESSAGE)
                msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
            self.task.write_event(playeruid, msg)

        msg = otext
        if msg is None:
            pass
        elif otexteval:
            ctx = EvalPropContext(self.task, loctx=loctx, level=LEVEL_MESSAGE)
            msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
        if msg:
            others = yield self.task.find_locale_players(uid=playeruid, notself=True)
            if others:
                self.task.write_event(others, msg)

        # Send them off. (The tovoid handles hooks.)
        self.app.queue_command({'cmd':'tovoid', 'uid':playeruid, 'portin':True})
            
    @tornado.gen.coroutine
    def perform_move(self, locid, text, texteval, oleave, oleaveeval, oarrive, oarriveeval, player=None):
        assert isinstance(locid, ObjectId)
        if self.level != LEVEL_EXECUTE:
            raise Exception('Moves may only occur in action code')
        if not (self.caps & EVALCAP_MOVE):
            raise Exception('Moves not permitted in this code')

        if player is None:
            playeruid = self.uid
        else:
            playeruid = player.uid
            
        player = yield motor.Op(self.app.mongodb.players.find_one,
                                {'_id':playeruid},
                                {'name':1})
        if not player:
            raise Exception('No such player')
        playername = player['name']

        playstate = yield motor.Op(self.app.mongodb.playstate.find_one,
                                   {'_id':playeruid})
        if playstate['iid'] != self.loctx.iid:
            raise Exception('Player is not in the current instance')

        # We must now construct a loctx for the moving player.
        if playeruid == self.uid:
            # The simple (old-fashioned) case.
            loctx = self.loctx
        else:
            # We know the player is in our instance, so this is not
            # too bad.
            loctx = two.task.LocContext(
                playeruid, wid=self.loctx.wid, scid=self.loctx.scid,
                iid=playstate['iid'], locid=playstate['locid'])
            
        yield two.execute.try_hook(self.task, 'on_leave', loctx, 'leaving loc, move',
                                   lambda:{
                '_from':two.execute.LocationProxy(loctx.locid),
                '_to':two.execute.LocationProxy(locid) })
            
        msg = oleave
        if msg is None:
            msg = self.app.localize('action.oleave') % (playername,) # '%s leaves.'
        elif oleaveeval:
            ctx = EvalPropContext(self.task, loctx=loctx, level=LEVEL_MESSAGE)
            msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
        if msg:
            others = yield self.task.find_locale_players(uid=playeruid, notself=True)
            if others:
                self.task.write_event(others, msg)

        # Move the player to the new location.
        lastlocid = loctx.locid
        yield motor.Op(self.app.mongodb.playstate.update,
                       {'_id':playeruid},
                       {'$set':{'locid':locid,
                                'focus':None,
                                'lastlocid': lastlocid,
                                'lastmoved': self.task.starttime }})
        self.task.set_dirty(playeruid, DIRTY_FOCUS | DIRTY_LOCALE | DIRTY_POPULACE)
        self.task.set_data_change( ('playstate', playeruid, 'locid') )
        if lastlocid:
            self.task.set_data_change( ('populace', loctx.iid, lastlocid) )
        self.task.set_data_change( ('populace', loctx.iid, locid) )
        self.task.clear_loctx(playeruid)
        
        msg = oarrive
        if msg is None:
            msg = self.app.localize('action.oarrive') % (playername,) # '%s arrives.'
        elif oarriveeval:
            ctx = EvalPropContext(self.task, loctx=loctx, level=LEVEL_MESSAGE)
            msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
        if msg:
            others = yield self.task.find_locale_players(uid=playeruid, notself=True)
            if others:
                self.task.write_event(others, msg)
                
        msg = text
        if msg:
            if texteval:
                ctx = EvalPropContext(self.task, loctx=loctx, level=LEVEL_MESSAGE)
                msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
            self.task.write_event(playeruid, msg)

        newloctx = yield self.task.get_loctx(playeruid)
        yield two.execute.try_hook(self.task, 'on_enter', newloctx, 'entering loc, move',
                                   lambda:{
                '_from':two.execute.LocationProxy(lastlocid) if lastlocid else None,
                '_to':two.execute.LocationProxy(locid) })

    def set_cooked(self, val):
        """Flip the raw/cooked flag in the text generation state. When
        we enter cooked mode, we use a state that causes a capital letter;
        when we leave, we generate a period (if there wasn't just one).
        """
        if (not self.cooked) and val:
            self.cooked = True
            if self.textstate is RunOnNode:
                self.textstate = BeginNode
        elif self.cooked and (not val):
            self.cooked = False
            if self.textstate is not BeginNode:
                self.accum.append('.')
            self.textstate = RunOnNode

    def accum_append(self, val, raw=False):
        """Add one element to an EvalPropContext. The value must be a
        string or a static GenNodeClass. This relies on, and modifies,
        the ctx state (textstate).
        The upshot is to (probably) add a new string to self.accum, or
        perhaps a paragraph break marker.

        This algorithm is occult, and I'm sorry for that. It's not logically
        *that* complicated; but it has a lot of interacting cases.
        """
        raw = raw or (not self.cooked)
        
        # Check the node type. Break types output nothing; they just change
        # the current state.
        if isinstance(val, GenNodeClass):
            nodtyp = type(val)
            if nodtyp in (RunOnNode, RunOnExplicitNode, CommaNode, SemiNode, StopNode, ParaNode):
                # Retain the more severe break form.
                if self.textstate.precedence < nodtyp.precedence:
                    self.textstate = nodtyp
                return
        else:
            assert (type(val) is str)
            if not val:
                return
            nodtyp = WordNode
            
        docap = False

        # Based on the current state, add a space or punctuation or
        # whatever before the new text.
        if self.textstate in (RunOnNode, RunOnExplicitNode):
            pass
        elif self.textstate in (BeginNode, StopNode, ParaNode):
            if self.textstate is StopNode:
                self.accum.append('. ')
            elif self.textstate is ParaNode:
                self.accum.append('.')
                self.accum.append(['para']) # see interp.ParaBreak
            docap = True
        elif self.textstate is SemiNode:
            self.accum.append('; ')
        elif self.textstate is CommaNode:
            self.accum.append(', ')
        elif self.textstate is RunOnCapNode:
            docap = True
        elif self.textstate is ANode:
            if nodtyp is AFormNode:
                self.accum.append(' ')
            elif nodtyp is AnFormNode:
                self.accum.append('n ')
            elif nodtyp is WordNode and re_vowelstart.match(val):
                self.accum.append('n ')
            else:
                self.accum.append(' ')
        else:
            self.accum.append(' ')

        # Add the new text. We may have to capitalize it, depending on
        # what the last state was. This sets the next state, most commonly
        # to WordNode.
        if nodtyp is WordNode:
            if docap:
                self.accum.append(val[0].upper())
                self.accum.append(val[1:])
            else:                   
                self.accum.append(val)
            if raw:
                self.textstate = RunOnNode
            else:
                self.textstate = WordNode
        elif nodtyp is ANode:
            if docap:
                self.accum.append('A')
            else:
                self.accum.append('a')
            self.textstate = ANode
        elif nodtyp in (AFormNode, AnFormNode):
            if docap:
                self.textstate = RunOnCapNode
            else:
                self.textstate = RunOnNode
        else:
            self.accum.append('[Unsupported GenNodeClass: %s]' % (nodtyp.__name__,))
            

                
def str_or_null(res):
    """Return res as a string, unless res is None, in which case it returns
    the empty string.
    """
    if res is None:
        return ''
    return str(res)

def optimize_accum(ls):
    """Given a list of strings and other objects, concatenate all the strings.
    That is, smush together all the sublists that are all-string.
    This operates in place (and returns nothing).
    """
    end = len(ls)
    while end > 0:
        beg = end - 1
        while beg >= 0 and isinstance(ls[beg], str):
            beg = beg - 1
        if end >= beg + 3:
            ls[beg+1:end] = (''.join(ls[beg+1:end]),)
        end = beg
    return

def parse_argument_spec(spec):
    """Take a function argument spec (e.g. "x, y=3") and parse it into a
    structure. Raises SyntaxError if the spec is invalid.
    Do not include the parentheses in the spec.
    This relies on the Python mechanism in ast.parse.
    
    The defaults and kw_defaults arrays in the result contain ast nodes.
    The caller should immediately evaluate these (self.execcode_expr).
    (The tests and code both assume that spec.defaults and spec.kw_defaults
    are reassignable.)
    """
    if not spec:
        spec = ''
    val = 'lambda %s : None' % (spec,)
    tree = ast.parse(val)
    assert type(tree) is ast.Module
    if len(tree.body) != 1:
        raise SyntaxError('apparent Bobby Tables in argument spec')
    nod = tree.body[0]
    assert type(nod) is ast.Expr
    nod = nod.value
    assert type(nod) is ast.Lambda
    res = nod.args

    # Check for duplicate arguments.
    argset = set()
    for arg in res.args:
        if arg.arg in argset:
            raise SyntaxError('duplicate argument %s in function definition' % (arg.arg,))
        argset.add(arg.arg)
    for arg in res.kwonlyargs:
        if arg.arg in argset:
            raise SyntaxError('duplicate argument %s in function definition' % (arg.arg,))
        argset.add(arg.arg)
    if res.vararg is not None:
        if res.vararg in argset:
            raise SyntaxError('duplicate argument %s in function definition' % (res.vararg,))
        argset.add(res.vararg)
    if res.kwarg is not None:
        if res.kwarg in argset:
            raise SyntaxError('duplicate argument %s in function definition' % (res.kwarg,))
        argset.add(res.kwarg)

    
    return res

def resolve_argument_spec(spec, args, kwargs):
    """Given an argument structure (as built by parse_argument_spec),
    and some positional and keyword arguments, return a map of
    parameter bindings. This should replicate the Python function-call
    spec.
    Raises TypeError if the arguments don't match.
    """
    # Copy this so we can destroy it (and also return it)
    kwargs = dict(kwargs)
        
    res = {}
    for (ix, arg) in enumerate(spec.args):
        if ix < len(args):
            if arg.arg in kwargs:
                raise TypeError('got multiple values for argument "%s"' % (arg.arg,))  
            res[arg.arg] = args[ix]
            continue
        if arg.arg in kwargs:
            res[arg.arg] = kwargs.pop(arg.arg)
            continue
        diff = len(spec.args) - len(spec.defaults)
        if ix >= diff:
            res[arg.arg] = spec.defaults[ix-diff]
            continue
        raise TypeError('missing %d required positional arguments' % (len(spec.args) - (len(args) + len(spec.defaults)),))

    if spec.vararg:
        res[spec.vararg] = tuple(args[ len(spec.args) : ])
    else:
        if len(args) > len(spec.args):
            raise TypeError('%d extra positional arguments' % (len(args) - len(spec.args),))

    for (arg, defv) in zip(spec.kwonlyargs, spec.kw_defaults):
        if arg.arg in kwargs:
            res[arg.arg] = kwargs.pop(arg.arg)
            continue
        if defv is not None:
            res[arg.arg] = defv
            continue
        raise TypeError('missing required keyword-only argument "%s"' % (arg.arg,))

    if spec.kwarg:
        res[spec.kwarg] = kwargs
    else:
        if kwargs:
            raise TypeError('%d extra keyword arguments' % (len(kwargs)),)
    
    return res

# Late imports, to avoid circularity
from twcommon.access import ACC_VISITOR, ACC_MEMBER
import twcommon.interp
from twcommon.interp import InterpNode
from twcommon.gentext import GenNodeClass, SymbolNode, SeqNode, AltNode, ShuffleNode, BeginNode, WordNode, ANode, AFormNode, AnFormNode, RunOnNode, RunOnExplicitNode, RunOnCapNode, ParaNode, StopNode, SemiNode, CommaNode
import two.execute
import two.symbols
import twcommon.gentext
import two.grammar
from two.task import DIRTY_ALL, DIRTY_WORLD, DIRTY_LOCALE, DIRTY_POPULACE, DIRTY_FOCUS
