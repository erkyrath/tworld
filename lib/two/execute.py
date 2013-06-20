"""
This module contains a grab-bag of tools used to execute player actions.
We have a bunch of proxy classes, which appear in the TworldPy environment
to represent locations and players and so on. We also have utility methods
involved by player actions in the world.

(The actual execution of TworldPy code is mostly handled in the evalctx
module, not here.)
"""

import datetime

import tornado.gen
from bson.objectid import ObjectId
import motor

from twcommon.excepts import MessageException, ErrorMessageException
from twcommon.excepts import SymbolError, ExecRunawayException, ExecSandboxException
from twcommon.misc import MAX_DESCLINE_LENGTH
import two.task

class PropertyProxyMixin:
    """Mix-in base class for an object which offers access to a bunch of
    database entries, indexed by key.

    Note that to fetch an attribute, you call proxy.getprop(ctx, loctx, key).
    But in script code, you'd just say "proxy.foo" or "proxy['foo']". The
    location information, which is necessary to make sense of the key,
    comes from the script's context.
    """
    @tornado.gen.coroutine
    def getprop(self, ctx, loctx, key):
        raise NotImplementedError('%s: getprop not implemented' % (self,))
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        raise NotImplementedError('%s: delprop not implemented' % (self,))
    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        raise NotImplementedError('%s: setprop not implemented' % (self,))

class PlayerProxy(PropertyProxyMixin, object):
    """Represents a player, in the script environment. The uid argument
    must be an ObjectId.
    """
    def __init__(self, uid):
        self.uid = uid
    def __repr__(self):
        return '<PlayerProxy %s>' % (self.uid,)
    def __eq__(self, other):
        if isinstance(other, PlayerProxy):
            return (self.uid == other.uid)
        if isinstance(other, ObjectId):
            return (self.uid == other)
        return False
    def __ne__(self, obj):
        return not self.__eq__(obj)

    @tornado.gen.coroutine
    def getprop(self, ctx, loctx, key):
        """Get a player property. This checks both the instance and world
        tables, and also the all-players properties. (We do not expect to
        see a world-level player-specific value, but it's legal.)
        """
        wid = loctx.wid
        iid = loctx.iid
        uid = self.uid
        dependencies = ctx.dependencies
        
        if iid is not None:
            if dependencies is not None:
                dependencies.add(('iplayerprop', iid, uid, key))
            res = yield motor.Op(ctx.app.mongodb.iplayerprop.find_one,
                                 {'iid':iid, 'uid':uid, 'key':key},
                                 {'val':1})
            if res:
                return res['val']
    
        if True:
            if dependencies is not None:
                dependencies.add(('wplayerprop', wid, uid, key))
            res = yield motor.Op(ctx.app.mongodb.wplayerprop.find_one,
                                 {'wid':wid, 'uid':uid, 'key':key},
                                 {'val':1})
            if res:
                return res['val']

        if iid is not None:
            if dependencies is not None:
                dependencies.add(('iplayerprop', iid, None, key))
            res = yield motor.Op(ctx.app.mongodb.iplayerprop.find_one,
                                 {'iid':iid, 'uid':None, 'key':key},
                                 {'val':1})
            if res:
                return res['val']
    
        if True:
            if dependencies is not None:
                dependencies.add(('wplayerprop', wid, None, key))
            res = yield motor.Op(ctx.app.mongodb.wplayerprop.find_one,
                                 {'wid':wid, 'uid':None, 'key':key},
                                 {'val':1})
            if res:
                return res['val']

        raise AttributeError('Player property "%s" is not found' % (key,))
        
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        """Delete a player instance property, if present.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code')
        iid = loctx.iid
        uid = self.uid
        yield motor.Op(ctx.app.mongodb.iplayerprop.remove,
                       {'iid':iid, 'uid':uid, 'key':key})
        ctx.task.changeset.add( ('iplayerprop', iid, uid, key) )

    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        """Set a player instance property.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code')
        iid = loctx.iid
        uid = self.uid
        yield motor.Op(ctx.app.mongodb.iplayerprop.update,
                       {'iid':iid, 'uid':uid, 'key':key},
                       {'iid':iid, 'uid':uid, 'key':key, 'val':val},
                       upsert=True)
        ctx.task.changeset.add( ('iplayerprop', iid, uid, key) )

class LocationProxy(PropertyProxyMixin, object):
    """Represents a location, in the script environment. The locid argument
    must be an ObjectId.

    ### Support "player in location" containment operator?
    """
    def __init__(self, locid):
        self.locid = locid
    def __repr__(self):
        return '<LocationProxy %s>' % (self.locid,)
    def __eq__(self, other):
        if isinstance(other, LocationProxy):
            return (self.locid == other.locid)
        if isinstance(other, ObjectId):
            return (self.locid == other)
        return False
    def __ne__(self, obj):
        return not self.__eq__(obj)
    
    @tornado.gen.coroutine
    def getprop(self, ctx, loctx, key):
        """Get a property. This checks both the instance and world tables,
        and also the realm-level properties.
        """
        wid = loctx.wid
        iid = loctx.iid
        locid = self.locid
        dependencies = ctx.dependencies
        
        if iid is not None:
            if dependencies is not None:
                dependencies.add(('instanceprop', iid, locid, key))
            res = yield motor.Op(ctx.app.mongodb.instanceprop.find_one,
                                 {'iid':iid, 'locid':locid, 'key':key},
                                 {'val':1})
            if res:
                return res['val']
    
        if True:
            if dependencies is not None:
                dependencies.add(('worldprop', wid, locid, key))
            res = yield motor.Op(ctx.app.mongodb.worldprop.find_one,
                                 {'wid':wid, 'locid':locid, 'key':key},
                                 {'val':1})
            if res:
                return res['val']

        if iid is not None:
            if dependencies is not None:
                dependencies.add(('instanceprop', iid, None, key))
            res = yield motor.Op(ctx.app.mongodb.instanceprop.find_one,
                                 {'iid':iid, 'locid':None, 'key':key},
                                 {'val':1})
            if res:
                return res['val']
    
        if True:
            if dependencies is not None:
                dependencies.add(('worldprop', wid, None, key))
            res = yield motor.Op(ctx.app.mongodb.worldprop.find_one,
                                 {'wid':wid, 'locid':None, 'key':key},
                                 {'val':1})
            if res:
                return res['val']


        raise AttributeError('Property "%s" is not found' % (key,))
        
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        """Delete an instance property, if present.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code')
        iid = loctx.iid
        locid = self.locid
        yield motor.Op(ctx.app.mongodb.instanceprop.remove,
                       {'iid':iid, 'locid':locid, 'key':key})
        ctx.task.changeset.add( ('instanceprop', iid, locid, key) )

    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        """Set an instance property.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code')
        iid = loctx.iid
        locid = self.locid
        yield motor.Op(ctx.app.mongodb.instanceprop.update,
                       {'iid':iid, 'locid':locid, 'key':key},
                       {'iid':iid, 'locid':locid, 'key':key, 'val':val},
                       upsert=True)
        ctx.task.changeset.add( ('instanceprop', iid, locid, key) )
        
class RealmProxy(PropertyProxyMixin, object):
    """Represents the realm-level properties, in the script environment.
    There's only one of these, in the global namespace.
    """
    def __repr__(self):
        return '<RealmProxy>'
    
    @tornado.gen.coroutine
    def getprop(self, ctx, loctx, key):
        """Get a realm-level property. This checks both the instance
        and world tables.
        """
        wid = loctx.wid
        iid = loctx.iid
        locid = None
        dependencies = ctx.dependencies
        
        if iid is not None:
            if dependencies is not None:
                dependencies.add(('instanceprop', iid, locid, key))
            res = yield motor.Op(ctx.app.mongodb.instanceprop.find_one,
                                 {'iid':iid, 'locid':locid, 'key':key},
                                 {'val':1})
            if res:
                return res['val']
    
        if True:
            if dependencies is not None:
                dependencies.add(('worldprop', wid, locid, key))
            res = yield motor.Op(ctx.app.mongodb.worldprop.find_one,
                                 {'wid':wid, 'locid':locid, 'key':key},
                                 {'val':1})
            if res:
                return res['val']

        raise AttributeError('Realm property "%s" is not found' % (key,))
        
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        """Delete a realm-level instance property, if present.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code')
        iid = loctx.iid
        locid = None
        yield motor.Op(ctx.app.mongodb.instanceprop.remove,
                       {'iid':iid, 'locid':locid, 'key':key})
        ctx.task.changeset.add( ('instanceprop', iid, locid, key) )

    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        """Set a realm-level instance property.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code')
        iid = loctx.iid
        locid = None
        yield motor.Op(ctx.app.mongodb.instanceprop.update,
                       {'iid':iid, 'locid':locid, 'key':key},
                       {'iid':iid, 'locid':locid, 'key':key, 'val':val},
                       upsert=True)
        ctx.task.changeset.add( ('instanceprop', iid, locid, key) )


class BoundPropertyProxy(object):
    """Wrapper to convert a PropertyProxyMixin to a load/delete/store
    object for a particular key.

    In other words, if you have a LocationProxy for a location, and you
    want a proxy to set, get, or delete loc.prop, you construct
    BoundPropertyProxy(loc, 'prop').
    """
    def __init__(self, proxy, key):
        self.proxy = proxy
        self.key = key
    @tornado.gen.coroutine
    def load(self, ctx, loctx):
        res = yield self.proxy.getprop(ctx, loctx, self.key)
        return res
    @tornado.gen.coroutine
    def delete(self, ctx, loctx):
        yield self.proxy.delprop(ctx, loctx, self.key)
    @tornado.gen.coroutine
    def store(self, ctx, loctx, val):
        yield self.proxy.setprop(ctx, loctx, self.key, val)

class BoundNameProxy(object):
    """A load/delete/store object for a particular symbol.

    That is, BoundNameProxy('name') has methods to set, get, or delete
    the "name" symbol (in a given location context). This respects all
    the wacky rules: '_' is always the global context, 'name' may be
    found at the realm level or in the world definition, etc.
    """
    
    def __init__(self, key):
        self.key = key
        
    @tornado.gen.coroutine
    def load(self, ctx, loctx):
        ### locals?
        res = yield two.symbols.find_symbol(ctx.app, loctx, self.key, dependencies=ctx.dependencies)
        return res
    
    @tornado.gen.coroutine
    def delete(self, ctx, loctx):
        if self.key == '_' or two.symbols.is_immutable_symbol(self.key):
            raise Exception('Cannot delete keyword "%s"' % (self.key,))
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code')
        iid = loctx.iid
        locid = loctx.locid
        yield motor.Op(ctx.app.mongodb.instanceprop.remove,
                       {'iid':iid, 'locid':locid, 'key':self.key})
        ctx.task.changeset.add( ('instanceprop', iid, locid, self.key) )
    
    @tornado.gen.coroutine
    def store(self, ctx, loctx, val):
        if self.key == '_':
            # Assignment to _ is silently dropped, to sort-of support
            # Python idiom.
            return
        if two.symbols.is_immutable_symbol(self.key):
            raise Exception('Cannot delete keyword "%s"' % (self.key,))
        ### locals?
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code')
        iid = loctx.iid
        locid = loctx.locid
        yield motor.Op(ctx.app.mongodb.instanceprop.update,
                       {'iid':iid, 'locid':locid, 'key':self.key},
                       {'iid':iid, 'locid':locid, 'key':self.key, 'val':val},
                       upsert=True)
        ctx.task.changeset.add( ('instanceprop', iid, locid, self.key) )

class WorldLocationsProxy(PropertyProxyMixin, object):
    """Represents the collection of locations (in the current world).
    Has read-only properties, since you can't invent new locations or
    destroy them on the fly.
    There's only one of these, in the global namespace.
    """
    def __repr__(self):
        return '<WorldLocationsProxy>'
    
    @tornado.gen.coroutine
    def getprop(self, ctx, loctx, key):
        res = yield motor.Op(ctx.app.mongodb.locations.find_one,
                             {'wid':loctx.wid, 'key':key},
                             {'_id':1})
        if not res:
            raise KeyError('No such location: %s' % (key,))
        return LocationProxy(res['_id'])

    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        raise ExecSandboxException('%s.%s: locations cannot be deleted' % (type(self).__name__, key))
    
    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        raise ExecSandboxException('%s.%s: locations cannot be assigned' % (type(self).__name__, key))
    
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
        app.log.warning('portal_description failed: %s', ex, exc_info=app.debugstacktraces)
        return None

@tornado.gen.coroutine
def render_focus(task, loctx, conn, focusobj):
    """The part of generate_update() that deals with focus.
    Returns (focus, focusspecial).
    """
    if focusobj is None:
        return (False, False)

    evaltype = EVALTYPE_SYMBOL

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
            evaltype = EVALTYPE_RAW
            arr = focusobj
            focusobj = {'type':'portal', 'portid':arr[1]}
            if len(arr) >= 3:
                focusobj['backto'] = arr[2]
            pass   # Fall through to EvalPropContext code below
        else:
            focusdesc = '[Focus: %s]' % (focusobj,)
            return (focusdesc, False)

    ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_DISPSPECIAL)
    focusdesc = yield ctx.eval(focusobj, evaltype=evaltype)
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
            text = target[2]
            otext = target[3]
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
            if text is not None:
                ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_MESSAGE)
                val = yield ctx.eval(text, evaltype=EVALTYPE_TEXT)
                task.write_event(uid, val)
            if otext is not None:
                others = yield task.find_locale_players(notself=True)
                ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_MESSAGE)
                val = yield ctx.eval(otext, evaltype=EVALTYPE_TEXT)
                task.write_event(others, val)
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

            # Move the player to the void, and schedule a portin event.
            portto = {'wid':newwid, 'scid':newscid, 'locid':newlocid}
            yield motor.Op(app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'iid':None,
                                    'locid':None,
                                    'focus':None,
                                    'lastmoved': task.starttime,
                                    'lastlocid': None,
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
        newval = yield ctx.eval(target, evaltype=EVALTYPE_CODE)
        if newval is not None:
            ### Not sure I like this.
            conn.write({'cmd':'event', 'text':str(newval)})
    except Exception as ex:
        task.log.warning('Action failed: %s', ex, exc_info=app.debugstacktraces)
        exmsg = '%s: %s' % (ex.__class__.__name__, ex,)
        conn.write({'cmd':'error', 'text':exmsg})
        
    
# Late imports, to avoid circularity
from two.task import DIRTY_ALL, DIRTY_WORLD, DIRTY_LOCALE, DIRTY_POPULACE, DIRTY_FOCUS
from two.evalctx import EvalPropContext
from two.evalctx import EVALTYPE_SYMBOL, EVALTYPE_RAW, EVALTYPE_CODE, EVALTYPE_TEXT
from two.evalctx import LEVEL_EXECUTE, LEVEL_DISPSPECIAL, LEVEL_DISPLAY, LEVEL_MESSAGE, LEVEL_FLAT, LEVEL_RAW
from twcommon.access import ACC_VISITOR
import two.symbols
