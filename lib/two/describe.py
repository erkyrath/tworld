import tornado.gen
import motor

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
        scopename = '(Personal instance, %s)' % (scopeowner['name'],)
    elif scope['type'] == 'grp':
        scopename = '(Group: %s)' % (scope['group'],)
    else:
        scopename = '???'
    
    msg = {'cmd':'refresh',
           'world':{'world':worldname, 'scope':scopename, 'creator':creatorname},
           'localename': 'LOC',
           'locale': '###.',
           'focus': None, ###
           }
    
    conn.write(msg)
    
