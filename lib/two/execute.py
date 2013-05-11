import random

import tornado.gen
import motor

from twcommon.excepts import MessageException, ErrorMessageException
from two import interp

LEVEL_DISPLAY = 3
LEVEL_MESSAGE = 2
LEVEL_FLAT = 1
LEVEL_RAW = 0

class EvalPropContext(object):
    link_code_counter = 1
    
    def __init__(self, app, wid, iid, locid=None, level=LEVEL_MESSAGE):
        self.app = app
        self.wid = wid
        self.iid = iid
        self.locid = locid
        self.level = level
        self.accum = None
        self.linktargets = None
        self.dependencies = None
        ### Will need CPU-limiting someday.

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
        # Initialize per-invocation fields.
        self.accum = None
        self.linktargets = None
        self.dependencies = None
        
        res = yield self.evalkey(key)

        # At this point, if the value was a {text}, the accum will contain
        # the desired description.
        
        if (self.level == LEVEL_RAW):
            return res
        if (self.level == LEVEL_FLAT):
            return str(res)
        if (self.level == LEVEL_MESSAGE):
            if is_text_object(res):
                return ''.join([ str_or_null(val) for val in self.accum ])
            return str(res)
        if (self.level == LEVEL_DISPLAY):
            if is_text_object(res):
                return self.accum
            return str_or_null(res)
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
                    if nod:
                        self.accum.append(nod)
                    continue
                if isinstance(nod, interp.Link):
                    code = str(EvalPropContext.link_code_counter) + hex(random.getrandbits(32))[2:]
                    EvalPropContext.link_code_counter = EvalPropContext.link_code_counter + 1
                    self.linktargets[code] = nod.target
                    self.accum.append( ['link', code] )
                    continue
                if isinstance(nod, interp.Interpolate):
                    ### Should execute code here, but right now we only
                    ### allow symbol lookup.
                    subres = yield self.evalkey(nod.expr, depth+1)
                    # {text} objects have already added their contents to
                    # the accum array.
                    if not is_text_object(subres):
                        # Anything not a {text} object gets interpolated as
                        # a string.
                        self.accum.append(str_or_null(subres))
                    continue
                self.accum.append(nod.describe())
            
        except Exception as ex:
            return '[Exception: %s]' % (ex,)

        return res

def is_text_object(res):
    return (type(res) is dict and res.get('type', None) == 'text')

def str_or_null(res):
    if res is None:
        return ''
    return str(res)

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
    assert conn is not None, 'generate_locale: conn is None'
    
    playstate = yield motor.Op(app.mongodb.playstate.find_one,
                               {'_id':conn.uid},
                               {'iid':1, 'locid':1, 'focus':1})
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

    locid = playstate['locid']
    location = yield motor.Op(app.mongodb.locations.find_one,
                              {'_id':locid},
                              {'wid':1, 'name':1})

    if not location or location['wid'] != wid:
        msg = {'cmd':'refresh',
               'world':{'world':worldname, 'scope':scopename, 'creator':creatorname},
               'localename': None,
               'locale': '[Location not found]',
               'focus': None,
           }
        conn.write(msg)
        return

    locname = location['name']

    conn.localeactions.clear() ### should be at top ### and localedependencies too!
    ctx = EvalPropContext(app, wid, iid, locid, level=LEVEL_DISPLAY)
    localetext = yield ctx.eval('desc')
    if ctx.linktargets:
        conn.localeactions.update(ctx.linktargets)

    focustext = None
    conn.focusactions.clear() ### should be at top
    if playstate['focus']:
        focustext = yield ctx.eval(playstate['focus'])
        if ctx.linktargets:
            conn.focusactions.update(ctx.linktargets)
    
    msg = {'cmd':'refresh',
           'world':{'world':worldname, 'scope':scopename, 'creator':creatorname},
           'localename': locname,
           'locale': localetext,
           'focus': focustext,
           }
    
    conn.write(msg)
    

@tornado.gen.coroutine
def perform_action(app, conn, target):
    playstate = yield motor.Op(app.mongodb.playstate.find_one,
                               {'_id':conn.uid},
                               {'iid':1, 'locid':1, 'focus':1})
    app.log.info('### playstate: %s', playstate)
    
    iid = playstate['iid']
    if not iid:
        # In the void, there should be no actions.
        raise ErrorMessageException('You are between worlds.')
        
    instance = yield motor.Op(app.mongodb.instances.find_one,
                              {'_id':iid})
    wid = instance['wid']
    scid = instance['scid']

    locid = playstate['locid']

    ### if the target is not a symbol, execute it directly
    
    res = yield find_symbol(app, wid, iid, locid, target)
    if res is None:
        raise ErrorMessageException('Action not defined: "%s"' % (target,))

    if type(res) is not dict:
        raise ErrorMessageException('Action "%s" is defined as a plain value: %s' % (target, res))
    restype = res.get('type', None)

    if restype == 'event':
        # Display an event.
        ### This should go through parse_description! (LEVEL_MESSAGE)
        ### Have an other-people field too.
        val = res.get('text', None)
        if val:
            conn.write({'cmd':'event', 'text':val})
        return

    if restype == 'code':
        raise ErrorMessageException('Code events are not yet supported.') ###
    
    if restype == 'text':
        # Set focus to this symbol-name
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':conn.uid},
                       {'$set':{'focus':target}})
    elif restype == 'focus':
        # Set focus to the given symbol
        ### if already at focus, leave it?
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':conn.uid},
                       {'$set':{'focus':res.get('key', None)}})
    elif restype == 'move':
        # Set locale to the given symbol
        lockey = res.get('loc', None)
        location = yield motor.Op(app.mongodb.locations.find_one,
                                  {'wid':wid, 'key':lockey},
                                  {'_id':1})
        if not location:
            raise ErrorMessageException('No such location: %s' % (lockey,))
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':conn.uid},
                       {'$set':{'locid':location['_id'], 'focus':None}})

    ### total refresh, which is not right. Be more clever.
    yield generate_locale(app, conn) 

