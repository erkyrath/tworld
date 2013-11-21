import types
import itertools
import random
import datetime

import tornado.gen
from bson.objectid import ObjectId
import motor

class ScriptNamespace(object):
    """A container for user-accessible items in a script. This is basically
    a script-safe equivalent of a module.

    Also supports generators as fields -- gettable properties, more or less.
    An entry in propmap is called and the result returned as the property
    value.    

    Note that to fetch an attribute, you call nmsp.get(key) or
    nmsp.getyieldy(key). But in script code, you'd say "nmsp.foo".
    
    Safe to print (as a str). Contained values are abbreviated, and it
    tries to avoid recursing into them.
    """
    def __init__(self, map, propmap=None):
        self.map = dict(map)
        if propmap:
            self.propmap = dict(propmap)
        else:
            self.propmap = {}
        
    def __repr__(self):
        ls = []
        for (key, val) in itertools.chain(self.map.items(), self.propmap.items()):
            if type(val) is dict:
                val = '{...}'
            elif isinstance(val, types.SimpleNamespace):
                val = 'namespace(...)'
            elif isinstance(val, ScriptNamespace):
                val = 'ScriptNamespace(...)'
            else:
                val = str(val)
                if len(val) > 30:
                    val = val[:30] + '...'
            ls.append('%s=%s' % (key, val))
        ls = ', '.join(ls)
        return '<ScriptNamespace(%s)>' % (ls,)

    def get(self, key):
        """Get an entry. This works for normal (attribute) entries and
        non-yieldy property entries. If you're trying to fetch an
        arbitrary entry, call getyieldy() instead.
        """
        if key in self.propmap:
            funcval = self.propmap[key]
            if isinstance(funcval, ScriptCallable):
                if not funcval.yieldy:
                    return funcval.func()
                else:
                    raise Exception('ScriptNamespace: cannot use simple get() for a yieldy ScriptFunc!')
            return funcval()
        return self.map[key]

    def getyieldy(self, key):
        """Get an entry which may be an asychronous operation.
        (This is terrible, but better than handling every single
        nmsp.attr as a coroutine call? I think?)
        Anyhow, you call this with the idiom:
          (res, yieldy) = nmsp.getyieldy(key)
          if yieldy:
            res = yield res()
        """
        if key in self.propmap:
            funcval = self.propmap[key]
            if isinstance(funcval, ScriptCallable):
                if not funcval.yieldy:
                    return (funcval.func(), False)
                else:
                    return (funcval.yieldfunc, True)
            return (funcval(), False)
        return (self.map[key], False)

    def has(self, key):
        return (key in self.map) or (key in self.propmap)

class ScriptCallable:
    """Base class for objects callable in the script environment.
    These generally wrap some native Python callable.

    A ScriptCallable must supply a func (if self.yieldy is False)
    or a yieldfunc (if self.yieldy is True).
    """
    yieldy = False

    def func(self):
        raise NotImplementedError('ScriptCallable: func')
    @tornado.gen.coroutine
    def yieldfunc(self):
        raise NotImplementedError('ScriptCallable: yieldfunc')

class ScriptPartialFunc(ScriptCallable):
    """The script equivalent of functools.partial.
    """
    def __init__(self, func, args, keywords):
        self.yieldy = True
        self.val = func
        self.args = args
        self.keywords = keywords

    def __repr__(self):
        argls = [ str(self.val) ] + [ repr(val) for val in self.args ] + [ ('%s=%s' % (key, repr(val))) for (key, val) in self.keywords.items() ]
        argls = ', '.join(argls)
        return '<ScriptPartialFunc %s>' % (argls,)
    
    @tornado.gen.coroutine
    def yieldfunc(self, *newargs, **newkeywords):
        args = self.args + newargs
        kwargs = self.keywords.copy()
        kwargs.update(newkeywords)
        ctx = EvalPropContext.get_current_context()
        res = yield ctx.exec_call_object(self.val, args, kwargs)
        return res

class ScriptFunc(ScriptCallable):
    """One of the callable objects that exists in the global namespace.
    These are always safe to call, because we set them up at init time.
    """
    
    # As functions are defined with the @scriptfunc decorator, they are
    # stuffed into a dict in this master dict.
    funcgroups = {}
    
    def __init__(self, name, func, group=None, yieldy=False):
        self.name = name
        if group == '_':
            group = None
        self.groupname = group
        self.yieldy = yieldy

        if not yieldy:
            self.func = func
        else:
            self.yieldfunc = tornado.gen.coroutine(func)
        
    def __repr__(self):
        prefix = ''
        if self.groupname:
            prefix = self.groupname + '.'
        return '<ScriptFunc "%s%s">' % (prefix, self.name,)

def scriptfunc(name, group=None, **kwargs):
    """Decorator for scriptfunc functions.
    """
    def wrap(func):
        func = ScriptFunc(name, func, group=group, **kwargs)
        if group is not None:
            if group not in ScriptFunc.funcgroups:
                ScriptFunc.funcgroups[group] = {}
            submap = ScriptFunc.funcgroups[group]
            submap[name] = func
        return func
    return wrap

def define_globals():
    
    @scriptfunc('print', group='_', yieldy=True)
    def global_print(*ls, sep=' '):
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('print() in non-printing context')
        if not ls:
            # print() is a no-op, because we don't care about blank lines.
            return
        if sep is not None:
            sep = str(sep)
        first = True
        for obj in ls:
            if first:
                first = False
            else:
                if sep:
                    ctx.accum.append(sep)
            res = yield ctx.evalobj(obj, evaltype=EVALTYPE_RAW)
            if not (res is None or res == ''):
                ctx.accum_append(str(res), raw=True)
        # We used raw mode, but if the ctx is in cooked mode, we'll fake
        # in WordNode state at the end.
        if ctx.cooked and ctx.textstate is twcommon.gentext.RunOnNode:
            ctx.textstate = twcommon.gentext.WordNode

    @scriptfunc('style', group='_')
    def global_style(style):
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('style() in non-printing context')
        nod = twcommon.interp.Style(style)
        # Non-printing element, append directly
        ctx.accum.append(nod.describe())
        
    @scriptfunc('endstyle', group='_')
    def global_endstyle(style):
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('endstyle() in non-printing context')
        nod = twcommon.interp.EndStyle(style)
        # Non-printing element, append directly
        ctx.accum.append(nod.describe())
        
    @scriptfunc('link', group='_')
    def global_link(target, external=False):
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('link() in non-printing context')
        # Assemble an appropriate desc element. Same as interpolate_text() in
        # evalctx.py.
        # Non-printing element, append directly.
        if external:
            if not twcommon.interp.Link.looks_url_like(target):
                raise Exception('External link target does not look like a URL: %s' % (target,))
            ctx.accum.append(['exlink', target.strip()])
        else:
            ackey = EvalPropContext.build_action_key()
            if twcommon.misc.is_typed_dict(target, 'code'):
                target = target.get('text', '')
            ctx.linktargets[ackey] = str(target)
            ctx.accum.append(['link', ackey])
        
    @scriptfunc('endlink', group='_')
    def global_endlink(external=False):
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('endlink() in non-printing context')
        nod = twcommon.interp.EndLink(external=external)
        # Non-printing element, append directly
        ctx.accum.append(nod.describe())
        
    @scriptfunc('parabreak', group='_')
    def global_parabreak():
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('parabreak() in non-printing context')
        nod = twcommon.interp.ParaBreak()
        # Non-printing element, append directly
        ctx.accum.append(nod.describe())
        
    @scriptfunc('locals', group='_')
    def global_locals():
        """Return a dictionary that reflects the current set of local
        variables. (Not properties or builtins.)
        """
        ctx = EvalPropContext.get_current_context()
        return ctx.frame.locals
        
    @scriptfunc('log', group='_')
    def global_log(*ls):
        """Log a message to the server log. Only works if debug is set
        in the server config file.
        """
        ctx = EvalPropContext.get_current_context()
        if ctx.app.opts.debug:
            ctx.app.log.info(*ls)
        
    @scriptfunc('text', group='_')
    def global_text(object=''):
        """Wrap a string as a {text} object, so that its markup will get
        interpreted.
        """
        if twcommon.misc.is_typed_dict(object, 'text'):
            return object
        if twcommon.misc.is_typed_dict(object, 'code') or twcommon.misc.is_typed_dict(object, 'gentext'):
            return { 'type':'text', 'text':object.get('text', '') }
        return { 'type':'text', 'text':str(object) }

    @scriptfunc('code', group='_')
    def global_code(object='', args=None):
        """Wrap a string as a {code} object.
        """
        if twcommon.misc.is_typed_dict(object, 'code'):
            # Replace the args if args are given. If args are not given,
            # return the object unchanged.
            if args:
                res = dict(object)
                res['args'] = args
                return res
            return object
        if twcommon.misc.is_typed_dict(object, 'text') or twcommon.misc.is_typed_dict(object, 'gentext'):
            # Convert the {text} into {code}
            object = object.get('text', '')
        res = { 'type':'code', 'text':str(object) }
        if args:
            res['args'] = args
        return res

    @scriptfunc('isinstance', group='_')
    def global_isinstance(object, typ):
        """The isinstance function.
        This is special-cased to handle a few "type constructors" which are
        not true Python types: text, code, ObjectId, datetime.
        (Note that timedelta *is* a Python type, however.)
        """
        if isinstance(typ, tuple):
            # isinstance(foo, (x,y,z)) checks whether foo is any of the
            # types (x,y,z). Betcha didn't know that.
            for subtyp in typ:
                if global_isinstance.func(object, subtyp):
                    return True
            return False
        if typ is global_objectid:
            return isinstance(object, ObjectId)
        if typ is global_code:
            return isinstance(object, dict) and object.get('type', None) == 'code'
        if typ is global_text:
            return isinstance(object, dict) and object.get('type', None) == 'text'
        if typ is gentext_gentext:
            return isinstance(object, dict) and object.get('type', None) == 'gentext'
        if typ is datetime_datetime:
            return isinstance(object, datetime.datetime)
        return isinstance(object, typ)

    @scriptfunc('ObjectId', group='_')
    def global_objectid(oid=None):
        """The ObjectId constructor. We extend this to handle player and
        location objects.
        """
        if (isinstance(oid, two.execute.PlayerProxy)):
            return oid.uid
        if (isinstance(oid, two.execute.LocationProxy)):
            return oid.locid
        ### RealmProxy? (wid or iid?)
        return ObjectId(oid)

    @scriptfunc('setfocus', group='_', yieldy=True)
    def global_setfocus(symbol, player=None):
        """Set the given player's focus to this symbol. (If player is None,
        the current player; if a location, then every player in it; if
        the realm, then every player in the instance.)
        """
        ctx = EvalPropContext.get_current_context()
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('setfocus: may only occur in action code')
        if type(symbol) is not str:
            raise TypeError('setfocus: symbol must be string')

        uid = None
        query = None
        
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        elif isinstance(player, two.execute.RealmProxy):
            query = { 'iid':ctx.loctx.iid }
        elif isinstance(player, two.execute.LocationProxy):
            query = { 'iid':ctx.loctx.iid, 'locid':player.locid }
        else:
            raise TypeError('setfocus: must be player, location, realm, or None')
        if uid is not None:
            # Focus exactly one player.
            res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                                 {'_id':uid},
                                 {'iid':1, 'focus':1})
            if not res:
                raise KeyError('No such player')
            if res['iid'] != ctx.loctx.iid:
                raise Exception('Player is not in this instance')
            yield motor.Op(ctx.app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':symbol}})
            ctx.task.set_dirty(uid, DIRTY_FOCUS)
        elif query is not None:
            # Focus all matching players
            uids = []
            cursor = ctx.app.mongodb.playstate.find(query,
                                                    {'_id':1})
            while (yield cursor.fetch_next):
                player = cursor.next_object()
                uids.append(player['_id'])
            # cursor autoclose
            if uids:
                yield motor.Op(ctx.app.mongodb.playstate.update,
                               query,
                               {'$set':{'focus':symbol}}, multi=True)
                ctx.task.set_dirty(uids, DIRTY_FOCUS)
        
    @scriptfunc('unfocus', group='_', yieldy=True)
    def global_unfocus(symbol=None, player=None):
        """Defocus the given player. (If player is None,
        the current player; if a location, then every player in it; if
        the realm, then every player in the instance.)
        This closes the focus pane, if it's open.
        If the symbol argument is not None, only defocus players with the
        given focus string value.
        """
        ctx = EvalPropContext.get_current_context()
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('unfocus: may only occur in action code')
        if symbol and type(symbol) is not str:
            raise TypeError('unfocus: symbol must be string')

        uid = None
        query = None
        
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        elif isinstance(player, two.execute.RealmProxy):
            query = { 'iid':ctx.loctx.iid }
            if symbol:
                query['focus'] = symbol
            else:
                query['focus'] = { '$ne':None }
        elif isinstance(player, two.execute.LocationProxy):
            query = { 'iid':ctx.loctx.iid, 'locid':player.locid }
            if symbol:
                query['focus'] = symbol
            else:
                query['focus'] = { '$ne':None }
        else:
            raise TypeError('unfocus: must be player, location, realm, or None')
        
        if uid is not None:
            # Unfocus at most one player.
            res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                                 {'_id':uid},
                                 {'iid':1, 'focus':1})
            if not res:
                raise KeyError('No such player')
            if res['iid'] != ctx.loctx.iid:
                raise Exception('Player is not in this instance')
            if symbol and res['focus'] != symbol:
                pass  # Do nothing
            elif res['focus'] == None:
                pass  # Do nothing
            else:
                yield motor.Op(ctx.app.mongodb.playstate.update,
                               {'_id':uid},
                               {'$set':{'focus':None}})
                ctx.task.set_dirty(uid, DIRTY_FOCUS)
        elif query is not None:
            # Unfocus all matching players
            uids = []
            cursor = ctx.app.mongodb.playstate.find(query,
                                                    {'_id':1})
            while (yield cursor.fetch_next):
                player = cursor.next_object()
                uids.append(player['_id'])
            # cursor autoclose
            if uids:
                yield motor.Op(ctx.app.mongodb.playstate.update,
                               query,
                               {'$set':{'focus':None}}, multi=True)
                ctx.task.set_dirty(uids, DIRTY_FOCUS)

    @scriptfunc('event', group='_', yieldy=True)
    def global_event(you, others=None, player=None):
        """Send an event message to the current player, like {event}.
        The argument(s) must be string or {text}. The optional second
        argument goes to other players in the same location.
        If the player argument is provided, the event refers to that
        player instead -- but they must be in-world.
        """
        ctx = EvalPropContext.get_current_context()
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Events may only occur in action code')
        
        youeval = False
        otherseval = False
        if you:
            if is_typed_dict(you, 'text'):
                you = you.get('text', None)
                youeval = True
            else:
                you = str(you)
        if others:
            if is_typed_dict(others, 'text'):
                others = others.get('text', None)
                otherseval = True
            else:
                others = str(others)

        if player is None:
            yield ctx.perform_event(you, youeval, others, otherseval)
        elif isinstance(player, two.execute.PlayerProxy):
            res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                                 {'_id':player.uid},
                                 {'iid':1})
            if not res:
                raise KeyError('No such player')
            if res['iid'] != ctx.loctx.iid:
                raise Exception('Player is not in this instance')
            yield ctx.perform_event_player(player.uid, you, youeval, others, otherseval)
        else:
            raise TypeError('event: must be player or None')
            

    @scriptfunc('eventloc', group='_', yieldy=True)
    def global_eventloc(loc, all):
        """Send an event message to all players in the given location.
        (Location or key, or the entire realm.)
        """
        ctx = EvalPropContext.get_current_context()
        iid = ctx.loctx.iid
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Events may only occur in action code')
       
        if isinstance(loc, two.execute.RealmProxy):
            locid = None
        elif isinstance(loc, two.execute.LocationProxy):
            res = yield motor.Op(ctx.app.mongodb.locations.find_one,
                                 {'_id':loc.locid, 'wid':ctx.loctx.wid},
                                 {'_id':1})
            if not res:
                raise KeyError('No such location')
            locid = loc.locid
        else:
            res = yield motor.Op(ctx.app.mongodb.locations.find_one,
                                 {'key':loc, 'wid':ctx.loctx.wid},
                                 {'_id':1})
            if not res:
                raise KeyError('No such location: %s' % (loc,))
            locid = res['_id']
            
        if is_typed_dict(all, 'text'):
            all = all.get('text', None)
            subctx = EvalPropContext(ctx.task, parent=ctx, level=LEVEL_MESSAGE)
            val = yield subctx.eval(all, evaltype=EVALTYPE_TEXT)
        else:
            val = str(all)
                
        others = yield ctx.task.find_location_players(iid, locid)
        ctx.task.write_event(others, val)
        
    @scriptfunc('panic', group='_', yieldy=True)
    def global_panic(you=None, others=None, player=None):
        """Panic a player out, optionally displaying messages first.
        The you and others arguments must be string or {text}. The player
        argument must be a PlayerProxy or None (the current player).
        """
        ctx = EvalPropContext.get_current_context()
        
        if player is None:
            pass
        elif isinstance(player, two.execute.PlayerProxy):
            pass
        else:
            raise TypeError('panic: player must be a player or None')

        youeval = False
        otherseval = False
        if you:
            if is_typed_dict(you, 'text'):
                you = you.get('text', None)
                youeval = True
            else:
                you = str(you)
        if others:
            if is_typed_dict(others, 'text'):
                others = others.get('text', None)
                otherseval = True
            else:
                others = str(others)
                
        yield ctx.perform_panic(you, youeval, others, otherseval, player=player)
        
    @scriptfunc('move', group='_', yieldy=True)
    def global_move(dest, you=None, oleave=None, oarrive=None, player=None):
        """Move a player to another location in the same world, like {move}.
        The first argument must be a location or location key. The you, oleave,
        and oarrive arguments must be string or {text}; they are messages
        displayed for the player and other players. The player argument
        must be a PlayerProxy or None (the current player).
        """
        ctx = EvalPropContext.get_current_context()
        
        if isinstance(dest, two.execute.LocationProxy):
            res = yield motor.Op(ctx.app.mongodb.locations.find_one,
                                 {'_id':dest.locid, 'wid':ctx.loctx.wid},
                                 {'_id':1})
            if not res:
                raise KeyError('No such location')
            locid = dest.locid
        else:
            res = yield motor.Op(ctx.app.mongodb.locations.find_one,
                                 {'key':dest, 'wid':ctx.loctx.wid},
                                 {'_id':1})
            if not res:
                raise KeyError('No such location: %s' % (dest,))
            locid = res['_id']

        if player is None:
            pass
        elif isinstance(player, two.execute.PlayerProxy):
            pass
        else:
            raise TypeError('move: player must be a player or None')
            
        youeval = False
        oleaveeval = False
        oarriveeval = False
        if you:
            if is_typed_dict(you, 'text'):
                you = you.get('text', None)
                youeval = True
            else:
                you = str(you)
        if oleave:
            if is_typed_dict(oleave, 'text'):
                oleave = oleave.get('text', None)
                oleaveeval = True
            else:
                oleave = str(oleave)
        if oarrive:
            if is_typed_dict(oarrive, 'text'):
                oarrive = oarrive.get('text', None)
                oarriveeval = True
            else:
                oarrive = str(oarrive)
                
        yield ctx.perform_move(locid, you, youeval, oleave, oleaveeval, oarrive, oarriveeval, player=player)
        
    @scriptfunc('location', group='_', yieldy=True)
    def global_location(obj=None):
        """Create a LocationProxy.
        - No argument: the current player's location
        - ObjectId argument: the location with the given identifier
        - LocationProxy argument: returns it unchanged
        - String argument: the location with the given key
        - Player argument: the location of the given player (if in the current world!)
        """
        if obj is None:
            ctx = EvalPropContext.get_current_context()
            if not ctx.uid:
                raise Exception('No current player')
            if not ctx.loctx.locid:
                return None
            if ctx.dependencies is not None:
                ctx.dependencies.add( ('playstate', ctx.uid, 'locid') )
            return two.execute.LocationProxy(ctx.loctx.locid)
        
        if isinstance(obj, ObjectId):
            ctx = EvalPropContext.get_current_context()
            res = yield motor.Op(ctx.app.mongodb.locations.find_one,
                                 {'_id':obj},
                                 {'wid':1})
            if not res:
                raise Exception('No such location')
            if res['wid'] != ctx.loctx.wid:
                raise Exception('Location not in this world')
            return two.execute.LocationProxy(obj)
        
        if isinstance(obj, two.execute.LocationProxy):
            return obj
        
        if isinstance(obj, two.execute.PlayerProxy):
            ctx = EvalPropContext.get_current_context()
            res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                                 {'_id':obj.uid},
                                 {'iid':1, 'locid':1})
            if not res:
                raise KeyError('No such player')
            if res['iid'] != ctx.loctx.iid:
                return None
            if ctx.dependencies is not None:
                ctx.dependencies.add( ('playstate', obj.uid, 'locid') )
            return two.execute.LocationProxy(res['locid'])
        
        ctx = EvalPropContext.get_current_context()
        if not ctx.loctx.wid:
            raise Exception('No current world')
        res = yield motor.Op(ctx.app.mongodb.locations.find_one,
                             {'wid':ctx.loctx.wid, 'key':obj},
                             {'_id':1})
        if not res:
            raise KeyError('No such location: %s' % (obj,))
        return two.execute.LocationProxy(res['_id'])

    @scriptfunc('sched', group='_')
    def global_sched(delta, func, repeat=False, cancel=None):
        """Schedule an event to occur in the future. The delta argument
        must be a timedelta or a number of seconds. The func should be
        a code snippet or {code} object.
        If repeat is true, the event will continue occurring regularly for
        as long as the instance is awake.
        If cancel is provided, the event can be cancelled later with the
        unsched() function.
        """
        ctx = EvalPropContext.get_current_context()
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Timer are only available in action code')
        if not ctx.loctx.iid:
            raise Exception('No current instance')
        app = ctx.app
        instance = app.ipool.get(ctx.loctx.iid)
        if not instance:
            raise Exception('Current instance is not awake')
        if not isinstance(delta, datetime.timedelta):
            delta = datetime.timedelta(seconds=delta)
        instance.add_timer_event(delta, func, repeat=repeat, cancel=cancel)

    @scriptfunc('unsched', group='_')
    def global_unsched(cancel=None):
        """Cancel all upcoming scheduled events for this instance.
        If the cancel argument is given, this only cancels events that
        were set up with the matching cancel argument.
        """
        ctx = EvalPropContext.get_current_context()
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Timer are only available in action code')
        if not ctx.loctx.iid:
            raise Exception('No current instance')
        app = ctx.app
        instance = app.ipool.get(ctx.loctx.iid)
        if not instance:
            raise Exception('Current instance is not awake')
        instance.remove_timer_events(cancel=cancel)

    @scriptfunc('player', group='_propmap')
    def global_player():
        """Create a PlayerProxy for the current player.
        This goes in the propmap group, meaning that the user will invoke
        it as a property object: "_.player", no parens.
        """
        ctx = EvalPropContext.get_current_context()
        if not ctx.uid:
            raise Exception('No current player')
        return two.execute.PlayerProxy(ctx.uid)

    @scriptfunc('lastlocation', group='_propmap', yieldy=True)
    def global_lastlocation():
        """A LocationProxy for the last location (in this world) that
        the player visited.
        This goes in the propmap group, meaning that the user will invoke
        it as a property object: "_.lastlocation", no parens.
        """
        ctx = EvalPropContext.get_current_context()
        if not ctx.uid:
            raise Exception('No current player')
        res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                             {'_id':ctx.uid},
                             {'iid':1, 'lastlocid':1})
        if not res:
            raise KeyError('No such player')
        if res['iid'] != ctx.loctx.iid:
            raise Exception('Player is not in this instance')
        locid = res.get('lastlocid', None)
        if not locid:
            return None
        return two.execute.LocationProxy(locid)

    @scriptfunc('gentext', group='gentext')
    def gentext_gentext(object=''):
        """Wrap a string as a {gentext} object.
        """
        if twcommon.misc.is_typed_dict(object, 'gentext'):
            # Return the object unchanged.
            return object
        if twcommon.misc.is_typed_dict(object, 'text') or twcommon.misc.is_typed_dict(object, 'code'):
            # Convert the {text} into {gentext}
            object = object.get('text', '')
        res = { 'type':'gentext', 'text':str(object) }
        return res

    @scriptfunc('display', group='gentext', yieldy=True)
    def gentext_display(obj, cooked=None, seed=None):
        ctx = EvalPropContext.get_current_context()
        origseed = ctx.genseed
        if seed is not None:
            ctx.genseed = str(seed).encode()
            
        origcooked = ctx.cooked
        if cooked is not None:
            ctx.set_cooked(cooked)
            
        res = yield ctx.evalobj(obj, evaltype=EVALTYPE_RAW)
        if not (res is None or res == ''):
            ctx.accum_append(str(res))
            
        if cooked is not None:
            ctx.set_cooked(origcooked)

        if seed is not None:
            ctx.genseed = origseed
            
    @scriptfunc('A', group='gentext')
    def gentext_a():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.ANode())
    
    @scriptfunc('An', group='gentext')
    def gentext_an():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.ANode())
    
    @scriptfunc('AForm', group='gentext')
    def gentext_aform():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.AFormNode())
    
    @scriptfunc('AnForm', group='gentext')
    def gentext_anform():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.AnFormNode())
    
    @scriptfunc('RunOn', group='gentext')
    def gentext_runon():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.RunOnExplicitNode())
    
    @scriptfunc('Para', group='gentext')
    def gentext_para():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.ParaNode())
    
    @scriptfunc('Stop', group='gentext')
    def gentext_stop():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.StopNode())
    
    @scriptfunc('Semi', group='gentext')
    def gentext_semi():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.SemiNode())
    
    @scriptfunc('Comma', group='gentext')
    def gentext_comma():
        ctx = EvalPropContext.get_current_context()
        ctx.accum_append(twcommon.gentext.CommaNode())
    
    @scriptfunc('datetime', group='datetime')
    def datetime_datetime(year, month, day, **kwargs):
        """The native datetime constructor, except that tzinfo is always
        UTC.
        """
        kwargs['tzinfo'] = datetime.timezone.utc
        return datetime.datetime(year, month, day, **kwargs)
        
    @scriptfunc('now', group='datetime_propmap')
    def datetime_now():
        """Return the current task's start time.
        This goes in a propmap group, meaning that the user will invoke
        it as a property object: "_.now", no parens.
        """
        ctx = EvalPropContext.get_current_context()
        return ctx.task.starttime

    @scriptfunc('player', group='players', yieldy=True)
    def players_player(player=None):
        """Create or find a PlayerProxy.
        - No argument: the current player
        - ObjectId argument: the player with the given identifier
        - PlayerProxy argument: returns it unchanged
        """
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            return two.execute.PlayerProxy(ctx.uid)
        elif isinstance(player, two.execute.PlayerProxy):
            return player
        elif isinstance(player, ObjectId):
            res = yield motor.Op(ctx.app.mongodb.players.find_one,
                                 {'_id':player},
                                 {'_id':1})
            if not res:
                raise Exception('No such player')
            return two.execute.PlayerProxy(player)
        else:
            raise TypeError('players.player: must be player, ObjectId, or None')
        
    @scriptfunc('name', group='players', yieldy=True)
    def players_name(player=None):
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('players.name: must be player or None')
        res = yield motor.Op(ctx.app.mongodb.players.find_one,
                             {'_id':uid},
                             {'name':1})
        if not res:
            raise Exception('No such player')
        return res.get('name', '???')

    @scriptfunc('pronoun', group='players', yieldy=True)
    def players_pronoun(player=None):
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('players.focus: must be player or None')
        res = yield motor.Op(ctx.app.mongodb.players.find_one,
                             {'_id':uid},
                             {'pronoun':1})
        if not res:
            raise Exception('No such player')
        # Could set up a pronoun dependency here.
        return res['pronoun']
        
    @scriptfunc('builder', group='players', yieldy=True)
    def players_builder(player=None):
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('players.builder: must be player or None')
        res = yield motor.Op(ctx.app.mongodb.players.find_one,
                             {'_id':uid},
                             {'build':1})
        if not res:
            raise Exception('No such player')
        return res.get('build', False)

    @scriptfunc('isguest', group='players', yieldy=True)
    def players_isguest(player=None):
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('players.isguest: must be player or None')
        res = yield motor.Op(ctx.app.mongodb.players.find_one,
                             {'_id':uid},
                             {'guest':1})
        if not res:
            raise Exception('No such player')
        return res.get('guest', False)

    @scriptfunc('ishere', group='players', yieldy=True)
    def players_ishere(player=None):
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('players.ishere: must be player or None')
        res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                             {'_id':uid},
                             {'iid':1})
        if not res:
            raise Exception('No such player')
        if ctx.loctx.iid and ctx.loctx.iid == res.get('iid', None):
            return True
        else:
            return False

    @scriptfunc('focus', group='players', yieldy=True)
    def players_focus(player=None):
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('players.focus: must be player or None')
        res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                             {'_id':uid},
                             {'focus':1})
        if not res:
            raise Exception('No such player')
        return res.get('focus', None)
        
    @scriptfunc('count', group='players', yieldy=True)
    def players_count(loc):
        """Number of players in a location or the instance.
        """
        ctx = EvalPropContext.get_current_context()
        iid = ctx.loctx.iid
        if not iid:
            raise Exception('No current instance')
        if isinstance(loc, two.execute.RealmProxy):
            cursor = ctx.app.mongodb.playstate.find({'iid':iid},
                                                    {'_id':1})
            # Could have a dependency on ('populace', iid, None). But then
            # we'd have to ping it whenever a player moved in the instance,
            # and I'm not sure it's worth the effort.
        elif isinstance(loc, two.execute.LocationProxy):
            cursor = ctx.app.mongodb.playstate.find({'iid':iid, 'locid':loc.locid},
                                                    {'_id':1})
            if ctx.dependencies is not None:
                ctx.dependencies.add( ('populace', iid, loc.locid) )
        else:
            raise TypeError('players.count: must be location or realm')
        res = yield motor.Op(cursor.count)
        # cursor autoclose
        return res

    @scriptfunc('list', group='players', yieldy=True)
    def players_list(loc):
        """List of players in a location or the instance.
        """
        ctx = EvalPropContext.get_current_context()
        iid = ctx.loctx.iid
        if not iid:
            raise Exception('No current instance')
        if isinstance(loc, two.execute.RealmProxy):
            cursor = ctx.app.mongodb.playstate.find({'iid':iid},
                                                    {'_id':1})
            # Could have a dependency on ('populace', iid, None). But then
            # we'd have to ping it whenever a player moved in the instance,
            # and I'm not sure it's worth the effort.
        elif isinstance(loc, two.execute.LocationProxy):
            cursor = ctx.app.mongodb.playstate.find({'iid':iid, 'locid':loc.locid},
                                                    {'_id':1})
            if ctx.dependencies is not None:
                ctx.dependencies.add( ('populace', iid, loc.locid) )
        else:
            raise TypeError('players.count: must be location or realm')
        res = []
        while (yield cursor.fetch_next):
            player = cursor.next_object()
            res.append(two.execute.PlayerProxy(player['_id']))
        # cursor autoclose
        return res

    @scriptfunc('resolve', group='pronoun', yieldy=True)
    def pronoun_resolve(pronoun, player=None):
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('players.focus: must be player or None')
        res = yield motor.Op(ctx.app.mongodb.players.find_one,
                             {'_id':uid},
                             {'pronoun':1, 'name':1})
        if not res:
            raise Exception('No such player')
        # Could set up a pronoun dependency here.
        return two.grammar.resolve_pronoun(res, pronoun)
        
    @scriptfunc('We', group='pronoun', yieldy=True)
    def pronoun_We(player=None):
        res = yield pronoun_resolve.yieldfunc('We', player)
        return res
    @scriptfunc('we', group='pronoun', yieldy=True)
    def pronoun_we(player=None):
        res = yield pronoun_resolve.yieldfunc('we', player)
        return res
    @scriptfunc('Us', group='pronoun', yieldy=True)
    def pronoun_Us(player=None):
        res = yield pronoun_resolve.yieldfunc('Us', player)
        return res
    @scriptfunc('us', group='pronoun', yieldy=True)
    def pronoun_us(player=None):
        res = yield pronoun_resolve.yieldfunc('us', player)
        return res
    @scriptfunc('Our', group='pronoun', yieldy=True)
    def pronoun_Our(player=None):
        res = yield pronoun_resolve.yieldfunc('Our', player)
        return res
    @scriptfunc('our', group='pronoun', yieldy=True)
    def pronoun_our(player=None):
        res = yield pronoun_resolve.yieldfunc('our', player)
        return res
    @scriptfunc('Ours', group='pronoun', yieldy=True)
    def pronoun_Ours(player=None):
        res = yield pronoun_resolve.yieldfunc('Ours', player)
        return res
    @scriptfunc('ours', group='pronoun', yieldy=True)
    def pronoun_ours(player=None):
        res = yield pronoun_resolve.yieldfunc('ours', player)
        return res
    @scriptfunc('Ourself', group='pronoun', yieldy=True)
    def pronoun_Ourself(player=None):
        res = yield pronoun_resolve.yieldfunc('Ourself', player)
        return res
    @scriptfunc('ourself', group='pronoun', yieldy=True)
    def pronoun_ourself(player=None):
        res = yield pronoun_resolve.yieldfunc('ourself', player)
        return res
    @scriptfunc('They', group='pronoun', yieldy=True)
    def pronoun_They(player=None):
        res = yield pronoun_resolve.yieldfunc('We', player)
        return res
    @scriptfunc('they', group='pronoun', yieldy=True)
    def pronoun_they(player=None):
        res = yield pronoun_resolve.yieldfunc('we', player)
        return res
    @scriptfunc('Them', group='pronoun', yieldy=True)
    def pronoun_Them(player=None):
        res = yield pronoun_resolve.yieldfunc('Us', player)
        return res
    @scriptfunc('them', group='pronoun', yieldy=True)
    def pronoun_them(player=None):
        res = yield pronoun_resolve.yieldfunc('us', player)
        return res
    @scriptfunc('Their', group='pronoun', yieldy=True)
    def pronoun_Their(player=None):
        res = yield pronoun_resolve.yieldfunc('Our', player)
        return res
    @scriptfunc('their', group='pronoun', yieldy=True)
    def pronoun_their(player=None):
        res = yield pronoun_resolve.yieldfunc('our', player)
        return res
    @scriptfunc('Theirs', group='pronoun', yieldy=True)
    def pronoun_Theirs(player=None):
        res = yield pronoun_resolve.yieldfunc('Ours', player)
        return res
    @scriptfunc('theirs', group='pronoun', yieldy=True)
    def pronoun_theirs(player=None):
        res = yield pronoun_resolve.yieldfunc('ours', player)
        return res
    @scriptfunc('Themself', group='pronoun', yieldy=True)
    def pronoun_Themself(player=None):
        res = yield pronoun_resolve.yieldfunc('Ourself', player)
        return res
    @scriptfunc('themself', group='pronoun', yieldy=True)
    def pronoun_themself(player=None):
        res = yield pronoun_resolve.yieldfunc('ourself', player)
        return res
    
    @scriptfunc('realm', group='worlds', yieldy=True)
    def worlds_realm(key, index=0):
        ctx = EvalPropContext.get_current_context()
        
        origworld = yield motor.Op(ctx.app.mongodb.worlds.find_one,
                                   {'_id':ctx.loctx.wid},
                                   {'creator':1})
        if not origworld:
            raise Exception('worlds.realm: Cannot find current world')
        
        plist = yield motor.Op(ctx.app.mongodb.portlists.find_one,
                               {'wid':ctx.loctx.wid, 'key':key, 'type':'world'},
                               {'_id':1})
        if not plist:
            raise Exception('worlds.realm: No such plist: %s' % (key,))
        plistid = plist['_id']

        # Take the Nth (world-level) portal in this list.
        portal = yield motor.Op(ctx.app.mongodb.portals.find_one,
                                {'plistid':plistid, 'iid':None},
                                sort=[('listpos', 1)],
                                skip=index)
        if not portal:
            raise Exception('worlds.realm: Plist %s does not have %d portals' % (key, index))

        newwid = portal['wid']
        world = yield motor.Op(ctx.app.mongodb.worlds.find_one,
                               {'_id':portal['wid']})
        if not world:
            raise Exception('worlds.realm: No such world')

        # Create an object which represents what we can do to the remote
        # world.
        perms = twcommon.access.RemoteAccessMap(world, origworld)
        if not perms.allaccess:
            # This may raise an immediate exception, if we have no access
            # entries for the given world at all.
            yield perms.loadentries(ctx.app)

        newscid = yield two.execute.portal_resolve_scope(ctx.app, portal, ctx.uid, ctx.loctx.scid, world)
        
        instance = yield motor.Op(ctx.app.mongodb.instances.find_one,
                                  {'wid':newwid, 'scid':newscid},
                                  {'_id':1})
        
        if instance:
            newiid = instance['_id']
        else:
            # Create the instance, although we will not awaken it.
            # Note that we do not reset the tick count; the on_init
            # hook counts against the caller's tick quota.
            newiid = yield motor.Op(ctx.app.mongodb.instances.insert,
                                    {'wid':newwid, 'scid':newscid})
            ctx.app.log.info('Created instance (for prop-access) %s (world %s, scope %s)', newiid, newwid, newscid)
            newloctx = two.task.LocContext(None, wid=newwid, scid=newscid, iid=newiid)
            yield two.execute.try_hook(ctx.task, 'on_init', newloctx, 'initing instance (prop-access)')

        return two.execute.RemoteRealmProxy(newwid, newscid, newiid, perms=perms, worldname=world.get('name', '???'))
        
    @scriptfunc('choice', group='random')
    def random_choice(seq):
        """Choose a random member of a list.
        """
        return random.choice(seq)

    @scriptfunc('randint', group='random')
    def random_randint(a, b):
        """Return a random integer in range [a, b], including both end
        points.
        """
        return random.randint(a, b)

    @scriptfunc('randrange', group='random')
    def random_randrange(start, stop=None, step=1):
        """Return a random integer from range(start, stop[, step]).
        """
        return random.randrange(start, stop=stop, step=1)
    
    @scriptfunc('partial', group='functools')
    def functools_partial(func, *args, **keywords):
        """Return a partial function application. The func must be a
        {code} object or other callable.
        """
        return ScriptPartialFunc(func, args, keywords)
    
    @scriptfunc('level', group='access', yieldy=True)
    def access_level(player=None, level=None):
        """Return the access level of the given player (or the current player)
        in the given scope.
        If level is given, returns whether this access level is at least
        that value.
        """
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        elif isinstance(player, two.execute.PlayerProxy):
            uid = player.uid
        else:
            raise TypeError('access.level: must be player or None')
        acclevel = yield two.execute.scope_access_level(ctx.app, uid, ctx.loctx.wid, ctx.loctx.scid)
        if level is None:
            return acclevel
        else:
            return (acclevel >= level)
        
    @scriptfunc('list_sort', group='builtinmethods', yieldy=True)
    def functools_list_sort(ls, key=None, reverse=False):
        """Wrapper for list.sort(). Sorts the list in place.
        If key is {code} or a callable, it is applied to each list element
        to produce a sorting key. If reverse is True, the order is reversed.
        """
        if key is None:
            # The simple case (no code called, non-yieldy)
            list.sort(ls, reverse=reverse)
            return
        # The code-calling case is ugly and not very efficient. Too bad.
        ctx = EvalPropContext.get_current_context()
        tmpls = []
        nokwargs = {}
        for val in ls:
            kval = yield ctx.exec_call_object(key, (val,), nokwargs)
            tmpls.append( (kval, val) )
        list.sort(tmpls, key=lambda tup:tup[0], reverse=reverse)
        ls[:] = [ tup[1] for tup in tmpls ]
        return
    
    # Copy the collection of top-level functions.
    globmap = dict(ScriptFunc.funcgroups['_'])
    
    # Add some stuff to it.
    globmap['int'] = int
    globmap['str'] = str
    globmap['bool'] = bool
    globmap['list'] = list
    globmap['dict'] = dict
    globmap['set'] = set
    globmap['len'] = len
    globmap['max'] = max
    globmap['min'] = min
    globmap['realm'] = two.execute.RealmProxy()
    globmap['locations'] = two.execute.WorldLocationsProxy()
    
    map = dict(ScriptFunc.funcgroups['random'])
    globmap['random'] = ScriptNamespace(map)

    map = dict(ScriptFunc.funcgroups['players'])
    map['location'] = globmap['location']
    globmap['players'] = ScriptNamespace(map)

    map = dict(ScriptFunc.funcgroups['pronoun'])
    globmap['pronoun'] = ScriptNamespace(map)

    map = dict(ScriptFunc.funcgroups['functools'])
    globmap['functools'] = ScriptNamespace(map)
    
    map = dict(ScriptFunc.funcgroups['access'])
    # Add in all the access level names (as uppercase symbols)
    map.update(twcommon.access.map)
    globmap['access'] = ScriptNamespace(map)

    map = dict(ScriptFunc.funcgroups['worlds'])
    globmap['worlds'] = ScriptNamespace(map)

    map = dict(ScriptFunc.funcgroups['gentext'])
    globmap['gentext'] = ScriptNamespace(map)

    map = dict(ScriptFunc.funcgroups['datetime'])
    # Expose some type constructors directly
    map['timedelta'] = datetime.timedelta
    propmap = dict(ScriptFunc.funcgroups['datetime_propmap'])
    globmap['datetime'] = ScriptNamespace(map, propmap)

    map = dict(ScriptFunc.funcgroups['builtinmethods'])
    globmap['builtinmethods'] = ScriptNamespace(map)
    
    # And a few entries that are generated each time they're fetched.
    propmap = dict(ScriptFunc.funcgroups['_propmap'])

    ### Run this through a site-specific Python hook.

    # And that's our global namespace.
    return ScriptNamespace(globmap, propmap)

# Set of native callables which script code can call.
callable_ok_set = frozenset([
        # Simple top-level builtins
        int, str, bool, list, dict, set, len, max, min,
        # Other native types
        datetime.timedelta, ObjectId,
        # Class methods which are never called as instance methods
        dict.fromkeys,
        ])

# Condensing the above for fast access: the set of id()s of valid callables.
callable_ok_idset = frozenset({ id(val) for val in callable_ok_set })

# Is this type (the type of built-in methods) named in the standard library?
# It's not types.BuiltinMethodType, annoyingly.
MethodDescriptorType = type(str.lower)

# Table of what attributes can be read from what types. Used by
# type_getattr_perform().
#
# Some type methods are omitted, or wrapped, because they invoke
# arbitrary code without Tworld limitations. For example,
# list.sort(key=foo) will invoke foo as a Python function. If foo were
# somehow evil (a native infinite loop), it would hang the
# interpreter. Contrariwise, if foo were a valid {code} object, it
# would fail. We want to avoid both of these outcomes.
#
# Therefore, the table contains True for unfettered access (can both
# get and call the native method). False or a missing entry means no
# access is allowed. A string means that the getattr returns a
# ScriptFunction wrapper, from the builtinmethods namespace.
#
def type_getattr_construct(ls, **kwargs):
    """Utility to build a type_getattr_table entry. Used only at module
    load time.
    """
    map = dict.fromkeys(ls, True)
    map.update(kwargs)
    return map
    
type_getattr_table = {
    datetime.timedelta: type_getattr_construct(
        ['days', 'max', 'microseconds', 'min', 'resolution', 'seconds', 'total_seconds']),
    datetime.datetime: type_getattr_construct(
        ['min', 'max', 'resolution', 'year', 'month', 'day', 'hour', 'minute', 'second', 'microsecond']),
    str: type_getattr_construct(
        ['capitalize', 'casefold', 'center', 'count', 'endswith', 'find', 'index', 'isalnum', 'isalpha', 'isdecimal', 'isdigit', 'isidentifier', 'islower', 'isnumeric', 'isprintable', 'isspace', 'istitle', 'isupper', 'join', 'ljust', 'lower', 'lstrip', 'partition', 'replace', 'rfind', 'rindex', 'rjust', 'rpartition', 'rsplit', 'rstrip', 'split', 'splitlines', 'startswith', 'strip', 'swapcase', 'title', 'upper', 'zfill']),  # omitted for callness: 'format', 'format_map'
    list: type_getattr_construct(
        ['append', 'clear', 'copy', 'count', 'extend', 'index', 'insert', 'pop', 'remove', 'reverse'],
        sort='list_sort'),
    dict: type_getattr_construct(
        ['clear', 'copy', 'fromkeys', 'get', 'items', 'keys', 'pop', 'popitem', 'setdefault', 'update', 'values']),
    }

# Condensing the above for fast access: the set of id()s of valid types.
type_getattr_idset = frozenset({ id(key) for key in type_getattr_table.keys() })

def type_callable(val):
    """Given an object, is it legitimate to call it? We don't want to
    rely on Python's callable() here; we want to exclude file() and other
    dangerous objects. In fact we want to have a list of *safe* objects
    and exclude everything else.
    
    (This only applies to native Python objects, functions, classes, and
    methods. Script constructs like ScriptCallable and {code} are accepted
    earlier.)
    """
    if id(val) in callable_ok_idset:
        return True
    typ = type(val)
    if typ is types.BuiltinMethodType:
        baseval = val.__self__
        if id(baseval) in type_getattr_idset:
            basetyp = baseval
        else:
            basetyp = type(baseval)
        res = type_getattr_table.get(basetyp, None)
        if not res:
            return False
        flag = res.get(val.__name__, False)
        if flag is True:
            return True
        # reject string entries
        return False
    if typ is MethodDescriptorType:
        res = type_getattr_table.get(val.__objclass__, None)
        if not res:
            return False
        flag = res.get(val.__name__, False)
        if flag is True:
            return True
        # reject string entries
        return False
    return False

def type_getattr_perform(app, val, key):
    """Implement getattr(val, key) with safety checks.
    This is important because unfettered access to foo.__dict__, for
    example, would be catastrophic.
    """
    isbase = (id(val) in type_getattr_idset)
    if isbase:
        typ = val
    else:
        typ = type(val)
    res = type_getattr_table.get(typ, None)
    if not res:
        raise ExecSandboxException('%s.%s: getattr not allowed' % (type(val).__name__, key))
    flag = res.get(key, False)
    if flag is True:
        return getattr(val, key)
    if flag and isinstance(flag, str):
        method = app.global_symbol_table.get('builtinmethods').get(flag)
        if isbase:
            return method
        else:
            return ScriptPartialFunc(method, (val,), {})
    raise ExecSandboxException('%s.%s: getattr not allowed' % (type(val).__name__, key))
    
# These symbols are actually keywords (in Python 3), but they come out of
# ast.parse() as Name nodes. They can never change.
immutable_symbol_table = {
    'True': True, 'False': False, 'None': None,
    }

def is_immutable_symbol(val):
    return (val in immutable_symbol_table)

@tornado.gen.coroutine
def find_symbol(app, loctx, key, locals=None, dependencies=None):
    """Look up a symbol, using the universal laws of symbol-looking-up.
    To wit:
    - "_" and other immutables
    - locals (which may be predefined or start with "_")
    - instance properties
    - world properties
    - realm-level instance properties
    - realm-level world properties
    - builtins
    ### We could change the first argument to ctx and take the dependencies
    ### from there, though.
    """
    # Special cases
    if key == '_':
        return app.global_symbol_table
    if key in immutable_symbol_table:
        return immutable_symbol_table[key]
    if (locals is not None) and (key in locals):
        return locals[key]
    if key.startswith('_'):
        if locals is None:
            raise NameError('Temporary variables not available ("%s")' % (key,))
        if key in locals:
            return locals[key]
        raise NameError('Temporary variable "%s" is not found' % (key,))

    # Property cases
    wid = loctx.wid
    iid = loctx.iid
    locid = loctx.locid
    
    if (locid is not None) and (iid is not None):
        res = yield app.propcache.get(('instanceprop', iid, locid, key),
                                      dependencies=dependencies)
        if res:
            return res.val
    
    if locid is not None:
        res = yield app.propcache.get(('worldprop', wid, locid, key),
                                      dependencies=dependencies)
        if res:
            return res.val

    if iid is not None:
        res = yield app.propcache.get(('instanceprop', iid, None, key),
                                      dependencies=dependencies)
        if res:
            return res.val

    if True:
        res = yield app.propcache.get(('worldprop', wid, None, key),
                                      dependencies=dependencies)
        if res:
            return res.val

    if app.global_symbol_table.has(key):
        (res, yieldy) = app.global_symbol_table.getyieldy(key)
        if yieldy:
            res = yield res()
        return res

    raise SymbolError('Name "%s" is not found' % (key,))


# Late imports, to avoid circularity
from twcommon.misc import is_typed_dict
from twcommon.excepts import SymbolError, ExecSandboxException
import twcommon.access
import twcommon.interp
import twcommon.gentext
import two.grammar
import two.execute
import two.ipool
from two.evalctx import EvalPropContext
from two.task import DIRTY_FOCUS
from two.evalctx import LEVEL_EXECUTE, LEVEL_MESSAGE
from two.evalctx import EVALTYPE_RAW, EVALTYPE_TEXT
