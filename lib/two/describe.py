import tornado.gen
import motor

import two.interp

LEVEL_EXECUTE = 4
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
        self.availtargets = set()

    @tornado.gen.coroutine
    def eval(self, key, asstring=False):
        res = yield find_symbol(self.app, self.wid, self.iid, self.locid, key)
        if self.level is LEVEL_RAW:
            if (asstring):
                res = str(res)
            return res
        
        try:
            if type(res) is dict:
                otype = res.get('type', None)
                if otype == 'text':
                    ls = two.interp.parse(res.get('text', ''))
                    res = []
                    for el in ls:
                        if isinstance(el, two.interp.Link):
                            res.append(['link', el.target])
                            self.availtargets.add(el.target)
                        elif isinstance(el, two.interp.EndLink):
                            res.append(['endlink'])
                        elif isinstance(el, two.interp.Interpolate):
                            res.append('[[###]]')
                        else:
                            res.append(el)
        except Exception as ex:
            return '[Exception: %s]' % (ex,)

        if (asstring):
            if res is None:
                res = ''
            res = str(res)
        return res

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
    
