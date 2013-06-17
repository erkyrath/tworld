import types
import itertools
import random
import datetime

import tornado.gen
import motor

from twcommon.excepts import SymbolError

class ScriptNamespace(object):
    """A container for user-accessible items in a script. This is basically
    a script-safe equivalent of a module.

    Also supports generators as fields -- gettable properties, more or less.
    An entry in propmap is called and the result returned as the property
    value.    

    Note that to fetch an attribute, you call nmsp.get(key). But in script
    code, you'd say "nmsp.foo" or "nmsp['foo']".
    
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
                if len(val) > 24:
                    val = val[:24] + '...'
            ls.append('%s=%s' % (key, val))
        ls = ', '.join(ls)
        return '<ScriptNamespace(%s)>' % (ls,)

    def get(self, key):
        if key in self.propmap:
            return self.propmap[key]()
        return self.map[key]

    def has(self, key):
        return (key in self.map) or (key in self.propmap)

class ScriptFunc:
    # As functions are defined with the @scriptfunc decorator, they are
    # stuffed into a dict in this master dict.
    funcgroups = {}
    
    def __init__(self, name, func, yieldy=False):
        self.name = name
        self.yieldy = yieldy

        if not yieldy:
            self.func = func
        else:
            self.yieldfunc = tornado.gen.coroutine(func)
        
    def __repr__(self):
        return '<ScriptFunc "%s">' % (self.name,)

def scriptfunc(name, group=None, **kwargs):
    """Decorator for scriptfunc functions.
    """
    def wrap(func):
        func = ScriptFunc(name, func, **kwargs)
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

    @scriptfunc('str', group='_')
    def global_str(object=''):
        """The str constructor.
        """
        return str(object)

    @scriptfunc('int', group='_')
    def global_int(x=0, base=10):
        """The int constructor.
        """
        return int(x, base=base)

    @scriptfunc('bool', group='_')
    def global_bool(x=False):
        """The bool constructor.
        """
        return bool(x)

    @scriptfunc('text', group='_')
    def global_text(object=''):
        """Wrap a string as a {text} object, so that its markup will get
        interpreted.
        """
        return { 'type':'text', 'text':str(object) }

    @scriptfunc('len', group='_')
    def global_len(object):
        """The length function.
        """
        return len(object)

    @scriptfunc('unfocus', group='_', yieldy=True)
    def global_unfocus(player=None):
        """Defocus the given player (or the current player, if none given).
        This closes the focus pane, if it's open.
        ### Maybe a second argument, for "unfocus if the focus is equal to
        this"? Would let us optimize out the already-null case, too.
        """
        ctx = EvalPropContext.get_current_context()
        if player is None:
            if not ctx.uid:
                raise Exception('No current player')
            uid = ctx.uid
        else:
            res = yield motor.Op(ctx.app.mongodb.playstate.find_one,
                                 {'_id':player.uid},
                                 {'iid':1})
            if not res:
                raise KeyError('No such player')
            if res['iid'] != ctx.loctx.iid:
                raise Exception('Player is not in this instance')
            uid = player.uid
        yield motor.Op(ctx.app.mongodb.playstate.update,
                       {'_id':uid},
                       {'$set':{'focus':None}})
        ctx.task.set_dirty(uid, DIRTY_FOCUS)

    @scriptfunc('event', group='_', yieldy=True)
    def global_event(you, others=None):
        """Send an event message to the current player, like {event}.
        The argument(s) must be string or {text}. The optional second
        argument goes to other players in the same location.
        """
        ctx = EvalPropContext.get_current_context()
        depth = ctx.depthatcall
        
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
                
        yield ctx.perform_event(you, youeval, others, otherseval, depth=depth)

    @scriptfunc('move', group='_', yieldy=True)
    def global_move(dest, you=None, oleave=None, oarrive=None):
        """Move the player to another location in the same world, like {move}.
        The first argument must be a location or location key. The rest
        of the arguments must be string or {text}; they are messages displayed
        for the player and other players.
        """
        ctx = EvalPropContext.get_current_context()
        depth = ctx.depthatcall
        
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
                
        yield ctx.perform_move(locid, you, youeval, oleave, oleaveeval, oarrive, oarriveeval, depth=depth)
        
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

    @scriptfunc('timedelta', group='datetime')
    def global_datetime_timedelta(days=0, seconds=0, microseconds=0, milliseconds=0, minutes=0, hours=0, weeks=0):
        """Construct a timedelta object. See datetime.timedelta in the
        Python library.
        """
        return datetime.timedelta(days=days, seconds=seconds, microseconds=microseconds, milliseconds=milliseconds, minutes=minutes, hours=hours, weeks=weeks)

    @scriptfunc('now', group='datetime_propmap')
    def global_datetime_now():
        """Return the current task's start time.
        This goes in a propmap group, meaning that the user will invoke
        it as a property object: "_.now", no parens.
        """
        ctx = EvalPropContext.get_current_context()
        return ctx.task.starttime

    @scriptfunc('choice', group='random')
    def global_random_choice(seq):
        """Choose a random member of a list.
        """
        return random.choice(seq)

    
    # Copy the collection of top-level functions.
    globmap = dict(ScriptFunc.funcgroups['_'])
    
    # Add some stuff to it.
    globmap['realm'] = two.execute.RealmProxy()
    globmap['locations'] = two.execute.WorldLocationsProxy()
    
    map = dict(ScriptFunc.funcgroups['random'])
    globmap['random'] = ScriptNamespace(map)

    map = dict(ScriptFunc.funcgroups['datetime'])
    globmap['datetime'] = ScriptNamespace(map, {
            global_datetime_now.name: global_datetime_now.func
            })

    # And a few entries that are generated each time they're fetched.
    propmap = dict([
            (key, func.func) for (key, func) in ScriptFunc.funcgroups['_propmap'].items()
            ])

    # And that's our global namespace.
    return ScriptNamespace(globmap, propmap)


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
    - locals
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
    
    if locals is not None:
        if key in locals:
            return locals[key]
    
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
        return app.global_symbol_table.get(key)

    raise SymbolError('Name "%s" is not found' % (key,))


# Late imports, to avoid circularity
from twcommon.misc import is_typed_dict
import two.execute
from two.evalctx import EvalPropContext
from two.task import DIRTY_FOCUS
