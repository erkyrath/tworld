import random
import datetime
import ast
import operator

import tornado.gen
import bson
from bson.objectid import ObjectId
import motor

import twcommon.misc
from twcommon.excepts import MessageException, ErrorMessageException
from twcommon.excepts import SymbolError, ExecRunawayException
from twcommon.misc import MAX_DESCLINE_LENGTH
from two import interp
import two.task
import two.symbols


LEVEL_EXECUTE = 5
LEVEL_DISPSPECIAL = 4
LEVEL_DISPLAY = 3
LEVEL_MESSAGE = 2
LEVEL_FLAT = 1
LEVEL_RAW = 0

# Singleton object that signifies that the result of an evaluation is
# the accum buffer of the EvalPropContext.
Accumulated = twcommon.misc.SuiGeneris('Accumulated')

class EvalPropContext(object):
    """
    EvalPropContext is a context for evaluating one symbol or piece of code,
    during a task.

    When setting up an EvalPropContext you must provide a LocContext, which
    is the identity and location of the player who is the center of the
    action. (Sorry about all the "context"s.) Or you can provide an existing
    EvalPropContext to clone.
    """
    
    link_code_counter = 0

    @staticmethod
    def build_action_key():
        """Return a random (hex digit) string which will never repeat.
        Okay, it is vastly unlikely to repeat.
        """
        EvalPropContext.link_code_counter = EvalPropContext.link_code_counter + 1
        return str(EvalPropContext.link_code_counter) + hex(random.getrandbits(32))[2:]
    
    def __init__(self, task, parent=None, loctx=None, level=LEVEL_MESSAGE):
        self.task = task
        self.app = self.task.app

        assert (parent or loctx)
        assert not (parent and loctx)
        
        if parent is not None:
            assert self.task == parent.task
            self.loctx = parent.loctx
            self.uid = parent.uid
        elif loctx is not None:
            self.loctx = loctx
            self.uid = loctx.uid
            
        self.level = level
        self.accum = None
        self.linktargets = None
        self.dependencies = None
        self.changeset = None

    def updateacdepends(self, ctx):
        """Merge in the actions and dependencies from a subcontext.        
        """
        assert self.accum is not None, 'EvalPropContext.accum should not be None here'
        if ctx.linktargets:
            self.linktargets.update(ctx.linktargets)
        if ctx.dependencies:
            self.dependencies.update(ctx.dependencies)

    @tornado.gen.coroutine
    def eval(self, key, lookup=True):
        """
        Look up and return a symbol, in this context. If lookup=False,
        the argument (string) is treated as an already-looked-up {text}
        value.

        This is the top-level entry point to Doing Stuff in this context.
        
        After the call, dependencies will contain the symbol (and any
        others checked when putting together the result).

        The result type depends on the level:

        RAW: Python object direct from Mongo.
        FLAT: A string.
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
        
        res = yield self.evalkey(key, lookup=lookup)

        # At this point, if the value was a {text}, the accum will contain
        # the desired description.
        
        if (self.level == LEVEL_RAW):
            return res
        if (self.level == LEVEL_FLAT):
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
    def evalkey(self, key, depth=0, lookup=True):
        """
        Look up a symbol, adding it to the accumulated content. If the
        result contains interpolated strings, this calls itself recursively.

        Returns an object or description array. (The latter only at
        MESSAGE/DISPLAY/DISPSPECIAL/EXEC level.)

        The top-level call to evalkey() may set up the description accumulator
        and linktargets. Lower-level calls use the existing ones.
        """
        self.task.tick()
        
        if lookup:
            origkey = key
            res = yield two.symbols.find_symbol(self.app, self.loctx, key, dependencies=self.dependencies)
        else:
            origkey = None
            if type(key) is dict:
                res = key
            else:
                if self.level == LEVEL_EXECUTE:
                    res = { 'type':'code', 'text':key }
                else:
                    res = { 'type':'text', 'text':key }

        objtype = None
        if type(res) is dict:
            objtype = res.get('type', None)

        if depth == 0 and objtype:
            assert self.accum is None, 'EvalPropContext.accum should be None at depth zero'
            self.accum = []
            self.linktargets = {}
            if self.level == LEVEL_EXECUTE:
                self.changeset = set()
        
        if depth == 0 and self.level == LEVEL_DISPSPECIAL and objtype == 'selfdesc':
            assert self.accum is not None, 'EvalPropContext.accum should not be None here'
            try:
                extratext = None
                val = res.get('text', None)
                if val:
                    # Look up the extra text in a separate context.
                    ctx = EvalPropContext(self.task, parent=self, level=LEVEL_DISPLAY)
                    extratext = yield ctx.eval(val, lookup=False)
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
                self.task.log.warning('Caught exception (selfdesc): %s', ex)
                return '[Exception: %s]' % (ex,)
                
        if depth == 0 and self.level == LEVEL_DISPSPECIAL and objtype == 'editstr':
            assert self.accum is not None, 'EvalPropContext.accum should not be None here'
            try:
                extratext = None
                val = res.get('text', None)
                if val:
                    # Look up the extra text in a separate context.
                    ctx = EvalPropContext(self.task, parent=self, level=LEVEL_DISPLAY)
                    extratext = yield ctx.eval(val, lookup=False)
                    self.updateacdepends(ctx)
                # Look up the current symbol value.
                editkey = 'editstr' + EvalPropContext.build_action_key()
                self.linktargets[editkey] = ('editstr', res['key'])
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_FLAT)
                curvalue = yield ctx.eval(res['key'])
                specres = ['editstr',
                           editkey,
                           curvalue,
                           extratext]
                self.wasspecial = True
                return specres
            except Exception as ex:
                self.task.log.warning('Caught exception (editstr): %s', ex)
                return '[Exception: %s]' % (ex,)
                
        if depth == 0 and self.level == LEVEL_DISPSPECIAL and objtype == 'portal':
            assert self.accum is not None, 'EvalPropContext.accum should not be None here'
            try:
                portid = res.get('portid', None)
                backkey = None
                backto = res.get('backto', None)
                if backto:
                    backkey = 'back' + EvalPropContext.build_action_key()
                    self.linktargets[backkey] = backto
                extratext = None
                val = res.get('text', None)
                if val:
                    # Look up the extra text in a separate context.
                    ctx = EvalPropContext(self.task, parent=self, level=LEVEL_DISPLAY)
                    extratext = yield ctx.eval(val, lookup=False)
                    self.updateacdepends(ctx)
                portal = yield motor.Op(self.app.mongodb.portals.find_one,
                                        {'_id':portid})
                yield portal_in_reach(self.app, portal, self.uid, self.loctx.wid)
                portalobj = yield portal_description(self.app, portal, self.uid, uidiid=self.loctx.iid, location=True)
                portalobj['portid'] = str(portal['_id'])
                ackey = 'port' + EvalPropContext.build_action_key()
                self.linktargets[ackey] = ('portal', portid)
                if portalobj.get('copyable', False):
                    copykey = 'copy' + EvalPropContext.build_action_key()
                    self.linktargets[copykey] = ('copyportal', portid)
                    portalobj['copyable'] = copykey
                # Look up the destination portaldesc in a separate context.
                altloctx = two.task.LocContext(None, wid=portal['wid'], locid=portal['locid'])
                ctx = EvalPropContext(self.task, loctx=altloctx, level=LEVEL_FLAT)
                desttext = yield ctx.eval('portaldesc')
                self.updateacdepends(ctx)
                if not desttext:
                    desttext = 'The destination is hazy.' ###localize
                portalobj['view'] = desttext;
                specres = ['portal', ackey, portalobj, backkey, extratext]
                self.wasspecial = True
                return specres
            except Exception as ex:
                self.task.log.warning('Caught exception (portal): %s', ex)
                return '[Exception: %s]' % (ex,)

        if depth == 0 and self.level == LEVEL_DISPSPECIAL and objtype == 'portlist':
            assert self.accum is not None, 'EvalPropContext.accum should not be None here'
            try:
                plistid = res.get('plistid', None)
                extratext = None
                val = res.get('text', None)
                if val:
                    # Look up the extra text in a separate context.
                    ctx = EvalPropContext(self.task, parent=self, level=LEVEL_DISPLAY)
                    extratext = yield ctx.eval(val, lookup=False)
                    self.updateacdepends(ctx)
                portlist = yield motor.Op(self.app.mongodb.portlists.find_one,
                                          {'_id':plistid})
                if not portlist or portlist['wid'] != self.loctx.wid:
                    raise ErrorMessageException('This portal list is not available.')
                cursor = self.app.mongodb.portals.find({'plistid':plistid})
                ls = []
                while (yield cursor.fetch_next):
                    portal = cursor.next_object()
                    ls.append(portal)
                cursor.close()
                ls.sort(key=lambda portal:portal.get('listpos', 0))
                subls = []
                for portal in ls:
                    desc = yield portal_description(self.app, portal, self.uid, uidiid=self.loctx.iid)
                    if desc:
                        ackey = 'plist' + EvalPropContext.build_action_key()
                        self.linktargets[ackey] = ('focus', 'portal', portal['_id'], origkey, None)
                        desc['target'] = ackey
                        subls.append(desc)
                specres = ['portlist', subls, extratext]
                self.wasspecial = True
                return specres
            except Exception as ex:
                self.task.log.warning('Caught exception (portlist): %s', ex)
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
                yield self.interpolate_text(res.get('text', ''), depth=depth)
                return Accumulated
            except ExecRunawayException:
                raise  # Let this through
            except Exception as ex:
                self.task.log.warning('Caught exception (interpolating): %s', ex)
                return '[Exception: %s]' % (ex,)
        elif objtype == 'code':
            # We let execution errors bubble up to the top level.
            newres = yield self.execute_code(res.get('text', ''), originlabel=key, depth=depth)
            return newres
        else:
            return '[Unhandled object type: %s]' % (objtype,)

    @tornado.gen.coroutine
    def execute_code(self, text, depth, originlabel=None):
        """Execute a pile of (already-looked-up) script code.
        """
        self.task.log.debug('### executing code: %s', text)
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
            res = yield self.execcode_statement(nod, depth)
        return res

    @tornado.gen.coroutine
    def execcode_statement(self, nod, depth):
        self.task.tick()
        nodtyp = type(nod)
        ### This should be a faster lookup table
        if nodtyp is ast.Expr:
            res = yield self.execcode_expr(nod.value, depth)
            return res
        if nodtyp is ast.Assign:
            res = yield self.execcode_assign(nod, depth)
            return res
        raise NotImplementedError('Script statement type not implemented: %s' % (nodtyp.__name__,))

    @tornado.gen.coroutine
    def execcode_expr(self, nod, depth):
        self.task.tick()
        nodtyp = type(nod)
        ### This should be a faster lookup table
        if nodtyp is ast.Name:
            res = yield self.execcode_name(nod, depth)
            return res
        if nodtyp is ast.Str:
            return nod.s
        if nodtyp is ast.Num:
            return nod.n  # covers floats and ints
        if nodtyp is ast.UnaryOp:
            res = yield self.execcode_unaryop(nod, depth)
            return res
        if nodtyp is ast.BinOp:
            res = yield self.execcode_binop(nod, depth)
            return res
        if nodtyp is ast.BoolOp:
            res = yield self.execcode_boolop(nod, depth)
            return res
        if nodtyp is ast.Compare:
            res = yield self.execcode_compare(nod, depth)
            return res
        if nodtyp is ast.Attribute:
            res = yield self.execcode_attribute(nod, depth)
            return res
        raise NotImplementedError('Script expression type not implemented: %s' % (nodtyp.__name__,))

    map_unaryop_operators = {
        ast.Not: operator.not_,
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
        }
        
    @tornado.gen.coroutine
    def execcode_unaryop(self, nod, depth):
        optyp = type(nod.op)
        argval = yield self.execcode_expr(nod.operand, depth)
        opfunc = self.map_unaryop_operators.get(optyp, None)
        if not opfunc:
            raise NotImplementedError('Script unaryop type not implemented: %s' % (optyp.__name__,))
        return opfunc(argval)
        
    map_binop_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: ast.Div,
        }
        
    @tornado.gen.coroutine
    def execcode_binop(self, nod, depth):
        optyp = type(nod.op)
        leftval = yield self.execcode_expr(nod.left, depth)
        rightval = yield self.execcode_expr(nod.right, depth)
        opfunc = self.map_binop_operators.get(optyp, None)
        if not opfunc:
            raise NotImplementedError('Script binop type not implemented: %s' % (optyp.__name__,))
        return opfunc(leftval, rightval)
        
    @tornado.gen.coroutine
    def execcode_boolop(self, nod, depth):
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
    def execcode_compare(self, nod, depth):
        leftval = yield self.execcode_expr(nod.left, depth)
        for (op, subnod) in zip(nod.ops, nod.comparators):
            rightval = yield self.execcode_expr(subnod, depth)
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
    def execcode_attribute(self, nod, depth):
        argument = yield self.execcode_expr(nod.value, depth)
        return getattr(argument, nod.attr)
        
    @tornado.gen.coroutine
    def execcode_name(self, nod, depth):
        symbol = nod.id
        res = yield two.symbols.find_symbol(self.app, self.loctx, symbol, dependencies=self.dependencies)
        if type(res) is not dict:
            return res
        restype = res.get('type', None)
        uid = self.uid
        
        if restype in ('text', 'portal', 'portlist', 'selfdesc', 'editstr'):
            # Set focus to this symbol-name
            yield motor.Op(self.app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':symbol}})
            self.task.set_dirty(uid, DIRTY_FOCUS)
            return None

        ### 'focus'?
        
        if restype == 'code':
            val = res.get('text', None)
            if not val:
                raise ErrorMessageException('Code object lacks text')
            # Pass in the whole {code} object
            newval = yield self.evalkey(res, lookup=False, depth=depth+1)
            return newval

        if restype == 'event':
            # Display an event.
            val = res.get('text', None)
            if val:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                newval = yield ctx.eval(val, lookup=False)
                self.task.write_event(uid, newval)
            val = res.get('otext', None)
            if val:
                others = yield self.task.find_locale_players(notself=True)
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                newval = yield ctx.eval(val, lookup=False)
                self.task.write_event(others, newval)
            return None

        if restype == 'panic':
            # Display an event.
            val = res.get('text', None)
            if val:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                newval = yield ctx.eval(val, lookup=False)
                self.task.write_event(uid, newval)
            val = res.get('otext', None)
            if val:
                others = yield self.task.find_locale_players(notself=True)
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                newval = yield ctx.eval(val, lookup=False)
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
                raise ErrorMessageException('No such location: %s' % (lockey,))
    
            player = yield motor.Op(self.app.mongodb.players.find_one,
                                    {'_id':uid},
                                    {'name':1})
            playername = player['name']
                
            msg = res.get('oleave', None)
            if msg is None:
                msg = '%s leaves.' % (playername,) ###localize
            else:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                msg = yield ctx.eval(msg, lookup=False)
            if msg:
                others = yield self.task.find_locale_players(notself=True)
                if others:
                    self.task.write_event(others, msg)
                    
            yield motor.Op(self.app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'locid':location['_id'], 'focus':None,
                                    'lastmoved': self.task.starttime }})
            self.task.set_dirty(uid, DIRTY_FOCUS | DIRTY_LOCALE | DIRTY_POPULACE)
            self.task.set_data_change( ('playstate', uid, 'locid') )
            self.task.clear_loctx(uid)
            
            # We set everybody in the destination room DIRTY_POPULACE.
            # (Players in the starting room have a dependency, which is already
            # covered.)
            others = yield self.task.find_locale_players(notself=True)
            if others:
                self.task.set_dirty(others, DIRTY_POPULACE)
                
            msg = res.get('oarrive', None)
            if msg is None:
                msg = '%s arrives.' % (playername,) ###localize
            else:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                msg = yield ctx.eval(msg, lookup=False)
            if msg:
                # others is already set
                if others:
                    self.task.write_event(others, msg)
            msg = res.get('text', None)
            if msg:
                ctx = EvalPropContext(self.task, parent=self, level=LEVEL_MESSAGE)
                msg = yield ctx.eval(msg, lookup=False)
                self.task.write_event(uid, msg)

            return None

        raise ErrorMessageException('Code invoked unsupported property type: %s' % (restype,))

    @tornado.gen.coroutine
    def execcode_assign(self, nod, depth):
        if len(nod.targets) != 1:
            raise NotImplementedError('Script assignment has more than one target')
        target = nod.targets[0]
        if type(target) != ast.Name:
            raise NotImplementedError('Script assignment is not a simple symbol')
        key = target.id
        val = yield self.execcode_expr(nod.value, depth)
        self.task.log.debug('### executing assignment: %s = %s', key, repr(val))
        
        if self.level != LEVEL_EXECUTE:
            raise Exception('Assignment only permitted in action code')
        
        iid = self.loctx.iid
        locid = self.loctx.locid
        yield motor.Op(self.app.mongodb.instanceprop.update,
                       {'iid':iid, 'locid':locid, 'key':key},
                       {'iid':iid, 'locid':locid, 'key':key, 'val':val},
                       upsert=True)
        self.changeset.add( ('instanceprop', iid, locid, key) )

        return None

    @tornado.gen.coroutine
    def interpolate_text(self, text, depth):
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
                    ifval = yield two.symbols.find_symbol(self.app, self.loctx, nod.expr, dependencies=self.dependencies)
                except SymbolError: ### or AttributeError?
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
                    ifval = yield two.symbols.find_symbol(self.app, self.loctx, nod.expr, dependencies=self.dependencies)
                except SymbolError: ### or AttributeError?
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
                    subres = yield self.evalkey(nod.expr, depth=depth+1)
                except SymbolError:
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

def str_or_null(res):
    if res is None:
        return ''
    return str(res)

@tornado.gen.coroutine
def portal_in_reach(app, portal, uid, wid):
    """Make sure that a portal (object) is reachable by the player (uid)
    who is in world wid. Raises a ErrorMessageException if not.

    ("Reachable" means in the given world, or in the player's personal
    collection. This does not check access levels.)
    ### Will also have to account for being offered a link by another
    player.
    """
    if not portal:
        raise ErrorMessageException('Portal not found.')
    if 'inwid' in portal:
        # Directly in-place in the world.
        if portal['inwid'] != wid:
            raise ErrorMessageException('You are not in this portal\'s world.')
    elif 'plistid' in portal:
        # In a portlist.
        portlist = yield motor.Op(app.mongodb.portlists.find_one,
                                  {'_id':portal['plistid']})
        if not portlist:
            raise ErrorMessageException('Portal does not have a portlist.')
        if portlist['type'] == 'pers':
            if portlist['uid'] != uid:
                raise ErrorMessageException('Portal is not in your personal portlist.')
        else:
            if portlist['wid'] != wid:
                raise ErrorMessageException('You are not in this portlist\'s world.')
    else:
        raise ErrorMessageException('Portal does not have a placement.')

@tornado.gen.coroutine
def portal_resolve_scope(app, portal, uid, scid, world):
    """Figure out what scope we are porting to. The portal scid
    value may be a special value such as 'personal', 'global',
    'same'. We also obey the (higher priority) world-instancing
    definition.

    The scid argument must be where the player is now; the world must be
    the destination world object from the database. (Yes, that's all
    clumsy and uneven.)
    """
    reqscid = portal['scid']
    if world['instancing'] == 'solo':
        reqscid = 'personal'
    if world['instancing'] == 'shared':
        reqscid = 'global'
    
    if reqscid == 'personal':
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':uid},
                                {'scid':1})
        if not player or not player['scid']:
            raise ErrorMessageException('You have no personal scope!')
        newscid = player['scid']
    elif reqscid == 'global':
        config = yield motor.Op(app.mongodb.config.find_one,
                                {'key':'globalscopeid'})
        if not config:
            raise ErrorMessageException('There is no global scope!')
        newscid = config['val']
    elif reqscid == 'same':
        newscid = scid
    else:
        newscid = reqscid
    assert isinstance(newscid, ObjectId), 'newscid is not ObjectId'
    return newscid
    
@tornado.gen.coroutine
def portal_description(app, portal, uid, uidiid=None, location=False, short=False):
    """Return a (JSONable) object describing a portal in human-readable
    strings. Returns None if a problem arises.

    The argument may be a portal object or an ObjectId referring to one.
    If location is true, include the location name. If short is true,
    use a shorter form of the scope label.
    """
    try:
        if isinstance(portal, ObjectId):
            portal = yield motor.Op(app.mongodb.portals.find_one,
                                    {'_id':portal})
        if not portal:
            return None
        
        world = yield motor.Op(app.mongodb.worlds.find_one,
                               {'_id':portal['wid']})
        if not world:
            return None
        worldname = world.get('name', '???')
        
        creator = yield motor.Op(app.mongodb.players.find_one,
                                 {'_id':world['creator']}, {'name':1})
        if creator:
            creatorname = creator.get('name', '???')
        else:
            creatorname = '???'

        # This logic is parallel to portal_resolve_scope().
        reqscid = portal['scid']
        if world['instancing'] == 'solo':
            reqscid = 'personal'
        if world['instancing'] == 'shared':
            reqscid = 'global'
            
        if reqscid == 'personal':
            player = yield motor.Op(app.mongodb.players.find_one,
                                    {'_id':uid},
                                    {'scid':1})
            scope = yield motor.Op(app.mongodb.scopes.find_one,
                                   {'_id':player['scid']})
        elif reqscid == 'global':
            config = yield motor.Op(app.mongodb.config.find_one,
                                    {'key':'globalscopeid'})
            scope = yield motor.Op(app.mongodb.scopes.find_one,
                                   {'_id':config['val']})
        elif reqscid == 'same':
            if not uidiid:
                playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                           {'_id':uid},
                                           {'iid':1})
                uidiid = playstate['iid']
            instance = yield motor.Op(app.mongodb.instances.find_one,
                                       {'_id':uidiid},
                                       {'scid':1})
            scope = yield motor.Op(app.mongodb.scopes.find_one,
                                   {'_id':instance['scid']})
        else:
            scope = yield motor.Op(app.mongodb.scopes.find_one,
                                   {'_id':reqscid})

        if scope['type'] == 'glob':
            if short:
                scopename = 'global'
            else:
                scopename = 'Global instance'
        elif scope['type'] == 'pers' and scope['uid'] == uid:
            if short:
                scopename = 'personal'
            else: 
                scopename = 'Personal instance'
        elif scope['type'] == 'pers':
            scopeowner = yield motor.Op(app.mongodb.players.find_one,
                                        {'_id':scope['uid']},
                                        {'name':1})
            if short:
                scopename = 'personal: %s' % (scopeowner['name'],)
            else: 
                scopename = 'Personal instance: %s' % (scopeowner['name'],)
        elif scope['type'] == 'grp':
            if short:
                scopename = 'group: %s' % (scope['group'],)
            else:
                scopename = 'Group instance: %s' % (scope['group'],)
        else:
            scopename = '???'

        res = {'world':worldname, 'scope':scopename, 'creator':creatorname}

        if world.get('copyable', False):
            res['copyable'] = True

        if portal.get('preferred', False):
            res['preferred'] = True

        if location:
            loc = yield motor.Op(app.mongodb.locations.find_one,
                                 {'_id':portal['locid']})
            if loc:
                locname = loc.get('name', '???')
            else:
                locname = '???'
            res['location'] = locname

        return res
    
    except Exception as ex:
        app.log.warning('portal_description failed: %s', ex)
        return None

@tornado.gen.coroutine
def render_focus(task, loctx, conn, focusobj):
    """The part of generate_update() that deals with focus.
    Returns (focus, focusspecial).
    """
    if focusobj is None:
        return (False, False)

    lookup = True

    assert conn.uid == loctx.uid
    wid = loctx.wid
    iid = loctx.iid
    locid = loctx.locid
    
    if type(focusobj) is list:
        restype = focusobj[0]
        
        if restype == 'player':
            player = yield motor.Op(task.app.mongodb.players.find_one,
                                    {'_id':focusobj[1]},
                                    {'name':1, 'desc':1})
            if not player:
                return ('There is no such person.', False)
            focusdesc = '%s is %s' % (player.get('name', '???'), player.get('desc', '...'))
            conn.focusdependencies.add( ('players', focusobj[1], 'desc') )
            conn.focusdependencies.add( ('players', focusobj[1], 'name') )
            return (focusdesc, False)
        
        if restype == 'portal':
            lookup = False
            arr = focusobj
            focusobj = {'type':'portal', 'portid':arr[1]}
            if len(arr) >= 3:
                focusobj['backto'] = arr[2]
            pass   # Fall through to EvalPropContext code below
        else:
            focusdesc = '[Focus: %s]' % (focusobj,)
            return (focusdesc, False)

    ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_DISPSPECIAL)
    focusdesc = yield ctx.eval(focusobj, lookup=lookup)
    if ctx.linktargets:
        conn.focusactions.update(ctx.linktargets)
    if ctx.dependencies:
        conn.focusdependencies.update(ctx.dependencies)
    return (focusdesc, ctx.wasspecial)

@tornado.gen.coroutine
def generate_update(task, conn, dirty):
    """Construct an update message for a player client. This will involve
    recomputing the locale text, focus text, or so on.
    """
    assert conn is not None, 'generate_update: conn is None'
    if not dirty:
        return

    app = task.app
    uid = conn.uid
    # Don't go to task.get_loctx for the locale info; we need a few different
    # bits of data. Plus, maybe the player moved.

    msg = { 'cmd': 'update' }

    playstate = yield motor.Op(app.mongodb.playstate.find_one,
                               {'_id':uid},
                               {'iid':1, 'locid':1, 'focus':1})
    
    iid = playstate['iid']
    if not iid:
        msg['world'] = {'world':'(In transition)', 'scope':'\u00A0', 'creator':'...'}
        msg['focus'] = False ### probably needs to be something for linking out of the void
        msg['populace'] = False
        msg['locale'] = { 'desc': '...' }
        conn.write(msg)
        return

    instance = yield motor.Op(app.mongodb.instances.find_one,
                              {'_id':iid})
    wid = instance['wid']
    scid = instance['scid']
    locid = playstate['locid']
    loctx = two.task.LocContext(uid, wid, scid, iid, locid)

    if dirty & DIRTY_WORLD:
        scope = yield motor.Op(app.mongodb.scopes.find_one,
                               {'_id':scid})
        world = yield motor.Op(app.mongodb.worlds.find_one,
                               {'_id':wid},
                               {'creator':1, 'name':1})
    
        worldname = world['name']
    
        creator = yield motor.Op(app.mongodb.players.find_one,
                                 {'_id':world['creator']},
                                 {'name':1})
        creatorname = 'Created by %s' % (creator['name'],)
    
        if scope['type'] == 'glob':
            scopename = '(Global instance)'
        elif scope['type'] == 'pers':
        ### Probably leave off the name if it's you
            scopeowner = yield motor.Op(app.mongodb.players.find_one,
                                        {'_id':scope['uid']},
                                        {'name':1})
            scopename = '(Personal instance: %s)' % (scopeowner['name'],)
        elif scope['type'] == 'grp':
            scopename = '(Group: %s)' % (scope['group'],)
        else:
            scopename = '???'

        msg['world'] = {'world':worldname, 'scope':scopename, 'creator':creatorname}

    if dirty & DIRTY_LOCALE:
        conn.localeactions.clear()
        conn.localedependencies.clear()
        
        ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_DISPLAY)
        localedesc = yield ctx.eval('desc')
        
        if ctx.linktargets:
            conn.localeactions.update(ctx.linktargets)
        if ctx.dependencies:
            conn.localedependencies.update(ctx.dependencies)

        location = yield motor.Op(app.mongodb.locations.find_one,
                                  {'_id':locid},
                                  {'wid':1, 'name':1})

        if not location or location['wid'] != wid:
            locname = '[Location not found]'
        else:
            locname = location['name']

        msg['locale'] = { 'name': locname, 'desc': localedesc }

    if dirty & DIRTY_POPULACE:
        conn.populaceactions.clear()
        conn.populacedependencies.clear()
        
        # Build a list of all the other people in the location.
        cursor = app.mongodb.playstate.find({'iid':iid, 'locid':locid},
                                            {'_id':1, 'lastmoved':1})
        people = []
        while (yield cursor.fetch_next):
            ostate = cursor.next_object()
            if ostate['_id'] == uid:
                continue
            if not ostate.get('lastmoved', None):
                # If no lastmoved field, set it to the beginning of time.
                ostate['lastmoved'] = datetime.datetime.min
            people.append(ostate)
            ackey = 'play' + EvalPropContext.build_action_key()
            ostate['_ackey'] = ackey
            conn.populaceactions[ackey] = ('player', ostate['_id'])
            conn.populacedependencies.add( ('playstate', ostate['_id'], 'locid') )
        cursor.close()
        for ostate in people:
            oplayer = yield motor.Op(app.mongodb.players.find_one,
                                     {'_id':ostate['_id']},
                                     {'name':1})
            ostate['name'] = oplayer.get('name', '???')

        if not people:
            populacedesc = False
        else:
            # Sort the list by lastmoved.
            people.sort(key=lambda ostate:ostate['lastmoved'])
            populacedesc = [ 'You see ' ]  # Location property? Routine?
            pos = 0
            numpeople = len(people)
            for ostate in people:
                if pos > 0:
                    if numpeople == 2:
                        populacedesc.append(' and ')
                    elif pos >= numpeople-2:
                        populacedesc.append(', and ')
                    else:
                        populacedesc.append(', ')
                populacedesc.append(['link', ostate['_ackey']])
                populacedesc.append(ostate['name'])
                populacedesc.append(['/link'])
                pos += 1
            populacedesc.append(' here.')

        msg['populace'] = populacedesc

    if dirty & DIRTY_FOCUS:
        conn.focusactions.clear()
        conn.focusdependencies.clear()

        focusobj = playstate.get('focus', None)
        (focusdesc, focusspecial) = yield render_focus(task, loctx, conn, focusobj)

        msg['focus'] = focusdesc
        if focusspecial:
            msg['focusspecial'] = True
    
    conn.write(msg)
    

@tornado.gen.coroutine
def perform_action(task, cmd, conn, target):
    """Carry out an action command. These are the commands which we have
    set up in the player's environment (localeactions, focusactions, etc);
    the player has just triggered one of them.

    The cmd argument is usually irrelevant -- we've already extracted
    the target argument from it. But in a few cases, we'll need additional
    fields from it.
    """
    app = task.app
    uid = conn.uid
    loctx = yield task.get_loctx(uid)

    if not loctx.iid:
        # In the void, there should be no actions.
        raise ErrorMessageException('You are between worlds.')

    if type(target) is tuple:
        # Action targets that are dicts. These result from special structures
        # in the world, not simple links in descriptions.
        
        restype = target[0]
        
        if restype == 'player':
            obj = ['player', target[1]]
            yield motor.Op(app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':obj}})
            task.set_dirty(uid, DIRTY_FOCUS)
            return

        if restype == 'focus':
            obj = list(target[1:])
            yield motor.Op(app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':obj}})
            task.set_dirty(uid, DIRTY_FOCUS)
            return
        
        if restype == 'editstr':
            key = target[1]
            val = getattr(cmd, 'val', None)
            if val is None:
                raise ErrorMessageException('No value given for editstr.')
            val = str(val)
            if len(val) > MAX_DESCLINE_LENGTH:
                val = val[0:MAX_DESCLINE_LENGTH]
            iid = loctx.iid
            locid = loctx.locid
            yield motor.Op(app.mongodb.instanceprop.update,
                           {'iid':iid, 'locid':locid, 'key':key},
                           {'iid':iid, 'locid':locid, 'key':key, 'val':val},
                           upsert=True)
            task.set_data_change( ('instanceprop', iid, locid, key) )
            return
            
        if restype == 'copyportal':
            portid = target[1]
            portal = yield motor.Op(app.mongodb.portals.find_one,
                                      {'_id':portid})
            if not portal:
                raise ErrorMessageException('Portal not found.')

            # Check that the portal is accessible.
            yield portal_in_reach(app, portal, uid, loctx.wid)

            world = yield motor.Op(app.mongodb.worlds.find_one,
                                   {'_id':portal['wid']})
            if not world:
                raise ErrorMessageException('Destination world not found.')
            newwid = world['_id']

            location = yield motor.Op(app.mongodb.locations.find_one,
                                      {'_id':portal['locid'], 'wid':newwid})
            if not location:
                raise ErrorMessageException('Destination location not found.')
            newlocid = location['_id']
            
            newscid = yield portal_resolve_scope(app, portal, uid, loctx.scid, world)

            
            player = yield motor.Op(app.mongodb.players.find_one,
                                    {'_id':uid},
                                    {'plistid':1})
            plistid = player['plistid']

            newportal = { 'plistid':plistid,
                          'wid':newwid, 'scid':newscid, 'locid':newlocid,
                          }
            res = yield motor.Op(app.mongodb.portals.find_one,
                                 newportal)
            if res:
                raise MessageException('This portal is already in your collection.') ###localize

            # Look through the player's list and find the entry with the
            # highest listpos.
            res = yield motor.Op(app.mongodb.portals.aggregate, [
                    {'$match': {'plistid':plistid}},
                    {'$sort': {'listpos':-1}},
                    {'$limit': 1},
                    ])
            listpos = 0.0
            if res and res['result']:
                listpos = res['result'][0].get('listpos', 0.0)
                
            newportal['listpos'] = listpos + 1.0
            newportid = yield motor.Op(app.mongodb.portals.insert, newportal)
            newportal['_id'] = newportid

            portaldesc = yield portal_description(app, portal, uid, uidiid=loctx.iid, location=True, short=True)
            if portaldesc:
                strid = str(newportid)
                portaldesc['portid'] = strid
                portaldesc['listpos'] = newportal['listpos']
                map = { strid: portaldesc }
                subls = app.playconns.get_for_uid(uid)
                if subls:
                    for subconn in subls:
                        subconn.write({'cmd':'updateplist', 'map':map})

            conn.write({'cmd':'message', 'text':'You copy the portal to your collection.'}) ###localize
            return

        if restype == 'portal':
            portid = target[1]
            portal = yield motor.Op(app.mongodb.portals.find_one,
                                      {'_id':portid})
            if not portal:
                raise ErrorMessageException('Portal not found.')

            # Check that the portal is accessible.
            yield portal_in_reach(app, portal, uid, loctx.wid)

            world = yield motor.Op(app.mongodb.worlds.find_one,
                                   {'_id':portal['wid']})
            if not world:
                raise ErrorMessageException('Destination world not found.')
            newwid = world['_id']

            location = yield motor.Op(app.mongodb.locations.find_one,
                                      {'_id':portal['locid'], 'wid':newwid})
            if not location:
                raise ErrorMessageException('Destination location not found.')
            newlocid = location['_id']

            newscid = yield portal_resolve_scope(app, portal, uid, loctx.scid, world)

            # Load up the instance, but only to check minaccess.
            instance = yield motor.Op(app.mongodb.instances.find_one,
                                      {'wid':newwid, 'scid':newscid})
            if instance:
                minaccess = instance.get('minaccess', ACC_VISITOR)
            else:
                minaccess = ACC_VISITOR
            if False: ### check minaccess against scope access!
                task.write_event(uid, 'You do not have access to this instance.') ###localize
                return
        
            res = yield motor.Op(app.mongodb.players.find_one,
                                 {'_id':uid},
                                 {'name':1})
            playername = res['name']
        
            others = yield task.find_locale_players(notself=True)
            if others:
                # Don't need to dirty populace; everyone here has a
                # dependency.
                task.write_event(others, '%s disappears.' % (playername,)) ###localize
            task.write_event(uid, 'The world fades away.') ###localize

            # Jump to the void, and schedule a portin event.
            portto = {'wid':newwid, 'scid':newscid, 'locid':newlocid}
            yield motor.Op(app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'iid':None,
                                    'locid':None,
                                    'focus':None,
                                    'lastmoved': task.starttime,
                                    'portto':portto }})
            task.set_dirty(uid, DIRTY_FOCUS | DIRTY_LOCALE | DIRTY_WORLD | DIRTY_POPULACE)
            task.set_data_change( ('playstate', uid, 'iid') )
            task.set_data_change( ('playstate', uid, 'locid') )
            task.clear_loctx(uid)
            app.schedule_command({'cmd':'portin', 'uid':uid}, 1.5)
            return

        # End of special-dict targets.
        raise ErrorMessageException('Action not understood: "%s"' % (target,))

    # The target is a string. This may be a simple symbol, or a chunk of
    # code.

    ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)
    try:
        newval = yield ctx.eval(target, lookup=False)
        if newval is not None:
            ### Not sure I like this.
            conn.write({'cmd':'event', 'text':str(newval)})
    except Exception as ex:
        task.log.warning('Action failed: %s', ex)
        exmsg = '%s: %s' % (ex.__class__.__name__, ex,)
        conn.write({'cmd':'error', 'text':exmsg})
    if ctx.changeset:
        task.add_data_changes(ctx.changeset)
        
    
# Late imports, to avoid circularity
from two.task import DIRTY_ALL, DIRTY_WORLD, DIRTY_LOCALE, DIRTY_POPULACE, DIRTY_FOCUS
from twcommon.access import ACC_VISITOR
