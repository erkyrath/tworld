import types
import itertools
import random
import datetime

import tornado.gen
from bson.objectid import ObjectId
import motor

from twcommon.excepts import SymbolError

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
            if isinstance(funcval, ScriptFunc):
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
            if isinstance(funcval, ScriptFunc):
                if not funcval.yieldy:
                    return (funcval.func(), False)
                else:
                    return (funcval.yieldfunc, True)
            return (funcval(), False)
        return (self.map[key], False)

    def has(self, key):
        return (key in self.map) or (key in self.propmap)

class ScriptFunc:
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
    
    @scriptfunc('print', group='_')
    def global_print(*ls):
        res = ' '.join(str(val) for val in ls)
        ###?

    @scriptfunc('style', group='_')
    def global_style(style):
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('style() in non-printing context')
        nod = twcommon.interp.Style(style)
        ctx.accum.append(nod.describe())
        return '' ### tacky
        
    @scriptfunc('endstyle', group='_')
    def global_endstyle(style):
        ctx = EvalPropContext.get_current_context()
        if ctx.accum is None:
            raise Exception('endstyle() in non-printing context')
        nod = twcommon.interp.EndStyle(style)
        ctx.accum.append(nod.describe())
        return '' ### tacky
        
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
        return { 'type':'text', 'text':str(object) }

    @scriptfunc('isinstance', group='_')
    def global_isinstance(object, typ):
        """The isinstance function.
        ### Special-case to handle text, ObjectId "types"?
        """
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
        raise Exception('###')
        
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
        
    @scriptfunc('move', group='_', yieldy=True)
    def global_move(dest, you=None, oleave=None, oarrive=None):
        """Move the player to another location in the same world, like {move}.
        The first argument must be a location or location key. The rest
        of the arguments must be string or {text}; they are messages displayed
        for the player and other players.
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
                
        yield ctx.perform_move(locid, you, youeval, oleave, oleaveeval, oarrive, oarriveeval)
        
    @scriptfunc('location', group='_', yieldy=True)
    def global_location(obj=None):
        """Create a LocationProxy.
        - No argument: the current player's location
        - String argument: the location with the given key
        - Player argument: the location of the given player (if in the current world!)
        """
        if obj is None:
            ctx = EvalPropContext.get_current_context()
            if not ctx.uid:
                raise Exception('No current player')
            if not ctx.loctx.locid:
                return None
            return two.execute.LocationProxy(ctx.loctx.locid)
        
        if isinstance(obj, two.execute.PlayerProxy):
            ctx = EvalPropContext.get_current_context()
            res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                                 {'_id':obj.uid},
                                 {'iid':1, 'locid':1})
            if not res:
                raise KeyError('No such player')
            if res['iid'] != ctx.loctx.iid:
                return None
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

    @scriptfunc('now', group='datetime_propmap')
    def global_datetime_now():
        """Return the current task's start time.
        This goes in a propmap group, meaning that the user will invoke
        it as a property object: "_.now", no parens.
        """
        ctx = EvalPropContext.get_current_context()
        return ctx.task.starttime

    @scriptfunc('player', group='players', yieldy=True)
    def global_players_player(player=None):
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
    def global_players_name(player=None):
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
    def global_players_pronoun(player=None):
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
        
    @scriptfunc('ishere', group='players', yieldy=True)
    def global_players_ishere(player=None):
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
    def global_players_focus(player=None):
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
    def global_players_count(loc):
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
    def global_players_list(loc):
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
    def global_pronoun_resolve(pronoun, player=None):
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
    def global_pronoun_We(player=None):
        res = yield global_pronoun_resolve.yieldfunc('We', player)
        return res
    @scriptfunc('we', group='pronoun', yieldy=True)
    def global_pronoun_we(player=None):
        res = yield global_pronoun_resolve.yieldfunc('we', player)
        return res
    @scriptfunc('Us', group='pronoun', yieldy=True)
    def global_pronoun_Us(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Us', player)
        return res
    @scriptfunc('us', group='pronoun', yieldy=True)
    def global_pronoun_us(player=None):
        res = yield global_pronoun_resolve.yieldfunc('us', player)
        return res
    @scriptfunc('Our', group='pronoun', yieldy=True)
    def global_pronoun_Our(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Our', player)
        return res
    @scriptfunc('our', group='pronoun', yieldy=True)
    def global_pronoun_our(player=None):
        res = yield global_pronoun_resolve.yieldfunc('our', player)
        return res
    @scriptfunc('Ours', group='pronoun', yieldy=True)
    def global_pronoun_Ours(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Ours', player)
        return res
    @scriptfunc('ours', group='pronoun', yieldy=True)
    def global_pronoun_ours(player=None):
        res = yield global_pronoun_resolve.yieldfunc('ours', player)
        return res
    @scriptfunc('Ourself', group='pronoun', yieldy=True)
    def global_pronoun_Ourself(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Ourself', player)
        return res
    @scriptfunc('ourself', group='pronoun', yieldy=True)
    def global_pronoun_ourself(player=None):
        res = yield global_pronoun_resolve.yieldfunc('ourself', player)
        return res
    @scriptfunc('They', group='pronoun', yieldy=True)
    def global_pronoun_They(player=None):
        res = yield global_pronoun_resolve.yieldfunc('We', player)
        return res
    @scriptfunc('they', group='pronoun', yieldy=True)
    def global_pronoun_they(player=None):
        res = yield global_pronoun_resolve.yieldfunc('we', player)
        return res
    @scriptfunc('Them', group='pronoun', yieldy=True)
    def global_pronoun_Them(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Us', player)
        return res
    @scriptfunc('them', group='pronoun', yieldy=True)
    def global_pronoun_them(player=None):
        res = yield global_pronoun_resolve.yieldfunc('us', player)
        return res
    @scriptfunc('Their', group='pronoun', yieldy=True)
    def global_pronoun_Their(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Our', player)
        return res
    @scriptfunc('their', group='pronoun', yieldy=True)
    def global_pronoun_their(player=None):
        res = yield global_pronoun_resolve.yieldfunc('our', player)
        return res
    @scriptfunc('Theirs', group='pronoun', yieldy=True)
    def global_pronoun_Theirs(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Ours', player)
        return res
    @scriptfunc('theirs', group='pronoun', yieldy=True)
    def global_pronoun_theirs(player=None):
        res = yield global_pronoun_resolve.yieldfunc('ours', player)
        return res
    @scriptfunc('Themself', group='pronoun', yieldy=True)
    def global_pronoun_Themself(player=None):
        res = yield global_pronoun_resolve.yieldfunc('Ourself', player)
        return res
    @scriptfunc('themself', group='pronoun', yieldy=True)
    def global_pronoun_themself(player=None):
        res = yield global_pronoun_resolve.yieldfunc('ourself', player)
        return res
        
    @scriptfunc('choice', group='random')
    def global_random_choice(seq):
        """Choose a random member of a list.
        """
        return random.choice(seq)

    @scriptfunc('randint', group='random')
    def global_random_randint(a, b):
        """Return a random integer in range [a, b], including both end
        points.
        """
        return random.randint(a, b)

    @scriptfunc('randrange', group='random')
    def global_random_randrange(start, stop=None, step=1):
        """Return a random integer from range(start, stop[, step]).
        """
        return random.randrange(start, stop=stop, step=1)
    
    @scriptfunc('level', group='access', yieldy=True)
    def global_access_level(player=None, level=None):
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
    
    # Copy the collection of top-level functions.
    globmap = dict(ScriptFunc.funcgroups['_'])
    
    # Add some stuff to it.
    globmap['int'] = int
    globmap['str'] = str
    globmap['bool'] = bool
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

    map = dict(ScriptFunc.funcgroups['access'])
    # Add in all the access level names (as uppercase symbols)
    map.update(twcommon.access.map)
    globmap['access'] = ScriptNamespace(map)

    #map = dict(ScriptFunc.funcgroups['datetime'])
    ### Need an approximate-delta-in-English function
    map = {}
    # Expose some type constructors directly
    map['timedelta'] = datetime.timedelta
    propmap = dict(ScriptFunc.funcgroups['datetime_propmap'])
    globmap['datetime'] = ScriptNamespace(map, propmap)

    # And a few entries that are generated each time they're fetched.
    propmap = dict(ScriptFunc.funcgroups['_propmap'])

    ### Run this through a site-specific Python hook.

    # And that's our global namespace.
    return ScriptNamespace(globmap, propmap)

# Table of what attributes can be read from what types. Used by
# type_getattr_allowed().
type_getattr_table = {
    datetime.timedelta: set(['days', 'max', 'microseconds', 'min', 'resolution', 'seconds', 'total_seconds']),
    }

def type_getattr_allowed(typ, key):
    """Given a type, what attributes do we permit script code to read?
    This is important because unfettered access to foo.__dict__, for
    example, would be catastrophic.
    """
    res = type_getattr_table.get(typ, None)
    if not res:
        return False
    if res is True:
        return True
    return (key in res)
    
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
    - locals (which start with "_")
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
        if dependencies is not None:
            dependencies.add(('instanceprop', iid, locid, key))
        res = yield motor.Op(app.mongodb.instanceprop.find_one,
                             {'iid':iid, 'locid':locid, 'key':key},
                             {'val':1})
        if res:
            return res['val']
    
    if locid is not None:
        if dependencies is not None:
            dependencies.add(('worldprop', wid, locid, key))
        res = yield motor.Op(app.mongodb.worldprop.find_one,
                             {'wid':wid, 'locid':locid, 'key':key},
                             {'val':1})
        if res:
            return res['val']

    if iid is not None:
        if dependencies is not None:
            dependencies.add(('instanceprop', iid, None, key))
        res = yield motor.Op(app.mongodb.instanceprop.find_one,
                             {'iid':iid, 'locid':None, 'key':key},
                             {'val':1})
        if res:
            return res['val']

    if True:
        if dependencies is not None:
            dependencies.add(('worldprop', wid, None, key))
        res = yield motor.Op(app.mongodb.worldprop.find_one,
                             {'wid':wid, 'locid':None, 'key':key},
                             {'val':1})
        if res:
            return res['val']

    if app.global_symbol_table.has(key):
        (res, yieldy) = app.global_symbol_table.getyieldy(key)
        if yieldy:
            res = yield res()
        return res

    raise SymbolError('Name "%s" is not found' % (key,))


# Late imports, to avoid circularity
from twcommon.misc import is_typed_dict
import twcommon.access
import twcommon.interp
import two.grammar
import two.execute
import two.ipool
from two.evalctx import EvalPropContext
from two.task import DIRTY_FOCUS
from two.evalctx import LEVEL_EXECUTE, LEVEL_MESSAGE
from two.evalctx import EVALTYPE_RAW, EVALTYPE_TEXT
