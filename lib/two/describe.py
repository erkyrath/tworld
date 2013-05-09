import tornado.gen
import motor

from two import interp

LEVEL_DISPLAY = 3
LEVEL_MESSAGE = 2
LEVEL_FLAT = 1
LEVEL_RAW = 0

class EvalPropContext(object):
    def __init__(self, app, wid, iid, locid=None, level=LEVEL_MESSAGE):
        self.app = app
        self.wid = wid
        self.iid = iid
        self.locid = locid
        self.level = level
        self.accum = None
        self.linktargets = None
        self.dependencies = None

    @tornado.gen.coroutine
    def eval(self, key):
        """
        Look up and return a symbol, in this context. After the call,
        dependencies will contain the symbol (and any others checked when
        putting together the result).

        The result type depends on the level:

        RAW: Python object direct from Mongo.
        FLAT: A string.
        MESSAGE: A string. ({text} objects produce strings from the flattened,
        de-styled, de-linked description.)
        DISPLAY: A string or, for {text} objects, a description.

        (A description is an array of strings and tag-arrays, JSONable and
        passable to the client.)

        For the {text} case, this also accumulates a set of link-targets
        which are found in links in the description. Dependencies are
        also accumulated.
        """
        res = yield self.evalkey(key)

        # At this point, if the value was a {text}, the accum will be an
        # array rather than None. That's how we tell the difference.
        
        if (self.level == LEVEL_RAW):
            return res
        if (self.level == LEVEL_FLAT):
            return str(res)
        if (self.level == LEVEL_MESSAGE):
            if self.accum is not None:
                return ''.join([ str(val) for val in self.accum ])
            return str(res)
        if (self.level == LEVEL_DISPLAY):
            if self.accum is not None:
                return self.accum
            return str(res)
        raise Exception('unrecognized eval level: %d' % (self.level,))
        
    @tornado.gen.coroutine
    def evalkey(self, key, depth=0):
        """
        Look up a symbol, adding it to the accumulated content. If the
        result contains interpolated strings, this calls itself recursively.

        Returns an object or description array. (The latter only at
        MESSAGE or DISPLAY level.)

        The top-level call to evalkey() may set up the description accumulator
        and linktargets. Lower-level calls use the existing ones.
        """
        res = yield find_symbol(self.app, self.wid, self.iid, self.locid, key)

        if not(is_text_object(res)
               and self.level in (LEVEL_MESSAGE, LEVEL_DISPLAY)):
            # For most cases, the type returned by the database is the
            # type we want.
            return res

        # But at MESSAGE/DISPLAY level, a {text} object is parsed out.

        try:
            if (depth == 0):
                assert self.accum is None, 'EvalPropContext.accum should be None at depth zero'
                self.accum = []
                self.linktargets = {}
                self.dependencies = set()
            else:
                assert self.accum is not None, 'EvalPropContext.accum should not be None at depth nonzero'
                
            nodls = interp.parse(res.get('text', ''))
            for nod in nodls:
                if not (isinstance(nod, interp.InterpNode)):
                    # String.
                    self.accum.append(nod)
                    continue
                if isinstance(nod, interp.Interpolate):
                    ### Should execute code here, but right now we only
                    ### allow symbol lookup.
                    subres = self.evalkey(self, nod.expr, depth+1)
                    # {text} objects have already added their contents to
                    # the accum array.
                    if not is_text_object(subres):
                        # Anything not a {text} object gets interpolated as
                        # a string.
                        self.accum.append(str(subres))
                    continue
                self.accum.append(nod.describe())
            
        except Exception as ex:
            return '[Exception: %s]' % (ex,)

        return res

def is_text_object(res):
    return (type(res) is dict and res.get('type', None) == 'text')

@tornado.gen.coroutine
def find_symbol(app, wid, iid, locid, key):
    res = yield motor.Op(app.mongodb.instanceprop.find_one,
                         {'iid':iid, 'locid':locid, 'key':key},
                         {'val':1})
    if res:
        return res['val']
    
    res = yield motor.Op(app.mongodb.worldprop.find_one,
                         {'wid':wid, 'locid':locid, 'key':key},
                         {'val':1})
    if res:
        return res['val']
    
    res = yield motor.Op(app.mongodb.instanceprop.find_one,
                         {'iid':iid, 'locid':None, 'key':key},
                         {'val':1})
    if res:
        return res['val']
    
    res = yield motor.Op(app.mongodb.worldprop.find_one,
                         {'wid':wid, 'locid':None, 'key':key},
                         {'val':1})
    if res:
        return res['val']

    return None

@tornado.gen.coroutine
def generate_locale(app, conn):
    playstate = yield motor.Op(app.mongodb.playstate.find_one,
                               {'_id':conn.uid},
                               {'iid':1, 'locale':1, 'focus':1})
    app.log.info('### playstate: %s', playstate)
    
    iid = playstate['iid']
    if not iid:
        msg = {'cmd':'refresh', 'locale':'...', 'focus':None, 'world':{'world':'(In transition)', 'scope':'\u00A0', 'creator':'...'}}
        conn.write(msg)
        return
        
    instance = yield motor.Op(app.mongodb.instances.find_one,
                              {'_id':iid})
    wid = instance['wid']
    scid = instance['scid']

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

    location = yield motor.Op(app.mongodb.locations.find_one,
                              {'wid':wid, 'key':playstate['locale']},
                              {'name':1})
    locid = location['_id']

    ctx = EvalPropContext(app, wid, iid, locid, level=LEVEL_DISPLAY)
    localetext = yield ctx.eval('desc')

    focustext = None
    if playstate['focus']:
        focustext = yield ctx.eval(playstate['focus'])
    
    msg = {'cmd':'refresh',
           'world':{'world':worldname, 'scope':scopename, 'creator':creatorname},
           'localename': location['name'],
           'locale': localetext,
           'focus': focustext,
           }
    
    conn.write(msg)
    
