"""
The context object for evaluating script code. Most of the implementation
of TworldPy lives in the EvalPropContext module.
"""

import random
import ast
import operator

import tornado.gen
import bson
from bson.objectid import ObjectId
import motor

import twcommon.misc
from twcommon.excepts import MessageException, ErrorMessageException
from twcommon.excepts import SymbolError, ExecRunawayException, ExecSandboxException
from twcommon.excepts import ReturnException
from two import interp
import two.task

EVALTYPE_SYMBOL = 0
EVALTYPE_RAW = 1
EVALTYPE_CODE = 2
EVALTYPE_TEXT = 3

LEVEL_EXECUTE = 5
LEVEL_DISPSPECIAL = 4
LEVEL_DISPLAY = 3
LEVEL_MESSAGE = 2
LEVEL_FLAT = 1
LEVEL_RAW = 0

# Singleton object that signifies that the result of an evaluation is
# the accum buffer of the EvalPropContext.
Accumulated = twcommon.misc.SuiGeneris('Accumulated')

class EvalPropFrame:
    """One stack frame in the EvalPropContext. Note that depth starts at 1.

    We add a stack frame for every function call, {code} invocation, and
    {text} interpolation. Nested sub-contexts have their own stack
    list, so we don't create a frame in that case, but the sub-context
    parentdepth field will be one higher than our total depth.
    """
    def __init__(self, depth):
        self.depth = depth
        # Probably foolish optimization: don't allocate an empty locals
        # map unless one is specifically requested.
        self.locals = None
    def __repr__(self):
        return '<EvalPropFrame depth=%d>' % (self.depth,)

class EvalPropContext(object):
    """EvalPropContext is a context for evaluating one symbol, piece of code,
    or piece of marked-up text, during a task.

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
    
    def __init__(self, task, parent=None, loctx=None, parentdepth=0, level=LEVEL_MESSAGE):
        """Caller must provide either parent (an EvalPropContext) or
        a loctx and parentdepth. If there is an effective parent context,
        parentdepth should be ctx.parentdepth+ctx.depth+1. If not, leave
        it as zero.

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
        elif loctx is not None:
            self.parentdepth = parentdepth
            self.loctx = loctx
            self.uid = loctx.uid

        # What kind of evaluation is going on.
        self.level = level

        self.frame = None
        self.frames = None
        self.accum = None
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
    def eval(self, key, evaltype=EVALTYPE_SYMBOL):
        """Look up and return a symbol, in this context. If EVALTYPE_TEXT,
        the argument is treated as an already-looked-up {text} value
        (a string with interpolations). If EVALTYPE_CODE, the argument
        is treated as a snippet of {code}. If EVALTYPE_RAW, the argument
        must be a dict object with a meaningful type field.

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
        
        # Initialize per-invocation fields.
        self.accum = None
        self.linktargets = None
        self.dependencies = set()
        self.wasspecial = False

        # We start with no frames and a depth of zero. (When we add frames,
        # the self.frame will always be the current stack frame, which is
        # the last entry of self.frames.)
        self.frame = None
        self.frames = []

        try:
            EvalPropContext.context_stack.append(self)
            res = yield self.evalobj(key, evaltype=evaltype)
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
            if res is Accumulated:
                # Skip all styles, links, etc. Just paste together strings.
                return ''.join([ val for val in self.accum if type(val) is str ])
            return str(res)
        if (self.level == LEVEL_DISPLAY):
            if res is Accumulated:
                return self.accum
            return str_or_null(res)
        if (self.level == LEVEL_DISPSPECIAL):
            if self.wasspecial:
                return res
            if res is Accumulated:
                return self.accum
            return str_or_null(res)
        if (self.level == LEVEL_EXECUTE):
            if res is Accumulated:
                return self.accum
            return res
        raise Exception('unrecognized eval level: %d' % (self.level,))
        
    @tornado.gen.coroutine
    def evalobj(self, key, evaltype=EVALTYPE_SYMBOL):
        """Look up a symbol, adding it to the accumulated content. If the
        result contains interpolated strings, this calls itself recursively.

        Returns an object, or the special ref Accumulated to indicate a
        description array. (The latter only at MESSAGE/DISPLAY/DISPSPECIAL/
        EXECUTE level.)

        The top-level call to evalobj() may set up the description accumulator
        and linktargets. Lower-level calls use the existing ones.

        A call to here will increment the stack depth *if* it goes into a
        code/text interpolation. For static data values, nothing recursive
        happens and the stack is left alone.
        """
        self.task.tick()
        
        if evaltype == EVALTYPE_SYMBOL:
            origkey = key
            res = yield two.symbols.find_symbol(self.app, self.loctx, key, dependencies=self.dependencies)
        elif evaltype == EVALTYPE_TEXT:
            origkey = None
            res = { 'type':'text', 'text':key }
        elif evaltype == EVALTYPE_CODE:
            origkey = None
            res = { 'type':'code', 'text':key }
        elif evaltype == EVALTYPE_RAW:
            origkey = None
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

        if not(objtype in ('text', 'code')
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
                self.frame = EvalPropFrame(self.depth+1)
                self.frames.append(self.frame)
                if self.parentdepth+self.depth > self.task.STACK_DEPTH_LIMIT:
                    self.task.log.error('ExecRunawayException: User script exceeded depth limit!')
                    raise ExecRunawayException('Script ran too deep; aborting!')
                yield self.interpolate_text(res.get('text', ''))
                return Accumulated
            except ReturnException as ex:
                ### use ex.returnvalue?
                return Accumulated
            except ExecRunawayException:
                raise  # Let this through
            except Exception as ex:
                self.task.log.warning('Caught exception (interpolating): %s', ex, exc_info=self.app.debugstacktraces)
                return '[Exception: %s]' % (ex,)
            finally:
                self.frames.pop()
                self.frame = origframe
        elif objtype == 'code':
            # We let execution errors bubble up to the top level.
            try:
                origframe = self.frame  # may be None
                self.frame = EvalPropFrame(self.depth+1)
                self.frames.append(self.frame)
                if self.parentdepth+self.depth > self.task.STACK_DEPTH_LIMIT:
                    self.task.log.error('ExecRunawayException: User script exceeded depth limit!')
                    raise ExecRunawayException('Script ran too deep; aborting!')
                newres = yield self.execute_code(res.get('text', ''), originlabel=key)
                return newres
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
        if originlabel:
            if type(originlabel) is dict and 'text' in originlabel:
                originlabel = originlabel['text']
            originlabel = '"%.20s"' % (originlabel,)
        else:
            originlabel = '<script>'
            
        tree = ast.parse(text, filename=originlabel)
        assert type(tree) is ast.Module

        ### probably catch some run-exceptions here

        res = None
        for nod in tree.body:
            res = yield self.execcode_statement(nod)
        return res

    @tornado.gen.coroutine
    def execcode_statement(self, nod):
        self.task.tick()
        nodtyp = type(nod)
        ### This should be a faster lookup table
        if nodtyp is ast.Expr:
            res = yield self.execcode_expr(nod.value, baresymbol=True)
            return res
        if nodtyp is ast.Assign:
            res = yield self.execcode_assign(nod)
            return res
        if nodtyp is ast.Delete:
            res = yield self.execcode_delete(nod)
            return res
        if nodtyp is ast.If:
            res = yield self.execcode_if(nod)
            return res
        if nodtyp is ast.Return:
            res = yield self.execcode_return(nod)
            assert False, 'Should not get here'
        if nodtyp is ast.Pass:
            return None
        raise NotImplementedError('Script statement type not implemented: %s' % (nodtyp.__name__,))

    @tornado.gen.coroutine
    def execcode_expr_store(self, nod):
        """Does not evaluate a complete expression. Instead, returns a
        wrapper object with store() and delete() methods.
        (The nod.ctx lets us know whether store or delete is coming up,
        but the way our proxies work, we don't much care.)
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
        raise NotImplementedError('Script store-expression type not implemented: %s' % (nodtyp.__name__,))
        
        
    @tornado.gen.coroutine
    def execcode_expr(self, nod, baresymbol=False):
        self.task.tick()
        nodtyp = type(nod)
        ### This should be a faster lookup table
        if nodtyp is ast.Name:
            res = yield self.execcode_name(nod, baresymbol=baresymbol)
            return res
        if nodtyp is ast.Str:
            return nod.s
        if nodtyp is ast.Num:
            return nod.n  # covers floats and ints
        if nodtyp is ast.List:
            res = yield self.execcode_list(nod)
            return res
        if nodtyp is ast.Tuple:
            res = yield self.execcode_tuple(nod)
            return res
        if nodtyp is ast.UnaryOp:
            res = yield self.execcode_unaryop(nod)
            return res
        if nodtyp is ast.BinOp:
            res = yield self.execcode_binop(nod)
            return res
        if nodtyp is ast.BoolOp:
            res = yield self.execcode_boolop(nod)
            return res
        if nodtyp is ast.Compare:
            res = yield self.execcode_compare(nod)
            return res
        if nodtyp is ast.Attribute:
            res = yield self.execcode_attribute(nod)
            return res
        if nodtyp is ast.Subscript:
            res = yield self.execcode_subscript(nod)
            return res
        if nodtyp is ast.Call:
            res = yield self.execcode_call(nod)
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
        if not opfunc:
            raise NotImplementedError('Script boolop type not implemented: %s' % (optyp.__name__,))
        return opfunc(leftval, rightval)

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
        typarg = type(argument)
        if two.symbols.type_getattr_allowed(typarg, key):
            return getattr(argument, key)
        raise ExecSandboxException('%s.%s: getattr not allowed' % (typarg.__name__, key))

    @tornado.gen.coroutine
    def execcode_subscript(self, nod):
        argument = yield self.execcode_expr(nod.value)
        slice = nod.slice
        if type(slice) is not ast.Index:
            raise NotImplementedError('Subscript slices are not supported')
        subscript = yield self.execcode_expr(slice.value)
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
            kwargs.extend(starargs)
        if isinstance(funcval, two.symbols.ScriptFunc):
            if not funcval.yieldy:
                return funcval.func(*args, **kwargs)
            else:
                res = yield funcval.yieldfunc(*args, **kwargs)
                return res
        ### Special case for {code} dicts...
        # This will raise TypeError if funcval is not callable.
        return funcval(*args, **kwargs)
        
    @tornado.gen.coroutine
    def execcode_name(self, nod, baresymbol=False):
        symbol = nod.id
        res = yield two.symbols.find_symbol(self.app, self.loctx, symbol, locals=self.frame.locals, dependencies=self.dependencies)
        
        if not baresymbol:
            return res
        if type(res) is not dict:
            return res
        
        restype = res.get('type', None)
        uid = self.uid

        if self.level != LEVEL_EXECUTE:
            # If we're not in an action, we invoke text/code snippets.
            if restype == 'text':
                val = res.get('text', None)
                if not val:
                    return ''
                newval = yield self.evalobj(val, evaltype=EVALTYPE_TEXT)
                return newval
            if restype == 'code':
                val = res.get('text', None)
                if not val:
                    return None
                newval = yield self.evalobj(val, evaltype=EVALTYPE_CODE)
                return newval
            # All other special objects are returned as-is.
            return res
        
        if restype in ('text', 'selfdesc', 'editstr'):
            # Set focus to this symbol-name
            yield motor.Op(self.app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':symbol}})
            self.task.set_dirty(uid, DIRTY_FOCUS)
            return None

        if restype == 'portlist':
            # Set focus to an ugly special-case array
            plistid = res.get('plistid', None)
            if not plistid:
                raise ErrorMessageException('portlist property has no plistid')
            
            level = yield two.execute.scope_access_level(self.app, self.uid, self.loctx.wid, self.loctx.scid)
            if level < res.get('readaccess', ACC_VISITOR):
                raise MessageException(self.app.localize('message.widget_no_access'))
            editable = (level >= res.get('editaccess', ACC_MEMBER))
            extratext = res.get('text', None)
            focusport = res.get('focusport', None)
            withback = (focusport is None)
            arr = ['portlist', plistid, editable, extratext, withback, focusport]
            yield motor.Op(self.app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':arr}})
            self.task.set_dirty(uid, DIRTY_FOCUS)
            return None

        if restype == 'code':
            val = res.get('text', None)
            if not val:
                return None
            newval = yield self.evalobj(val, evaltype=EVALTYPE_CODE)
            return newval

        if restype == 'event':
            # Display an event.
            yield self.perform_event(res.get('text', None), True, res.get('otext', None), True)
            return None

        if restype == 'panic':
            # Display an event.
            val = res.get('text', None)
            if val:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                newval = yield ctx.eval(val, evaltype=EVALTYPE_TEXT)
                self.task.write_event(uid, newval)
            val = res.get('otext', None)
            if val:
                others = yield self.task.find_locale_players(notself=True)
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                newval = yield ctx.eval(val, evaltype=EVALTYPE_TEXT)
                self.task.write_event(others, newval)
            self.app.queue_command({'cmd':'tovoid', 'uid':uid, 'portin':True})
            return None

        if restype == 'move':
            # Set locale to the given symbol
            lockey = res.get('loc', None)
            location = yield motor.Op(self.app.mongodb.locations.find_one,
                                      {'wid':self.loctx.wid, 'key':lockey},
                                      {'_id':1})
            if not location:
                raise KeyError('No such location: %s' % (lockey,))

            yield self.perform_move(location['_id'], res.get('text', None), True, res.get('oleave', None), True, res.get('oarrive', None), True)
            return None

        raise ErrorMessageException('Code invoked unsupported property type: %s' % (restype,))

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
    def execcode_return(self, nod):
        if nod.value is None:
            val = None
        else:
            val = yield self.execcode_expr(nod.value)
        raise ReturnException(returnvalue=val)
        
    @tornado.gen.coroutine
    def execcode_assign(self, nod):
        if len(nod.targets) != 1:
            raise NotImplementedError('Script assignment has more than one target')
        target = yield self.execcode_expr_store(nod.targets[0])
        val = yield self.execcode_expr(nod.value)

        yield target.store(self, self.loctx, val)
        return None

    @tornado.gen.coroutine
    def execcode_delete(self, nod):
        for subnod in nod.targets:
            target = yield self.execcode_expr_store(subnod)
            yield target.delete(self, self.loctx)
        return None

    @tornado.gen.coroutine
    def interpolate_text(self, text):
        """Evaluate a bunch of (already-looked-up) interpolation markup.
        """
        self.task.tick()
        
        nodls = interp.parse(text)
        
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
            if not (isinstance(nod, interp.InterpNode)):
                # String.
                if nod and not suppressed:
                    self.accum.append(nod)
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
                    self.accum.append('[$elif without matching $if]')
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
                    self.accum.append('[$end without matching $if]')
                    continue
                suppstack.pop()
                suppressed = sum(suppstack)
                continue

            if nodkey == 'Else':
                if len(suppstack) == 0:
                    self.accum.append('[$else without matching $if]')
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
                if subres is not Accumulated:
                    # Anything not a {text} object gets interpolated as
                    # a string.
                    self.accum.append(str(subres))
                continue
            
            if nodkey == 'PlayerRef':
                player = yield motor.Op(self.app.mongodb.players.find_one,
                                        {'_id':self.uid},
                                        {'name':1, 'pronoun':1})
                if nod.key == 'name':
                    self.accum.append(player['name'])
                else:
                    self.accum.append(interp.resolve_pronoun(player, nod.key))
                continue

            # Otherwise...
            self.accum.append(nod.describe())

        # End of nodls interaction.
        if len(suppstack) > 0:
            self.accum.append('[$if without matching $end]')

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
    def perform_move(self, locid, text, texteval, oleave, oleaveeval, oarrive, oarriveeval):
        if self.level != LEVEL_EXECUTE:
            raise Exception('Moves may only occur in action code')

        player = yield motor.Op(self.app.mongodb.players.find_one,
                                {'_id':self.uid},
                                {'name':1})
        playername = player['name']
                
        msg = oleave
        if msg is None:
            msg = self.app.localize('action.oleave') % (playername,) # '%s leaves.'
        elif oleaveeval:
            ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
            msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
        if msg:
            others = yield self.task.find_locale_players(notself=True)
            if others:
                self.task.write_event(others, msg)

        # Move the player to the new location.
                
        yield motor.Op(self.app.mongodb.playstate.update,
                       {'_id':self.uid},
                       {'$set':{'locid':locid,
                                'focus':None,
                                'lastlocid': self.loctx.locid,
                                'lastmoved': self.task.starttime }})
        self.task.set_dirty(self.uid, DIRTY_FOCUS | DIRTY_LOCALE | DIRTY_POPULACE)
        self.task.set_data_change( ('playstate', self.uid, 'locid') )
        self.task.clear_loctx(self.uid)
        
        # We set everybody in the destination room DIRTY_POPULACE.
        # (Players in the starting room have a dependency, which is already
        # covered.)
        others = yield self.task.find_locale_players(notself=True)
        if others:
            self.task.set_dirty(others, DIRTY_POPULACE)
            
        msg = oarrive
        if msg is None:
            msg = self.app.localize('action.oarrive') % (playername,) # '%s arrives.'
        elif oarriveeval:
            ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
            msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
        if msg:
            # others is already set
            if others:
                self.task.write_event(others, msg)
                
        msg = text
        if msg:
            if texteval:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                msg = yield ctx.eval(msg, evaltype=EVALTYPE_TEXT)
            self.task.write_event(self.uid, msg)


def str_or_null(res):
    if res is None:
        return ''
    return str(res)

# Late imports, to avoid circularity
from twcommon.access import ACC_VISITOR, ACC_MEMBER
import two.execute
from two.task import DIRTY_ALL, DIRTY_WORLD, DIRTY_LOCALE, DIRTY_POPULACE, DIRTY_FOCUS
