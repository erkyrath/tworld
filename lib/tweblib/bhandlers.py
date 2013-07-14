"""
The build-related URI request handlers used by Tweb.
"""

import datetime
import random
import json
import ast
import re

from bson.objectid import ObjectId
import tornado.web
import tornado.gen
import tornado.escape

import motor

import tweblib.handlers
import twcommon.misc
from twcommon.misc import sluggify

# Utility class for JSON-encoding objects that contain ObjectIds.
# I still need to think about datetime objects.
class JSONEncoderExtra(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)

# Regexp to match valid Python (2) identifiers. See also sluggify() in
# lib/twcommon/misc.py.
re_valididentifier = re.compile('^[a-zA-Z_][a-zA-Z0-9_]*$')
    

class BuildBaseHandler(tweblib.handlers.MyRequestHandler):
    """Base class for the handlers for build pages. This has some common
    functionality.
    """
    @tornado.gen.coroutine
    def prepare(self):
        """
        Called before every get/post invocation for this handler. We use
        the opportunity to make sure the player is authenticated and a
        builder. We also save the admin flag as self.twisadmin.
        """
        yield self.find_current_session()
        if self.twsessionstatus != 'auth':
            raise tornado.web.HTTPError(403, 'You are not signed in.')
        res = yield motor.Op(self.application.mongodb.players.find_one,
                             { '_id':self.twsession['uid'] })
        if not res:
            raise tornado.web.HTTPError(403, 'You do not exist.')
        self.twisadmin = res.get('admin', False)
        self.twisbuild = (self.twisadmin or res.get('build', False))
        if not self.twisbuild:
            self.redirect('/nobuild')
            return

    def extend_template_namespace(self, map):
        map = super().extend_template_namespace(map)
        map['xsrf_token'] = tornado.escape.xhtml_escape(self.xsrf_token)
        return map

    @tornado.gen.coroutine
    def find_build_world(self, wid):
        """Given the ObjectId of a world, look up the world and make sure
        this player is the creator. We also look up the location list for
        the world, since any build page that cares will have a location
        pop-up.
        """
        world = yield motor.Op(self.application.mongodb.worlds.find_one,
                               { '_id':wid })
        if not world:
            raise Exception('No such world')
        if not self.twisbuild:
            raise tornado.web.HTTPError(403, 'You do not have build access.')
        if world['creator'] != self.twsession['uid'] and not self.twisadmin:
            raise tornado.web.HTTPError(403, 'You did not create this world.')
        
        locations = []
        cursor = self.application.mongodb.locations.find({'wid':wid})
        while (yield cursor.fetch_next):
            loc = cursor.next_object()
            locations.append(loc)
        # cursor autoclose
        locations.sort(key=lambda loc:loc['_id']) ### or other criterion?

        return (world, locations)

    @tornado.gen.coroutine
    def check_world_arguments(self, wid, locid, playerok=False):
        """Given a world ObjectId (and optional location too), look
        them up and make sure this player is the creator. This is similar
        to find_build_world, but tuned for the AJAX POST handlers rather
        than full pages.
        """
        world = yield motor.Op(self.application.mongodb.worlds.find_one,
                               { '_id':wid })
        if not world:
            raise Exception('No such world')
        if not self.twisbuild:
            raise tornado.web.HTTPError(403, 'You do not have build access.')
        if world['creator'] != self.twsession['uid'] and not self.twisadmin:
            raise tornado.web.HTTPError(403, 'You did not create this world.')
        
        if locid is None:
            loc = None
        elif locid == '$player':
            if not playerok:
                raise Exception('Player property not permitted')
            loc = locid
        else:
            loc = yield motor.Op(self.application.mongodb.locations.find_one,
                                 { '_id':locid })
            if not loc:
                raise Exception('No such location')

        return (world, loc)

    def export_prop_array(self, ls):
        """Given an array of property values (from the db), return an array
        suitable for handing over to the client for editing. This means
        an array of type-keyed dicts. We wrap all native values as {value}
        objects.
        """
        res = []
        for prop in ls:
            val = prop['val']
            if type(val) is dict and val.get('type', None):
                pass
            else:
                ### If I defaulted to double-quotes for strings, it would be a bit tidier.
                val = { 'type':'value', 'value':repr(val) }
            newprop = {'key':prop['key'], 'val':val, 'id':str(prop['_id'])}
            res.append(newprop)
        return res

    def import_property(self, prop):
        """Given a type-keyed dict from the client, convert it into database
        form. Raises an exception if a problem occurs.
        This is written strictly; it never allows in typed structures that
        we don't recognize. 
        """
        valtype = prop['type']
        if valtype == 'value':
            ### This does not cope with ObjectIds, datetimes, or other
            ### such items.
            ### It also allows arbitrary typed dicts, which makes a mockery
            ### of the strictness I mentioned.
            val = prop.get('value', None)
            if not val:
                raise Exception('Value entry may not be blank')
            return ast.literal_eval(val)
        if valtype == 'text':
            return { 'type':valtype, 'text':prop.get('text', None) }
        if valtype == 'code':
            return { 'type':valtype, 'text':prop.get('text', None) }
        if valtype == 'event':
            return { 'type':valtype,
                     'text':prop.get('text', None),
                     'otext':prop.get('otext', None) }
        if valtype == 'move':
            return { 'type':valtype,
                     'loc':prop.get('loc', None),
                     'text':prop.get('text', None),
                     'oleave':prop.get('oleave', None),
                     'oarrive':prop.get('oarrive', None) }
        raise Exception('Unknown property type: %s' % (valtype,))

class BuildMainHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self):
        worlds = []
        cursor = self.application.mongodb.worlds.find({'creator':self.twsession['uid']}, {'name':1})
        while (yield cursor.fetch_next):
            world = cursor.next_object()
            worlds.append({'name':world['name'], 'id':str(world['_id'])})
        # cursor autoclose
        worlds.sort(key=lambda world:world['id']) ### or other criterion?
        self.render('build_main.html', worlds=worlds)
        
class BuildWorldHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self, wid):
        wid = ObjectId(wid)
        (world, locations) = yield self.find_build_world(wid)

        worldname = world.get('name', '???')
        # This array must be handed to the client to construct the pop-up
        # location menu.
        locarray = [ {'id':str(loc['_id']), 'name':loc['name']} for loc in locations ]

        worldprops = []
        cursor = self.application.mongodb.worldprop.find({'wid':wid, 'locid':None}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            worldprops.append(prop)
        # cursor autoclose
        worldprops.sort(key=lambda prop:prop['_id']) ### or other criterion?

        playerprops = []
        cursor = self.application.mongodb.wplayerprop.find({'wid':wid, 'uid':None}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            playerprops.append(prop)
        # cursor autoclose
        playerprops.sort(key=lambda prop:prop['_id']) ### or other criterion?

        encoder = JSONEncoderExtra()
        worldproparray = encoder.encode(self.export_prop_array(worldprops))
        playerproparray = encoder.encode(self.export_prop_array(playerprops))

        self.render('build_world.html',
                    wid=str(wid), worldname=worldname,
                    worldnamejs=json.dumps(worldname),
                    worldcopyable=json.dumps(world.get('copyable', False)),
                    worldinstancing=json.dumps(world.get('instancing', 'standard')),
                    locarray=json.dumps(locarray), locations=locations,
                    worldproparray=worldproparray, playerproparray=playerproparray)

class BuildLocHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self, locid):
        locid = ObjectId(locid)
        location = yield motor.Op(self.application.mongodb.locations.find_one,
                                  { '_id':locid })
        if not location:
            raise Exception('No such location')
        wid = location['wid']
        (world, locations) = yield self.find_build_world(wid)

        worldname = world.get('name', '???')
        # This array must be handed to the client to construct the pop-up
        # location menu.
        locarray = [ {'id':str(loc['_id']), 'name':loc['name']} for loc in locations ]

        lockey = location.get('key')
        locname = location.get('name', '???')

        props = []
        cursor = self.application.mongodb.worldprop.find({'wid':wid, 'locid':locid}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            props.append(prop)
        # cursor autoclose
        props.sort(key=lambda prop:prop['_id']) ### or other criterion?

        encoder = JSONEncoderExtra()
        proparray = encoder.encode(self.export_prop_array(props))
        
        self.render('build_loc.html',
                    wid=str(wid), worldname=worldname,
                    locarray=json.dumps(locarray), locations=locations,
                    locname=locname, locnamejs=json.dumps(locname),
                    locid=str(locid), lockey=json.dumps(lockey),
                    proparray=proparray)

class BuildSetPropHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            key = self.get_argument('key')
            propid = ObjectId(self.get_argument('id'))
            wid = ObjectId(self.get_argument('world'))
            locid = self.get_argument('loc')
            if locid == '$realm':
                locid = None
            elif locid == '$player':
                pass  # special case
            else:
                locid = ObjectId(locid)
    
            (world, loc) = yield self.check_world_arguments(wid, locid, playerok=True)

            key = sluggify(key)
            if not re_valididentifier.match(key):
                raise Exception('Invalid key name')

            # Construct the new property, except for the value
            if loc == '$player':
                prop = { '_id':propid, 'key':key, 'wid':wid, 'uid':None }
            else:
                prop = { '_id':propid, 'key':key, 'wid':wid, 'locid':locid }
                
            trashprop = None
            
            # Fetch the current version of the property (possibly None).
            # If that exists, create an entry for the trashprop queue.
            # Also check for a version with the same key-name (also may be
            # None).
            if loc == '$player':
                # We can only edit all-player wplayerprops here.
                oprop = yield motor.Op(self.application.mongodb.wplayerprop.find_one,
                                       { '_id':propid })
                kprop = yield motor.Op(self.application.mongodb.wplayerprop.find_one,
                                       { 'wid':wid, 'uid':None, 'key':key })
                if oprop:
                    try:
                        trashprop = { 'wid':oprop['wid'], 'uid':oprop['uid'],
                                      'key':oprop['key'], 'val':oprop['val'],
                                      'origtype':'wplayerprop',
                                      'changed':twcommon.misc.now(),
                                      }
                    except:
                        pass
            else:
                oprop = yield motor.Op(self.application.mongodb.worldprop.find_one,
                                       { '_id':propid })
                kprop = yield motor.Op(self.application.mongodb.worldprop.find_one,
                                       { 'wid':wid, 'locid':locid, 'key':key })
                if oprop:
                    try:
                        trashprop = { 'wid':oprop['wid'], 'locid':oprop['locid'],
                                      'key':oprop['key'], 'val':oprop['val'],
                                      'origtype':'worldprop',
                                      'changed':twcommon.misc.now(),
                                      }
                    except:
                        pass

            if self.get_argument('delete', False):
                if trashprop:
                    try:
                        yield motor.Op(self.application.mongodb.trashprop.insert, trashprop)
                    except Exception as ex:
                        self.application.twlog.warning('Unable to add trashprop: %s', ex)

                # And now we delete it.
                if loc == '$player':
                    yield motor.Op(self.application.mongodb.wplayerprop.remove,
                                   { '_id':propid })
                    dependency = ('wplayerprop', wid, None, key)
                else:
                    yield motor.Op(self.application.mongodb.worldprop.remove,
                                   { '_id':propid })
                    dependency = ('worldprop', wid, locid, key)

                # Send dependency key to tworld
                try:
                    encoder = JSONEncoderExtra()
                    depmsg = encoder.encode({ 'cmd':'notifydatachange', 'change':dependency })
                    self.application.twservermgr.tworld_write(0, depmsg)
                except Exception as ex:
                    self.application.twlog.warning('Unable to notify tworld of data change: %s', ex)

                # We have to return all the property information (except for
                # the value) so the client knows what row to delete.
                returnprop = {'key':prop['key'], 'id':str(prop['_id'])}
                self.write( { 'loc':self.get_argument('loc'), 'delete':True, 'prop':returnprop } )
                return

            newval = self.get_argument('val')
            if len(newval) > 4000:
                raise Exception('Property value is too long')
            newval = json.loads(newval)
            newval = self.import_property(newval)
            prop['val'] = newval

            # Make sure this doesn't collide with an existing key (in a
            # different property).
            if kprop and kprop['_id'] != propid:
                raise Exception('A property with that key already exists.')

            if trashprop:
                try:
                    yield motor.Op(self.application.mongodb.trashprop.insert, trashprop)
                except Exception as ex:
                    self.application.twlog.warning('Unable to add trashprop: %s', ex)

            dependency2 = None
            # And now we write it.
            if loc == '$player':
                yield motor.Op(self.application.mongodb.wplayerprop.update,
                               { '_id':propid }, prop, upsert=True)
                dependency = ('wplayerprop', wid, None, key)
                if oprop and key != oprop['key']:
                    dependency2 = ('wplayerprop', wid, None, oprop['key'])
            else:
                yield motor.Op(self.application.mongodb.worldprop.update,
                               { '_id':propid }, prop, upsert=True)
                dependency = ('worldprop', wid, locid, key)
                if oprop and key != oprop['key']:
                    dependency2 = ('worldprop', wid, locid, oprop['key'])

            # Send dependency key to tworld
            try:
                encoder = JSONEncoderExtra()
                depmsg = encoder.encode({ 'cmd':'notifydatachange', 'change':dependency })
                self.application.twservermgr.tworld_write(0, depmsg)
                if dependency2:
                    depmsg = encoder.encode({ 'cmd':'notifydatachange', 'change':dependency2 })
                    self.application.twservermgr.tworld_write(0, depmsg)
            except Exception as ex:
                self.application.twlog.warning('Unable to notify tworld of data change: %s', ex)

            # Converting the value for the javascript client goes through
            # this array-based call, because I am sloppy like that.
            returnprop = self.export_prop_array([prop])[0]
            self.write( { 'loc':self.get_argument('loc'), 'prop':returnprop } )
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (setting property): %s', ex)
            self.write( { 'error': str(ex) } )

class BuildAddPropHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            wid = ObjectId(self.get_argument('world'))
            locid = self.get_argument('loc')
            if locid == '$realm':
                locid = None
            elif locid == '$player':
                pass  # special case
            else:
                locid = ObjectId(locid)
    
            (world, loc) = yield self.check_world_arguments(wid, locid, playerok=True)

            # Now we have to invent a fresh new prop key. This is kind
            # of a nuisance.
            counter = 0
            while True:
                key = 'key_%d' % (counter,)
                if loc == '$player':
                    kprop = yield motor.Op(self.application.mongodb.wplayerprop.find_one,
                                       { 'wid':wid, 'uid':None, 'key':key })
                else:
                    kprop = yield motor.Op(self.application.mongodb.worldprop.find_one,
                                       { 'wid':wid, 'locid':locid, 'key':key })
                if not kprop:
                    break
                counter = counter+1
                if counter >= 5:
                    # Getting trapped in a linear loop is dumb.
                    counter = counter + random.randrange(50)

            # Construct the new property, with a boring default value
            if loc == '$player':
                prop = { 'key':key, 'wid':wid, 'uid':None }
            else:
                prop = { 'key':key, 'wid':wid, 'locid':locid }
            prop['val'] = { 'type':'text' }
            
            # And now we write it.
            if loc == '$player':
                propid = yield motor.Op(self.application.mongodb.wplayerprop.insert,
                                        prop)
                dependency = ('wplayerprop', wid, None, key)
            else:
                propid = yield motor.Op(self.application.mongodb.worldprop.insert,
                                        prop)
                dependency = ('worldprop', wid, locid, key)

            prop['_id'] = propid

            # Send dependency key to tworld. (Theoretically, no player should
            # be holding a dependency on a brand-new key. But we'll be
            # paranoid.
            try:
                encoder = JSONEncoderExtra()
                depmsg = encoder.encode({ 'cmd':'notifydatachange', 'change':dependency })
                self.application.twservermgr.tworld_write(0, depmsg)
            except Exception as ex:
                self.application.twlog.warning('Unable to notify tworld of data change: %s', ex)

            # Converting the value for the javascript client goes through
            # this array-based call, because I am sloppy like that.
            returnprop = self.export_prop_array([prop])[0]
            self.write( { 'loc':self.get_argument('loc'), 'prop':returnprop } )
            
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (adding property): %s', ex)
            self.write( { 'error': str(ex) } )

class BuildAddLocHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            wid = ObjectId(self.get_argument('world'))
    
            (world, dummy) = yield self.check_world_arguments(wid, None)

            # Now we have to invent a fresh new loc key. This is kind
            # of a nuisance.
            counter = 0
            while True:
                key = 'loc_%d' % (counter,)
                oloc = yield motor.Op(self.application.mongodb.locations.find_one,
                                      { 'wid':wid, 'key':key })
                if not oloc:
                    break
                counter = counter+1
                if counter >= 5:
                    # Getting trapped in a linear loop is dumb.
                    counter = counter + random.randrange(50)

            loc = { 'key':key, 'wid':wid, 'name':'New Location' }
            locid = yield motor.Op(self.application.mongodb.locations.insert,
                                   loc)

            # Also set up a desc property. Every location should have one.
            prop = { 'wid':wid, 'locid':locid, 'key':'desc',
                     'val':{ 'type':'text', 'text':'You are here.' } }
            propid = yield motor.Op(self.application.mongodb.worldprop.insert,
                                    prop)

            self.write( { 'id':str(locid) } )
            
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (adding location): %s', ex)
            self.write( { 'error': str(ex) } )

class BuildSetDataHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            name = self.get_argument('name')
            value = self.get_argument('val')
            wid = ObjectId(self.get_argument('world'))
            locid = self.get_argument('loc', None)
            if locid:
                locid = ObjectId(locid)
    
            (world, loc) = yield self.check_world_arguments(wid, locid)

            if name == 'lockey':
                if not locid:
                    raise Exception('No location declared')
                value = sluggify(value)
                if not re_valididentifier.match(value):
                    raise Exception('Invalid key name')
                oloc = yield motor.Op(self.application.mongodb.locations.find_one,
                                     { 'wid':wid, 'key':value })
                if oloc and oloc['_id'] != locid:
                    raise Exception('A location with this key already exists.')
                yield motor.Op(self.application.mongodb.locations.update,
                               { '_id':locid },
                               { '$set':{'key':value} })
                self.write( { 'val':value } )
                return

            if name == 'locname':
                if not locid:
                    raise Exception('No location declared')
                yield motor.Op(self.application.mongodb.locations.update,
                               { '_id':locid },
                               { '$set':{'name':value} })
                ### dependency change for location name?
                self.write( { 'val':value } )
                return

            if name == 'worldname':
                yield motor.Op(self.application.mongodb.worlds.update,
                               { '_id':wid },
                               { '$set':{'name':value} })
                self.write( { 'val':value } )
                return
            
            if name == 'copyportal':
                if not locid:
                    raise Exception('No location declared')
                uid = self.twsession['uid']
                # The server will have to figure out scope.
                msg = { 'cmd':'buildcopyportal', 'uid':str(uid), 'locid':str(locid), 'wid':str(wid) }
                self.application.twservermgr.tworld_write(0, msg)
                # Any failure in this request will not be returned to the
                # client. Oh well.
                self.write( { 'ok':True } )
                return

            raise Exception('Data not recognized: %s' % (name,))
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (setting data): %s', ex)
            self.write( { 'error': str(ex) } )

class BuildDelLocHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            wid = ObjectId(self.get_argument('world'))
            locid = self.get_argument('loc', None)
            if locid:
                locid = ObjectId(locid)

            (world, loc) = yield self.check_world_arguments(wid, locid)

            if not locid:
                raise Exception('No location declared')

            ### Have not tested how this affects portals that link to the
            ### location. Or people in the location!

            # First delete all world properties in this location.
            yield motor.Op(self.application.mongodb.worldprop.remove,
                           { 'wid':wid, 'locid':locid })

            # Then the location itself.
            yield motor.Op(self.application.mongodb.locations.remove,
                           { '_id':locid })

            # The result value isn't used for anything.
            self.write( { 'ok':True } )
            
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (setting data): %s', ex)
            self.write( { 'error': str(ex) } )


class BuildAddWorldHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            uid = self.twsession['uid']
            world = { 'creator':uid, 'name':'New World',
                      'copyable':True, 'instancing':'standard' }

            wid = yield motor.Op(self.application.mongodb.worlds.insert,
                                 world)
            self.write( { 'id':str(wid) } )
        
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (setting data): %s', ex)
            self.write( { 'error': str(ex) } )

