import types
import random

import tornado.gen
import motor

from twcommon.excepts import SymbolError

class QuietNamespace(types.SimpleNamespace):
    """A subclass of SimpleNamespace which doesn't go hog-wild when you
    print it. Contained values are abbreviated, and it tries to avoid
    recursing into them.
    """
    def __repr__(self):
        ls = []
        for (key, val) in self.__dict__.items():
            if type(val) is dict:
                val = '{...}'
            elif isinstance(val, types.SimpleNamespace):
                val = 'namespace(...)'
            else:
                val = str(val)
                if len(val) > 24:
                    val = val[:24] + '...'
            ls.append('%s=%s' % (key, val))
        ls = ', '.join(ls)
        return '<namespace(%s)>' % (ls,)

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
        return str(object)

    @scriptfunc('int', group='_')
    def global_int(x=0, base=10):
        return int(x, base=base)

    @scriptfunc('bool', group='_')
    def global_bool(x=False):
        return bool(x)

    @scriptfunc('choice', group='random')
    def global_random_choice(seq):
        return random.choice(seq)

    
    # Copy the collection of top-level functions.
    globmap = dict(ScriptFunc.funcgroups['_'])
    
    # Add some stuff to it.
    map = dict(ScriptFunc.funcgroups['random'])
    globmap['random'] = QuietNamespace(**map)

    # And that's our global namespace.
    return QuietNamespace(**globmap)


@tornado.gen.coroutine
def find_symbol(app, loctx, key, locals=None, dependencies=None):
    """Look up a symbol, using the universal laws of symbol-looking-up.
    To wit:
    - ### "_" and locals
    - instance properties
    - world properties
    - realm-level instance properties
    - realm-level world properties
    - ### builtins
    """
    if key == '_':
        # Special case
        return app.global_symbol_table
    
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

    raise SymbolError('Name "%s" is not found' % (key,))

