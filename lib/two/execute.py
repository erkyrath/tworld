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
import twcommon.misc
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
        app = ctx.app
        
        if iid is not None:
            res = yield app.propcache.get(('iplayerprop', iid, uid, key),
                                          dependencies=dependencies)
            if res:
                return res.val
    
        if True:
            res = yield app.propcache.get(('wplayerprop', wid, uid, key),
                                          dependencies=dependencies)
            if res:
                return res.val

        if iid is not None:
            res = yield app.propcache.get(('iplayerprop', iid, None, key),
                                          dependencies=dependencies)
            if res:
                return res.val
    
        if True:
            res = yield app.propcache.get(('wplayerprop', wid, None, key),
                                          dependencies=dependencies)
            if res:
                return res.val

        raise AttributeError('Player property "%s" is not found' % (key,))
        
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        """Delete a player instance property, if present.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code (player prop "%s")' % (key,))
        iid = loctx.iid
        uid = self.uid
        app = ctx.app
        
        tup = ('iplayerprop', iid, uid, key)
        yield app.propcache.delete(tup)
        ctx.task.changeset.add(tup)

    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        """Set a player instance property.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code (player prop "%s")' % (key,))
        iid = loctx.iid
        uid = self.uid
        app = ctx.app

        tup = ('iplayerprop', iid, uid, key)
        yield app.propcache.set(tup, val)
        ctx.task.changeset.add(tup)

class LocationProxy(PropertyProxyMixin, object):
    """Represents a location, in the script environment. The locid argument
    must be an ObjectId.
    Note that "PlayerProxy in LocationProxy" does not work, because that
    requires an async operation to resolve.
    """
    def __init__(self, locid):
        assert locid is not None
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
        app = ctx.app
        dependencies = ctx.dependencies
        
        if iid is not None:
            res = yield app.propcache.get(('instanceprop', iid, locid, key),
                                          dependencies=dependencies)
            if res:
                return res.val
    
        if True:
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

        raise AttributeError('Property "%s" is not found' % (key,))
        
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        """Delete an instance property, if present.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code (location prop "%s")' % (key,))
        iid = loctx.iid
        locid = self.locid
        app = ctx.app
        
        tup = ('instanceprop', iid, locid, key)
        yield app.propcache.delete(tup)
        ctx.task.changeset.add(tup)

    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        """Set an instance property.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code (location prop "%s")' % (key,))
        iid = loctx.iid
        locid = self.locid
        app = ctx.app
        
        tup = ('instanceprop', iid, locid, key)
        yield app.propcache.set(tup, val)
        ctx.task.changeset.add(tup)
        
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
        app = ctx.app
        dependencies = ctx.dependencies
        
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

        raise AttributeError('Realm property "%s" is not found' % (key,))
        
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        """Delete a realm-level instance property, if present.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code (realm prop "%s")' % (key,))
        iid = loctx.iid
        app = ctx.app
        
        tup = ('instanceprop', iid, None, key)
        yield app.propcache.delete(tup)
        ctx.task.changeset.add(tup)

    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        """Set a realm-level instance property.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code (realm prop "%s")' % (key,))
        iid = loctx.iid
        app = ctx.app
        
        tup = ('instanceprop', iid, None, key)
        yield app.propcache.set(tup, val)
        ctx.task.changeset.add(tup)

class RemoteRealmProxy(PropertyProxyMixin, object):
    """Represents the realm-level properties of some other world and instance
    (not the current location of the executing code). This looks a lot like
    RealmProxy, but it's much more limited -- there are several functions
    in symbol.py which accept RealmProxy, but RemoteRealmProxy is only
    good for property access.

    The perms argument should be a RemoteAccessMap which has been loaded
    up for the given world (and the appropriate access-from world).
    The worldname argument is only for debugging output; it doesn't affect
    functionality.
    """
    def __init__(self, wid, scid, iid, perms, worldname='???'):
        self.wid = wid
        self.scid = scid
        self.iid = iid
        self.perms = perms
        assert (perms.wid == self.wid)
        self.worldname = worldname
        
    def __repr__(self):
        return '<RemoteRealmProxy %s "%s">' % (self.iid, self.worldname)

    @tornado.gen.coroutine
    def getprop(self, ctx, loctx, key):
        """Get a realm-level property. This checks both the instance
        and world tables.

        Note that we ignore loctx completely. The RemoteRealmProxy refers
        to a fixed world/instance.
        """
        wid = self.wid
        iid = self.iid
        app = ctx.app
        dependencies = ctx.dependencies

        if not self.perms.canread(key):
            raise Exception('Cannot read this key from foreign world: %s' % (key,))
        
        if iid is not None:
            res = yield app.propcache.get(('instanceprop', iid, None, key),
                                          dependencies=dependencies)
            if res:
                val = res.val
                if isinstance(val, (list, dict)):
                    if not self.perms.canwrite(key, val):
                        val = two.propcache.deepcopy(val)
                return val
    
        if True:
            res = yield app.propcache.get(('worldprop', wid, None, key),
                                          dependencies=dependencies)
            if res:
                val = res.val
                if isinstance(val, (list, dict)):
                    if not self.perms.canwrite(key, val):
                        val = two.propcache.deepcopy(val)
                return val

        raise AttributeError('Realm property "%s" is not found' % (key,))
        
    @tornado.gen.coroutine
    def delprop(self, ctx, loctx, key):
        """Delete a realm-level instance property, if present.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code (realm prop "%s")' % (key,))
        iid = self.iid
        app = ctx.app
        
        if not self.perms.candelete(key):
            raise Exception('Cannot delete this key from foreign world: %s' % (key,))
        
        tup = ('instanceprop', iid, None, key)
        yield app.propcache.delete(tup)
        ctx.task.changeset.add(tup)

    @tornado.gen.coroutine
    def setprop(self, ctx, loctx, key, val):
        """Set a realm-level instance property.
        """
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code (realm prop "%s")' % (key,))
        iid = self.iid
        app = ctx.app
        
        if not self.perms.canwrite(key, val):
            raise Exception('Cannot write this key value to foreign world: %s=%s' % (key, repr(val)))
        
        tup = ('instanceprop', iid, None, key)
        yield app.propcache.set(tup, val)
        ctx.task.changeset.add(tup)

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
    the wacky rules: "_" is always the global context, symbols starting
    with "_" are locals, "name" may be found at the realm level or in the
    world definition, etc.
    """
    
    def __init__(self, key):
        self.key = key
        
    @tornado.gen.coroutine
    def load(self, ctx, loctx):
        res = yield two.symbols.find_symbol(ctx.app, loctx, self.key, locals=ctx.frame.locals, dependencies=ctx.dependencies)
        return res
    
    @tornado.gen.coroutine
    def delete(self, ctx, loctx):
        key = self.key
        if key == '_' or two.symbols.is_immutable_symbol(key):
            raise Exception('Cannot delete keyword "%s"' % (key,))
        
        locals = ctx.frame.locals
        if key in locals or key.startswith('_'):
            if key in locals:
                del locals[key]
                return
            raise NameError('Temporary variable "%s" is not found' % (key,))
            
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be deleted in action code (prop "%s")' % (key,))
        iid = loctx.iid
        locid = loctx.locid
        app = ctx.app
        
        tup = ('instanceprop', iid, locid, key)
        yield app.propcache.delete(tup)
        ctx.task.changeset.add(tup)
    
    @tornado.gen.coroutine
    def store(self, ctx, loctx, val):
        key = self.key
        if key == '_':
            # Assignment to _ is silently dropped, to sort-of support
            # Python idiom.
            return
        if two.symbols.is_immutable_symbol(key):
            raise Exception('Cannot delete keyword "%s"' % (key,))

        locals = ctx.frame.locals
        if key in locals or key.startswith('_'):
            locals[key] = val
            return
            
        if ctx.level != LEVEL_EXECUTE:
            raise Exception('Properties may only be set in action code (prop "%s")' % (key,))
        iid = loctx.iid
        locid = loctx.locid
        app = ctx.app
        
        tup = ('instanceprop', iid, locid, key)
        yield app.propcache.set(tup, val)
        ctx.task.changeset.add(tup)
        

class BoundSubscriptProxy(object):
    """A load/store/delete object for a subscript expression. This
    represents the left-hand side of an "x[y] = ..." expression.
    (But not "x[y:z]" -- that's not yet implemented.)
    """
    
    def __init__(self, arg, subscript):
        self.arg = arg
        self.subscript = subscript

    @tornado.gen.coroutine
    def load(self, ctx, loctx):
        return self.arg[self.subscript]
    
    @tornado.gen.coroutine
    def delete(self, ctx, loctx):
        del self.arg[self.subscript]
    
    @tornado.gen.coroutine
    def store(self, ctx, loctx, val):
        self.arg[self.subscript] = val

class MultiBoundProxy(object):
    """A load/delete/store object for a tuple of l/d/s objects. This
    represents the left-hand side of an "(x, y, z) = (1, 2, 3)" statement.
    """
    
    def __init__(self, args):
        self.tuple = tuple(args)
        
    @tornado.gen.coroutine
    def load(self, ctx, loctx):
        res = []
        for proxy in self.tuple:
            val = yield proxy.load(ctx, loctx)
            res.append(val)
        return tuple(res)

    @tornado.gen.coroutine
    def delete(self, ctx, loctx):
        for proxy in self.tuple:
            yield proxy.delete(ctx, loctx)
    
    @tornado.gen.coroutine
    def store(self, ctx, loctx, val):
        vals = tuple(val)
        if len(vals) != len(self.tuple):
            raise ValueError('wrong number of values to unpack (expected %d)' % (len(self.tuple),))
        for proxy, val in zip(self.tuple, vals):
            yield proxy.store(ctx, loctx, val)
            
    
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
def scope_access_level(app, uid, wid, scid):
    """Check the access level of the given player to the given world and
    scope.
    If the scope is global, the world creator has creator access, everybody
    else is a visitor.
    If the scope is personal, the owner has creator access. (This is actually
    in the scopeaccess table, but we special-case it anyhow.)
    Otherwise, check the scopeaccess table.
    """
    scope = yield motor.Op(app.mongodb.scopes.find_one,
                         {'_id':scid},
                         {'type':1, 'level':1})
    if scope['type'] == 'glob':
        world = yield motor.Op(app.mongodb.worlds.find_one,
                               {'_id':wid})
        if world and world['creator'] == uid:
            return ACC_FOUNDER
        return ACC_VISITOR

    if scope['type'] == 'pers' and scope.get('uid', None) == uid:
        return ACC_FOUNDER
    
    res = yield motor.Op(app.mongodb.scopeaccess.find_one,
                         {'uid':uid, 'scid':scid},
                         {'level':1})
    if not res:
        return ACC_VISITOR
    return res.get('level', ACC_VISITOR)

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
def portal_alt_scope_accessible(app, scid, uid, world):
    """Check that a given scope is accessible to the player *as an alternate
    selection*, that is, using the "link instead to..." selector.
    Raises an exception if not available.
    """
    if (world['instancing'] != 'standard'):
        raise ErrorMessageException('The instance of this portal may not be changed.')

    scope = yield motor.Op(app.mongodb.scopes.find_one,
                            {'_id':scid})
    if not scope:
        raise ErrorMessageException('No such scope!')

    if scope['type'] == 'glob':
        # Global scope is always okay
        return
    if scope['type'] == 'pers':
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':uid},
                                {'scid':1})
        if scid == player['scid']:
            # Your personal scope is always okay
            return
        ### check access level
        raise ErrorMessageException('You do not have permission to reach this personal scope.')
    if scope['type'] == 'grp':
        ### check access level
        raise ErrorMessageException('You do not have permission to reach this group scope.')
    raise ErrorMessageException('Scope type not recognized.')
    
@tornado.gen.coroutine
def portal_resolve_scope(app, portal, uid, curscid, world):
    """Figure out what scope we are porting to. The portal scid
    value may be a special value such as 'personal', 'global',
    'same'. We also obey the (higher priority) world-instancing
    definition.

    The curscid argument must be where the player is now; the world must be
    the destination world object from the database. (Yes, that's all
    clumsy and uneven.) For an external URL portal, pass curscid==None;
    in this case 'same' will throw an exception.
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
        if curscid is None:
            raise ErrorMessageException('There is no current scope!')
        newscid = curscid
    else:
        newscid = reqscid
    assert isinstance(newscid, ObjectId), 'newscid is not ObjectId'
    return newscid

@tornado.gen.coroutine
def scope_description(app, scid, uid):
    """Return a (JSONable) object describing a scope in human-readable
    strings. Returns None if a problem arises.
    """
    scope = yield motor.Op(app.mongodb.scopes.find_one,
                           {'_id':scid})
    if not scope:
        return None

    scopetype = scope['type']
    res = { 'id':str(scope['_id']), 'type':scopetype }

    if scopetype == 'glob':
        res['name'] = 'Global'
    elif scopetype == 'grp':
        res['name'] = 'Group: %s' % (scope['group'],)
    elif scopetype == 'pers' and scope['uid'] == uid:
        res['name'] = 'Personal'
        res['you'] = True
    elif scopetype == 'pers':
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':scope['uid']},
                                {'name':1})
        res['name'] = 'Personal: %s' % (player['name'],)
    else:
        res['name'] = '???'
    
    return res

@tornado.gen.coroutine
def portal_description(app, portal, uid, uidiid=None, location=False, short=False):
    """Return a (JSONable) object describing a portal in human-readable
    strings. Returns None if a problem arises.

    The argument may be a portal object or an ObjectId referring to one.
    The uidiid argument is optional (it's looked up if not provided).
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

        scopename = None
            
        # This logic is parallel to portal_resolve_scope().
        reqscid = portal['scid']
        if world['instancing'] == 'solo':
            reqscid = 'personal'
            if short:
                scopename = 'personal-always'
            else:
                scopename = 'Personal instance (always)'
        if world['instancing'] == 'shared':
            reqscid = 'global'
            if short:
                scopename = 'global-always'
            else:
                scopename = 'Global instance (always)'

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

        if scopename is not None:
            pass  # scopename already set
        elif scope['type'] == 'glob':
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

        res = {'world':worldname, 'scope':scopename, 'scid':str(scope['_id']),
               'creator':creatorname}

        if world.get('copyable', False):
            res['copyable'] = True

        res['instancing'] = world.get('instancing', 'standard')

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
def create_portal_for_player(app, uid, plistid, newwid, newscid, newlocid, silent=False):
    """Create a new portal in the player's portal list. This does not check
    legality or access; the caller must do that.
    If the player already has this portal, raises a MessageException (if
    the silent argument is false), or just returns the portid (if silent
    is true).
    """
    newportal = { 'plistid':plistid, 'iid':None,
                  'wid':newwid, 'scid':newscid, 'locid':newlocid,
                  }
    res = yield motor.Op(app.mongodb.portals.find_one,
                         newportal)
    if res:
        if silent:
            return res['_id']
        raise MessageException(app.localize('message.copy_already_have')) # 'This portal is already in your collection.'

    # Look through the player's list and find the entry with the
    # highest listpos.
    res = yield motor.Op(app.mongodb.portals.aggregate, [
            {'$match': {'plistid':plistid, 'iid':None}},
            {'$sort': {'listpos':-1}},
            {'$limit': 1},
            ])
    listpos = 0.0
    if res and res['result']:
        listpos = res['result'][0].get('listpos', 0.0)
        
    newportal['listpos'] = listpos + 1.0
    newportid = yield motor.Op(app.mongodb.portals.insert, newportal)
    newportal['_id'] = newportid

    # Refresh the displayed plist of the player (if connected).
    try:
        portaldesc = yield portal_description(app, newportal, uid, location=True, short=True)
        if portaldesc:
            strid = str(newportid)
            portaldesc['portid'] = strid
            portaldesc['listpos'] = newportal['listpos']
            map = { strid: portaldesc }
            subls = app.playconns.get_for_uid(uid)
            if subls:
                for subconn in subls:
                    subconn.write({'cmd':'updateplist', 'map':map})
    except Exception as ex:
        app.log.warning('Unable to notify player of new portal: %s', ex, exc_info=app.debugstacktraces)

    return newportid

@tornado.gen.coroutine
def create_portal_for_plist(task, iid, plistid, newwid, newscid, newlocid):
    """Create a new portal in an instance of a portal list. This does not
    check legality or access; the caller must do that.
    Raises a MessageException if the list already has this portal.
    """
    app = task.app
    if not iid:
        raise ErrorMessageException('create_portal_for_plist: not in an instance!')
    newportal = { 'plistid':plistid, 'iid':iid,
                  'wid':newwid, 'scid':newscid, 'locid':newlocid,
                  }
    # Check whether it's in the world-level or instance-level list.
    res = yield motor.Op(app.mongodb.portals.find_one,
                         newportal)
    if res:
        raise MessageException(app.localize('message.plist_add_already_have')) # 'This portal is already in this collection.'
    altportal = dict(newportal)
    altportal['iid'] = None
    res = yield motor.Op(app.mongodb.portals.find_one,
                         altportal)
    if res:
        raise MessageException(app.localize('message.plist_add_already_have')) # 'This portal is already in this collection.'

    # Look through the list (both instance and world) and find the
    # entry with the highest listpos.
    res = yield motor.Op(app.mongodb.portals.aggregate, [
            {'$match': {'plistid':plistid, '$or':[{'iid':None}, {'iid':iid}]}},
            {'$sort': {'listpos':-1}},
            {'$limit': 1},
            ])
    listpos = 0.0
    if res and res['result']:
        listpos = res['result'][0].get('listpos', 0.0)
        
    newportal['listpos'] = listpos + 1.0
    newportid = yield motor.Op(app.mongodb.portals.insert, newportal)
    newportal['_id'] = newportid

    # Data change for anyone watching this portlist
    task.set_data_change( ('portlist', plistid, iid) )
    return newportid
    

@tornado.gen.coroutine
def render_focus(task, loctx, conn, focusobj):
    """The part of generate_update() that deals with focus.
    Returns (focus, focusspecial).
    """
    if focusobj is None:
        return (False, False)

    assert conn.uid == loctx.uid
    
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
        
        if restype == 'portlist':
            # We've already checked access level (if indeed this portlist
            # focus array came from a {portlist} with a readaccess level).
            (dummy, plistid, editable, extratext, withback, portid) = focusobj
            
            if extratext:
                # Look up the extra text in a separate context.
                ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_DISPLAY)
                extratext = yield ctx.eval(extratext, evaltype=EVALTYPE_TEXT)
                if ctx.linktargets:
                    conn.focusactions.update(ctx.linktargets)
                if ctx.dependencies:
                    conn.focusdependencies.update(ctx.dependencies)

            portlist = yield motor.Op(task.app.mongodb.portlists.find_one,
                                      {'_id':plistid})
            if not portlist:
                raise ErrorMessageException('No such portal list.')
            if 'uid' in portlist and portlist['uid'] != conn.uid:
                raise ErrorMessageException('This portal list is not yours.')
            if 'wid' in portlist and portlist['wid'] != loctx.wid:
                raise ErrorMessageException('This portal list is not available.')

            if portid:
                # We are focussed on a predetermined portal in the list.
                # Render it.
                portal = yield motor.Op(task.app.mongodb.portals.find_one,
                                        {'_id':portid})
                if not portal:
                    raise ErrorMessageException('No such portal.')
                if portal.get('plistid', None) != plistid:
                    raise ErrorMessageException('Portal does not match portlist.')

                if withback:
                    # If the player has poked into a bookshelf, show the
                    # back link (but not the bookshelf description).
                    backkey = 'plistback' + EvalPropContext.build_action_key()
                    conn.focusactions[backkey] = ('focusportal', None, plistid)
                    extratext = None
                else:
                    # Got here by an autofocus portlist, or by selecting from
                    # the player's personal portlist.
                    backkey = None
                
                yield two.execute.portal_in_reach(task.app, portal, conn.uid, loctx.wid)

                portalobj = yield two.execute.portal_description(task.app, portal, conn.uid, uidiid=loctx.iid, location=True)
                portalobj['portid'] = str(portal['_id'])
                ackey = 'port' + EvalPropContext.build_action_key()
                conn.focusactions[ackey] = ('portal', portid)
                if portalobj.get('copyable', False):
                    copykey = 'copy' + EvalPropContext.build_action_key()
                    conn.focusactions[copykey] = ('copyportal', portid)
                    portalobj['copyable'] = copykey
                    
                altloctx = two.task.LocContext(None, wid=portal['wid'], locid=portal['locid'])
                ctx = EvalPropContext(task, loctx=altloctx, level=LEVEL_FLAT)
                try:
                    desttext = yield ctx.eval('portaldesc')
                except:
                    desttext = None
                # This is a dependency on 'portaldesc', whether or not the
                # property was found.
                if ctx.linktargets:
                    conn.focusactions.update(ctx.linktargets)
                if ctx.dependencies:
                    conn.focusdependencies.update(ctx.dependencies)
                
                if not desttext:
                    desttext = task.app.localize('message.no_portaldesc') # 'The destination is hazy.'
                portalobj['view'] = desttext;
                specres = ['portal', ackey, portalobj, backkey, extratext]
                return (specres, True)

            # Render the portlist.
            if not loctx.iid:
                query = {'plistid':plistid, 'iid':None}
            else:
                query = {'plistid':plistid, '$or':[{'iid':None}, {'iid':loctx.iid}]}
            cursor = task.app.mongodb.portals.find(query)
            ls = []
            while (yield cursor.fetch_next):
                portal = cursor.next_object()
                ls.append(portal)
            # cursor autoclose
            ls.sort(key=lambda portal:portal.get('listpos', 0))

            # Note the dependencies on the world and instance portlist.
            conn.focusdependencies.add( ('portlist', plistid, None) )
            if loctx.iid:
                conn.focusdependencies.add( ('portlist', plistid, loctx.iid) )
            
            subls = []
            for portal in ls:
                desc = yield two.execute.portal_description(task.app, portal, conn.uid, uidiid=loctx.iid, short=True)
                if not desc:
                    continue
                ackey = 'plist' + EvalPropContext.build_action_key()
                conn.focusactions[ackey] = ('focusportal', portal['_id'], plistid)
                desc['target'] = ackey
                if editable and withback:
                    desc['portid'] = str(portal['_id'])
                subls.append(desc)

            editkey = None
            if editable and withback:
                editkey = 'editplist' + EvalPropContext.build_action_key()
                conn.focusactions[editkey] = ('editplist', plistid)
            specres = ['portlist', subls, extratext, editkey]
            return (specres, True)

        # Unknown format, complain
        focusdesc = '[Focus: %s]' % (focusobj,)
        return (focusdesc, False)

    if type(focusobj) is not str:
        return (str(focusobj), False)

    if focusobj.startswith('_'):
        raise Exception('Temporary variable cannot be focus: %s' % (focusobj,))

    ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_DISPSPECIAL)
    focusdesc = yield ctx.eval(focusobj, evaltype=EVALTYPE_SYMBOL)
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
        msg['world'] = {'world':app.localize('label.in_transition'), 'scope':'\u00A0', 'creator':'...'}
        msg['focus'] = False ### probably needs to be something for linking out of the void
        msg['populace'] = False
        msg['locale'] = { 'desc': '...' }
        msg['insttool'] = False
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
        creatorname = app.localize('label.created_by') % (creator['name'],)
    
        if scope['type'] == 'glob':
            scopename = app.localize('label.global_instance_paren')
        elif scope['type'] == 'pers' and scope['uid'] == conn.uid:
            scopename = app.localize('label.personal_instance_you_paren')
        elif scope['type'] == 'pers':
            scopeowner = yield motor.Op(app.mongodb.players.find_one,
                                        {'_id':scope['uid']},
                                        {'name':1})
            scopename = app.localize('label.personal_instance_paren') % (scopeowner['name'],)
        elif scope['type'] == 'grp':
            scopename = app.localize('label.group_instance_paren') % (scope['group'],)
        else:
            scopename = '???'

        msg['world'] = {'world':worldname, 'scope':scopename, 'creator':creatorname}

    if dirty & DIRTY_LOCALE:
        conn.localeactions.clear()
        conn.localedependencies.clear()

        ctx = EvalPropContext(task, loctx=loctx, level=LEVEL_DISPLAY)
        try:
            localedesc = yield ctx.eval('desc')
        except Exception as ex:
            task.log.warning('Exception rendering locale: %s', ex, exc_info=app.debugstacktraces)
            localedesc = '[Exception: %s]' % (str(ex),)
        
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
        conn.populacedependencies.add( ('populace', iid, locid) )
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
        # cursor autoclose
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
                    elif pos > numpeople-2:
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

        try:
            focusobj = playstate.get('focus', None)
            (focusdesc, focusspecial) = yield render_focus(task, loctx, conn, focusobj)
        except Exception as ex:
            task.log.warning('Exception rendering focus: %s', ex, exc_info=app.debugstacktraces)
            focusdesc = '[Exception: %s]' % (str(ex),)
            focusspecial = False

        msg['focus'] = focusdesc
        if focusspecial:
            msg['focusspecial'] = True
    
    if dirty & DIRTY_TOOL:
        conn.toolactions.clear()
        conn.tooldependencies.clear()
        
        tooldesc = False
        try:
            altloctx = two.task.LocContext(uid=loctx.uid, wid=loctx.wid, scid=loctx.scid, iid=loctx.iid, locid=None)
            toolsym = yield two.symbols.find_symbol(app, altloctx, 'instancepane', dependencies=conn.tooldependencies)
            
            if toolsym is not None:
                ctx = EvalPropContext(task, loctx=altloctx, level=LEVEL_DISPLAY)
                try:
                    tooldesc = yield ctx.eval(toolsym, evaltype=EVALTYPE_RAW)
                except Exception as ex:
                    task.log.warning('Exception rendering instancepane: %s', ex, exc_info=app.debugstacktraces)
                    tooldesc = '[Exception: %s]' % (str(ex),)
            
                if ctx.linktargets:
                    conn.toolactions.update(ctx.linktargets)
                if ctx.dependencies:
                    conn.tooldependencies.update(ctx.dependencies)
        except:
            # No instancepane symbol in the world
            pass

        msg['insttool'] = tooldesc
        
    conn.write(msg)

@tornado.gen.coroutine
def try_hook(task, hookname, loctx, label, argfunc=None):
    """Execute a hook function, if one exists. This catches and logs all
    errors.
    The argfunc argument, if present, should be a function that returns a
    map of (underscorey) local variables. (We handle this as a function
    so that we can avoid doing it unless necessary. Probably a trivial
    savings, I know.)
    """
    try:
        hook = yield two.symbols.find_symbol(task.app, loctx, hookname)
    except:
        hook = None
        
    if hook and twcommon.misc.is_typed_dict(hook, 'code'):
        ctx = two.evalctx.EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE, forbid=two.evalctx.EVALCAP_MOVE)
        try:
            if argfunc:
                args = argfunc()
            else:
                args = None
            yield ctx.eval(hook, evaltype=EVALTYPE_RAW, locals=args)
        except Exception as ex:
            task.log.warning('Caught exception (%s): %s', label, ex, exc_info=task.app.debugstacktraces)

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

        if restype == 'editstr':
            key = target[1]
            if not key:
                raise ErrorMessageException('No key given for editstr.')
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
            tup = ('instanceprop', iid, locid, key)
            yield app.propcache.set(tup, val)
            task.set_data_change(tup)
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

        if restype == 'editplist':
            plistid = target[1]
            portlist = yield motor.Op(app.mongodb.portlists.find_one,
                                      {'_id':plistid})
            if not portlist:
                raise ErrorMessageException('Portlist not found.')
            if portlist['type'] != 'world' or portlist['wid'] != loctx.wid:
                raise ErrorMessageException('Portlist not reachable.')
            # The editaccess check was done earlier, and can't be repeated
            # at this point, sadly. But at least we know that the portlist
            # belongs to this world.
            if cmd.edit == 'add':
                portid = ObjectId(cmd.portid)
                portal = yield motor.Op(app.mongodb.portals.find_one,
                                        {'_id':portid})
                if not portal:
                    raise ErrorMessageException('Portal not found.')
                if not isinstance(portal['scid'], ObjectId):
                    raise ErrorMessageException('Portal does not have definite scope.')
                yield create_portal_for_plist(task, loctx.iid, plistid, portal['wid'], portal['scid'], portal['locid'])
                conn.write({'cmd':'message', 'text':app.localize('message.plist_add_ok')}) # 'You add your portal to this collection.'
                return
            if cmd.edit == 'delete':
                portid = ObjectId(cmd.portid)
                portal = yield motor.Op(app.mongodb.portals.find_one,
                                        {'_id':portid})
                if not portal:
                    raise ErrorMessageException('Portal not found.')
                if portal.get('plistid', None) != plistid:
                    raise ErrorMessageException('Portal not in this portlist.')
                if portal.get('iid', None) is None:
                    raise MessageException(app.localize('message.plist_delete_not_instance'))
                if portal.get('iid', None) != loctx.iid:
                    raise ErrorMessageException('Portal not in this instance.')
                yield motor.Op(app.mongodb.portals.remove,
                               {'_id':portid})
                # Data change for anyone watching this portlist
                task.set_data_change( ('portlist', plistid, loctx.iid) )
                conn.write({'cmd':'message', 'text':app.localize('message.plist_delete_ok')}) # 'You delete the portal from this collection.'
                return
            raise ErrorMessageException('Portlist edit not understood: %s.' % (cmd.edit,))
        
        if restype == 'focusportal':
            # Change the current (portlist) focus to a specific entry in
            # that portlist.
            res = yield motor.Op(app.mongodb.playstate.find_one,
                                 {'_id':uid},
                                 {'focus':1})
            curfocus = res.get('focus', None)
            # Make sure the current focus really is the mentioned portlist.
            if not curfocus or type(curfocus) != list or curfocus[0] != 'portlist' or curfocus[1] != target[2]:
                raise ErrorMessageException('Portal list does not match action.')
            curfocus[5] = target[1] # may be None
            
            yield motor.Op(app.mongodb.playstate.update,
                           {'_id':uid},
                           {'$set':{'focus':curfocus}})
            task.set_dirty(uid, DIRTY_FOCUS)
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

            # Figure out the destination scope. This may come from the portal,
            # or the player may have selected an alternate.
            altscid = getattr(cmd, 'scid', None)
            if not altscid:
                newscid = yield portal_resolve_scope(app, portal, uid, loctx.scid, world)
            else:
                newscid = ObjectId(altscid)
                # Check validity of the player's chosen scope.
                yield portal_alt_scope_accessible(app, newscid, uid, world)
            
            player = yield motor.Op(app.mongodb.players.find_one,
                                    {'_id':uid},
                                    {'plistid':1})
            plistid = player['plistid']

            yield create_portal_for_player(app, uid, plistid, newwid, newscid, newlocid)

            conn.write({'cmd':'message', 'text':app.localize('message.copy_ok')}) # 'You copy the portal to your collection.'
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

            # Figure out the destination scope. This may come from the portal,
            # or the player may have selected an alternate.
            altscid = getattr(cmd, 'scid', None)
            if not altscid:
                newscid = yield portal_resolve_scope(app, portal, uid, loctx.scid, world)
            else:
                newscid = ObjectId(altscid)
                # Check validity of the player's chosen scope.
                yield portal_alt_scope_accessible(app, newscid, uid, world)

            # Load up the instance, but only to check minaccess.
            instance = yield motor.Op(app.mongodb.instances.find_one,
                                      {'wid':newwid, 'scid':newscid})
            if instance:
                minaccess = instance.get('minaccess', ACC_VISITOR)
            else:
                minaccess = ACC_VISITOR
            if False: ### check minaccess against scope access!
                task.write_event(uid, app.localize('message.instance_no_access')) # 'You do not have access to this instance.'
                return
        
            res = yield motor.Op(app.mongodb.players.find_one,
                                 {'_id':uid},
                                 {'name':1})
            playername = res['name']

            yield try_hook(task, 'on_leave', loctx, 'leaving loc, linkout',
                           lambda:{
                    '_from':two.execute.LocationProxy(loctx.locid) if loctx.locid else None,
                    '_to':None })
                
            others = yield task.find_locale_players(notself=True)
            if others:
                # Don't need to dirty populace; everyone here has a
                # dependency.
                task.write_event(others, app.localize('action.oportout') % (playername,)) # '%s disappears.'
            task.write_event(uid, app.localize('action.portout')) # 'The world fades away.'

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
            task.set_dirty(uid, DIRTY_FOCUS | DIRTY_LOCALE | DIRTY_WORLD | DIRTY_POPULACE | DIRTY_TOOL)
            task.set_data_change( ('playstate', uid, 'iid') )
            task.set_data_change( ('playstate', uid, 'locid') )
            if loctx.iid:
                task.set_data_change( ('populace', loctx.iid, loctx.locid) )
            task.clear_loctx(uid)
            app.schedule_command({'cmd':'portin', 'uid':uid}, 1.5)
            return

        # End of special-dict targets.
        raise ErrorMessageException('Action not understood: "%s"' % (target,))

    # The target is a string. This may be a simple symbol, or a chunk of
    # code. (But a simple symbol *is* valid code, so we'll just treat it
    # as the latter.)

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
from two.task import DIRTY_ALL, DIRTY_WORLD, DIRTY_LOCALE, DIRTY_POPULACE, DIRTY_FOCUS, DIRTY_TOOL
from two.evalctx import EvalPropContext
from two.evalctx import EVALTYPE_SYMBOL, EVALTYPE_RAW, EVALTYPE_CODE, EVALTYPE_TEXT
from two.evalctx import LEVEL_EXECUTE, LEVEL_DISPSPECIAL, LEVEL_DISPLAY, LEVEL_MESSAGE, LEVEL_FLAT, LEVEL_RAW
from twcommon.access import ACC_VISITOR, ACC_FOUNDER
import two.symbols
import two.propcache
