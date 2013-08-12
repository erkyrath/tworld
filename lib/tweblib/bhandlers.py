"""
The build-related URI request handlers used by Tweb.
"""

import datetime
import random
import json
import ast
import re
import collections

from bson.objectid import ObjectId
import tornado.web
import tornado.gen
import tornado.escape

import motor

import tweblib.handlers
import twcommon.misc
from twcommon.misc import sluggify

# Utility class for JSON-encoding objects that contain ObjectIds.
class JSONEncoderExtra(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime.datetime):
            return {'type':'datetime', 'value':twcommon.misc.gen_datetime_format(obj)}
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
    def check_world_arguments(self, wid, locid, plistid=None, playerok=False):
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
            if loc['wid'] != wid:
                raise Exception('Location is not in this world')

        if plistid is not None:
            plist = yield motor.Op(self.application.mongodb.portlists.find_one,
                                     { '_id':plistid })
            if not plist:
                raise Exception('Portlist not found')
            if plist['type'] != 'world':
                raise Exception('Portlist is not world-level')
            if plist['wid'] != wid:
                raise Exception('Portlist not in this world')

        return (world, loc)

    def export_prop_array(self, ls):
        """Given an array of property values (from the db), return an array
        suitable for handing over to the client for editing. This means
        an array of type-keyed dicts. We wrap all native values as {value}
        objects.

        We leave ObjectId objects alone. They will be translated
        at the JSONEncoder level.
        """
        res = []
        for prop in ls:
            val = prop['val']
            if type(val) is dict:
                valtype = val.get('type', None)
                if not valtype:
                    val = { 'type':'value', 'value':repr(val) }
                elif valtype == 'editstr':
                    if 'editaccess' in val:
                        try:
                            val['editaccess'] = twcommon.access.name_for_level(val['editaccess']).lower()
                        except:
                            del val['editaccess']
                elif valtype == 'portlist':
                    if 'editaccess' in val:
                        try:
                            val['editaccess'] = twcommon.access.name_for_level(val['editaccess']).lower()
                        except:
                            del val['editaccess']
                    if 'readaccess' in val:
                        try:
                            val['readaccess'] = twcommon.access.name_for_level(val['readaccess']).lower()
                        except:
                            del val['readaccess']
                else:
                    pass
            elif isinstance(val, datetime.datetime):
                val = { 'type':'datetime', 'value':twcommon.misc.gen_datetime_format(val) }
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
        if valtype == 'datetime':
            val = prop.get('value', None)
            if not val:
                return twcommon.misc.now().replace(microsecond=0)
            val = twcommon.misc.gen_datetime_parse(val)
            return val
        if valtype == 'text':
            res = { 'type':valtype }
            if 'text' in prop:
                res['text'] = prop['text']
            return res
        if valtype == 'code':
            res = { 'type':valtype }
            if 'text' in prop:
                res['text'] = prop['text']
            return res
        if valtype == 'event':
            res = { 'type':valtype }
            if 'text' in prop:
                res['text'] = prop['text']
            if 'otext' in prop:
                res['otext'] = prop['otext']
            return res
        if valtype == 'panic':
            res = { 'type':valtype }
            if 'text' in prop:
                res['text'] = prop['text']
            if 'otext' in prop:
                res['otext'] = prop['otext']
            return res
        if valtype == 'move':
            res = { 'type':valtype }
            if 'loc' in prop:
                loc = sluggify(prop['loc'])
                res['loc'] = loc
            if 'text' in prop:
                res['text'] = prop['text']
            if 'oleave' in prop:
                res['oleave'] = prop['oleave']
            if 'oarrive' in prop:
                res['oarrive'] = prop['oarrive']
            return res
        if valtype == 'editstr':
            res = { 'type':valtype }
            if 'key' in prop:
                key = sluggify(prop['key'])
                res['key'] = key
            if 'editaccess' in prop:
                try:
                    editaccess = twcommon.access.level_named(prop['editaccess'])
                except:
                    namels = twcommon.access.level_name_list()
                    raise Exception('Access level must be in %s' % (namels,))
                res['editaccess'] = editaccess
            if 'label' in prop:
                res['label'] = prop['label']
            if 'text' in prop:
                res['text'] = prop['text']
            if 'otext' in prop:
                res['otext'] = prop['otext']
            return res
        if valtype == 'portlist':
            res = { 'type':valtype }
            if 'plistkey' in prop:
                plistkey = sluggify(prop['plistkey'])
                res['plistkey'] = plistkey
            if 'editaccess' in prop:
                try:
                    editaccess = twcommon.access.level_named(prop['editaccess'])
                except:
                    namels = twcommon.access.level_name_list()
                    raise Exception('Access level must be in %s' % (namels,))
                res['editaccess'] = editaccess
            if 'readaccess' in prop:
                try:
                    readaccess = twcommon.access.level_named(prop['readaccess'])
                except:
                    namels = twcommon.access.level_name_list()
                    raise Exception('Access level must be in %s' % (namels,))
                res['readaccess'] = readaccess
            if 'text' in prop:
                res['text'] = prop['text']
            if 'focus' in prop:
                try:
                    if twcommon.misc.gen_bool_parse(prop['focus']):
                        res['focus'] = True
                    else:
                        res.pop('focus', None)
                except:
                    raise Exception('Focus flag must be true or false')
            return res
        raise Exception('Unknown property type: %s' % (valtype,))

    @tornado.gen.coroutine
    def export_portal_array(self, ls):
        """Given an array of portal objects (from the db), return an array
        suitable for handing over to the client for editing.
        (This has to be yieldy, because we're looking up the names of
        everything.)
        """
        res = []
        for portal in ls:
            try:
                world = yield motor.Op(self.application.mongodb.worlds.find_one,
                                       {'_id':portal['wid']})
                worldname = world.get('name', '???')
                creator = yield motor.Op(self.application.mongodb.players.find_one,
                                         {'_id':world['creator']}, {'name':1})
                if creator:
                    creatorname = creator.get('name', '???')
                else:
                    creatorname = '???'
                if portal['scid'] in ('personal', 'global', 'same'):
                    scope = None
                    scopetype = None
                    scopename = None
                else:
                    scope = yield motor.Op(self.application.mongodb.scopes.find_one,
                                           {'_id':portal['scid']})
                    scopetype = scope['type']
                    scopename = None
                    if scopetype == 'grp':
                        scopename = scope.get('group', '???')
                    elif scopetype == 'pers':
                        scopeplayer = yield motor.Op(self.application.mongodb.players.find_one,
                                                     {'_id':scope['uid']},
                                                     {'name':1})
                        scopename = '???'
                        if scopeplayer:
                            scopename = scopeplayer.get('name', '???')
                loc = yield motor.Op(self.application.mongodb.locations.find_one,
                                     {'_id':portal['locid']})
                if loc:
                    locname = loc.get('name', '???')
                else:
                    locname = '???'
                # wid, locid are not used by the client (scid is)
                newprop = { 'id':str(portal['_id']),
                            'listpos':portal.get('listpos', 0.0),
                            'scid':str(portal['scid']),
                            'worldname':worldname,
                            'locname':locname,
                            'creatorname':creatorname,
                            'instancing':world.get('instancing', 'standard'),
                            'scopetype':scopetype, 'scopename':scopename,
                            }
                res.append(newprop)
            except Exception as ex:
                self.application.twlog.warning('Unable to convert portal: %s', ex)
            
        return res

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

        portlists = []
        cursor = self.application.mongodb.portlists.find({'wid':wid, 'type':'world'})
        while (yield cursor.fetch_next):
            plist = cursor.next_object()
            portlists.append(plist)
        # cursor autoclose
        portlists.sort(key=lambda plist:plist['_id']) ### or other criterion?

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
                    worldnameslug=sluggify(worldname),
                    worldcopyable=json.dumps(world.get('copyable', False)),
                    worldinstancing=json.dumps(world.get('instancing', 'standard')),
                    locarray=json.dumps(locarray), locations=locations,
                    portlists=portlists,
                    worldproparray=worldproparray, playerproparray=playerproparray)

class BuildTrashWorldHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self, wid):
        wid = ObjectId(wid)
        (world, locations) = yield self.find_build_world(wid)

        worldname = world.get('name', '???')
        # This array must be handed to the client to construct the pop-up
        # location menu.
        locarray = [ {'id':str(loc['_id']), 'name':loc['name']} for loc in locations ]

        PER_PAGE = 10
        try:
            page = int(self.get_argument('page', 0))
            page = max(0, page)
        except:
            page = 0

        trashprops = []
        cursor = self.application.mongodb.trashprop.find(
            {'wid':wid},
            sort=[('changed', motor.pymongo.DESCENDING)],
            skip=page*PER_PAGE,
            limit=PER_PAGE)
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            trashprops.append(prop)
        # cursor autoclose

        encoder = JSONEncoderExtra()
        trashproparray = encoder.encode(self.export_prop_array(trashprops))

        self.render('build_trash.html',
                    wid=str(wid), worldname=worldname,
                    locarray=json.dumps(locarray),
                    pagingnum=page,
                    hasnext=int(len(trashprops) == PER_PAGE), hasprev=int(page > 0),
                    trashproparray=trashproparray)

class BuildPortListHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self, plistid):
        plistid = ObjectId(plistid)
        plist = yield motor.Op(self.application.mongodb.portlists.find_one,
                               { '_id':plistid })
        if not plist:
            raise Exception('No such portlist')
        if plist['type'] != 'world' or 'wid' not in plist:
            raise Exception('Portlist is not in a world')
        plistkey = plist.get('key')
            
        wid = plist['wid']
        (world, locations) = yield self.find_build_world(wid)

        worldname = world.get('name', '???')
        # This array must be handed to the client to construct the pop-up
        # location menu.
        locarray = [ {'id':str(loc['_id']), 'name':loc['name']} for loc in locations ]

        portals = []
        cursor = self.application.mongodb.portals.find({'plistid':plistid, 'iid':None})
        while (yield cursor.fetch_next):
            port = cursor.next_object()
            portals.append(port)
        # cursor autoclose
        portals.sort(key=lambda port:port.get('listpos', 0.0))

        # Fetch the player's personal list (for available options in the
        # build screen). Also the player's list of available scopes.
        selfportals = []
        selfscopes = []
        player = yield motor.Op(self.application.mongodb.players.find_one,
                                {'_id':self.twsession['uid']},
                                {'plistid':1, 'scid':1})
        if player and 'plistid' in player:
            cursor = self.application.mongodb.portals.find({'plistid':player['plistid'], 'iid':None})
            while (yield cursor.fetch_next):
                port = cursor.next_object()
                selfportals.append(port)
            # cursor autoclose
        selfportals.sort(key=lambda port:port.get('listpos', 0.0))

        config = yield motor.Op(self.application.mongodb.config.find_one,
                                {'key':'globalscopeid'})
        selfscopes.append({'id':str(config['val']), 'name':'Global'})
        if player and 'scid' in player:
            selfscopes.append({'id':str(player['scid']), 'name':'Personal: (you)'})
        ### And any personal scopes you have access to
        ### And any group scopes you have access to

        encoder = JSONEncoderExtra()
        clientls = yield self.export_portal_array(portals)
        portarray = encoder.encode(clientls)
        clientls = yield self.export_portal_array(selfportals)
        selfportarray = encoder.encode(clientls)
            
        self.render('build_portlist.html',
                    wid=str(wid), worldname=worldname,
                    locarray=json.dumps(locarray), locations=locations,
                    plistid=str(plistid), plistkey=json.dumps(plistkey),
                    portarray=portarray, selfportarray=selfportarray,
                    selfscopes=selfscopes,
                    withblurb=(len(portals) == 0))


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
                    proparray=proparray,
                    withblurb=(len(props) <= 1))

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
                    if oprop['wid'] != wid:
                        raise Exception('Property not in this world')
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
                    if oprop['wid'] != wid:
                        raise Exception('Property not in this world')
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

            # Send dependency key to tworld. (Two of them, if we changed the
            # property key!)
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

class BuildAddPortListHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            wid = ObjectId(self.get_argument('world'))
    
            (world, dummy) = yield self.check_world_arguments(wid, None)

            # Now we have to invent a fresh new plist key. This is kind
            # of a nuisance.
            counter = 0
            while True:
                key = 'portlist_%d' % (counter,)
                oplist = yield motor.Op(self.application.mongodb.portlists.find_one,
                                        { 'wid':wid, 'key':key, 'type':'world' })
                if not oplist:
                    break
                counter = counter+1
                if counter >= 5:
                    # Getting trapped in a linear loop is dumb.
                    counter = counter + random.randrange(50)

            plist = { 'key':key, 'wid':wid, 'type':'world' }
            plistid = yield motor.Op(self.application.mongodb.portlists.insert,
                                   plist)

            self.write( { 'id':str(plistid) } )
            
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (adding portlist): %s', ex)
            self.write( { 'error': str(ex) } )

class BuildDelPortListHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            wid = ObjectId(self.get_argument('world'))
            plistid = self.get_argument('plist', None)
            if plistid:
                plistid = ObjectId(plistid)
            if not plistid:
                raise Exception('No portlist declared')

            (world, dummy) = yield self.check_world_arguments(wid, None, plistid=plistid)

            # First delete all portals associated with this list.
            # (This includes instance members.)
            yield motor.Op(self.application.mongodb.portals.remove,
                           { 'plistid':plistid })

            # Then the list itself.
            yield motor.Op(self.application.mongodb.portlists.remove,
                           { '_id':plistid })

            try:
                dependency = ('portlist', plistid, None)
                encoder = JSONEncoderExtra()
                depmsg = encoder.encode({ 'cmd':'notifydatachange', 'change':dependency })
                self.application.twservermgr.tworld_write(0, depmsg)
            except Exception as ex:
                self.application.twlog.warning('Unable to notify tworld of data change: %s', ex)
                
            # The result value isn't used for anything.
            self.write( { 'ok':True } )
            
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (deleting portlist): %s', ex)
            self.write( { 'error': str(ex) } )

class BuildAddPortHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            wid = ObjectId(self.get_argument('world'))
            plistid = self.get_argument('plist', None)
            if plistid:
                plistid = ObjectId(plistid)
            if not plistid:
                raise Exception('No portlist declared')

            (world, dummy) = yield self.check_world_arguments(wid, None, plistid=plistid)

            # Newly-created portal is always to the start location, because
            # that's easier.
            res = yield motor.Op(self.application.mongodb.config.find_one,
                                 {'key':'startworldloc'})
            lockey = res['val']
            res = yield motor.Op(self.application.mongodb.config.find_one,
                                 {'key':'startworldid'})
            newwid = res['val']
            res = yield motor.Op(self.application.mongodb.locations.find_one,
                                 {'wid':newwid, 'key':lockey})
            newlocid = res['_id']
            
            portal = { 'plistid':plistid, 'iid':None,
                       'wid':newwid, 'scid':'personal', 'locid':newlocid,
                       ### 'listpos':,
                       }

            portid = yield motor.Op(self.application.mongodb.portals.insert,
                                    portal)
            portal['_id'] = portid
            
            try:
                dependency = ('portlist', plistid, None)
                encoder = JSONEncoderExtra()
                depmsg = encoder.encode({ 'cmd':'notifydatachange', 'change':dependency })
                self.application.twservermgr.tworld_write(0, depmsg)
            except Exception as ex:
                self.application.twlog.warning('Unable to notify tworld of data change: %s', ex)
                
            # Converting the value for the javascript client goes through
            # this array-based call, because I am sloppy like that.
            returnportal = yield self.export_portal_array([portal])
            returnportal = returnportal[0]
            self.write( { 'port':returnportal } )
            
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (adding portal): %s', ex)
            self.write( { 'error': str(ex) } )

class BuildSetPortHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def post(self):
        try:
            wid = ObjectId(self.get_argument('world'))
            plistid = self.get_argument('plist', None)
            if plistid:
                plistid = ObjectId(plistid)
            if not plistid:
                raise Exception('No portlist declared')

            action = self.get_argument('action', None)
            portid = self.get_argument('id', None)
            if not portid:
                raise Exception('No portal declared')
            portid = ObjectId(portid)

            (world, dummy) = yield self.check_world_arguments(wid, None, plistid=plistid)

            port = yield motor.Op(self.application.mongodb.portals.find_one,
                                     { '_id':portid })
            if not port:
                raise Exception('No such portal')
            if port['plistid'] != plistid:
                raise Exception('Portal is not in this portlist')

            if action == 'delete':
                yield motor.Op(self.application.mongodb.portals.remove,
                               { '_id':portid })
                # We have to return enough of the portal information that
                # the client knows what row to delete.
                returnport = { 'id':str(portid) }
                self.write( { 'delete':True, 'port':returnport } )
                return

            if action == 'world':
                copyportid = self.get_argument('copyport', None)
                if not copyportid:
                    raise Exception('No portal selected')
                copyportid = ObjectId(copyportid)
                copyport = yield motor.Op(self.application.mongodb.portals.find_one,
                                          { '_id':copyportid })
                if not copyport:
                    raise Exception('Portal not found')
                player = yield motor.Op(self.application.mongodb.players.find_one,
                                        {'_id':self.twsession['uid']},
                                        {'plistid':1})
                if player['plistid'] != copyport['plistid']:
                    raise Exception('Portal is not in your personal collection')
                port['wid'] = copyport['wid']
                port['scid'] = copyport['scid']
                port['locid'] = copyport['locid']
                yield motor.Op(self.application.mongodb.portals.update,
                               { '_id':portid },
                               { '$set':{'wid':copyport['wid'],
                                         'scid':copyport['scid'],
                                         'locid':copyport['locid']} })

                # Converting the value for the javascript client goes through
                # this array-based call, because I am sloppy like that.
                returnportal = yield self.export_portal_array([port])
                returnportal = returnportal[0]
                self.write( { 'port':returnportal } )
                return

            if action == 'instance':
                newscid = self.get_argument('scope')
                if newscid in ('personal', 'global', 'same'):
                    pass  # always okay
                else:
                    newscid = ObjectId(newscid)
                    scope = yield motor.Op(self.application.mongodb.scopes.find_one,
                                           { '_id':newscid })
                    if not scope:
                        raise Exception('No scope selected')
                    scopetype = scope['type']
                    if scopetype == 'glob':
                        pass  # global scope always okay
                    elif scopetype == 'pers':
                        if scope['uid'] == self.twsession['uid']:
                            pass  # your personal scope always okay
                        else:
                            ### or any personal scopes you have access to
                            raise Exception('Not your personal scope')
                    elif scopetype == 'grp':
                        raise Exception('Group scopes not yet available')
                    else:
                        raise Exception('Unknown scope type')
                port['scid'] = newscid
                yield motor.Op(self.application.mongodb.portals.update,
                               { '_id':portid },
                               { '$set':{'scid':newscid} })

                # Converting the value for the javascript client goes through
                # this array-based call, because I am sloppy like that.
                returnportal = yield self.export_portal_array([port])
                returnportal = returnportal[0]
                self.write( { 'port':returnportal } )
                return
            
            raise Exception('Action not understood.')
        except Exception as ex:
            # Any exception that occurs, return as an error message.
            self.application.twlog.warning('Caught exception (setting portal): %s', ex)
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
            
            if name == 'worldinstancing':
                value = value.lower()
                if value not in ("solo", "shared", "standard"):
                    raise Exception('Instancing must be "solo", "shared", or "standard"')
                yield motor.Op(self.application.mongodb.worlds.update,
                               { '_id':wid },
                               { '$set':{'instancing':value} })
                self.write( { 'val':value } )
                return
            
            if name == 'worldcopyable':
                value = value.lower()
                if value not in ("true", "false"):
                    raise Exception('Copyable must be "true" or "false"')
                value = (value == "true")
                yield motor.Op(self.application.mongodb.worlds.update,
                               { '_id':wid },
                               { '$set':{'copyable':value} })
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

            if name == 'plistkey':
                value = sluggify(value)
                if not re_valididentifier.match(value):
                    raise Exception('Invalid key name')
                plistid = self.get_argument('plist', None)
                if not plistid:
                    raise Exception('No portlist declared')
                plistid = ObjectId(plistid)
                oplist = yield motor.Op(self.application.mongodb.portlists.find_one,
                                     { 'wid':wid, 'key':value, 'type':'world' })
                if oplist and oplist['_id'] != plistid:
                    raise Exception('A portlist with this key already exists.')
                yield motor.Op(self.application.mongodb.portlists.update,
                               { '_id':plistid, 'wid':wid },
                               { '$set':{'key':value} })
                self.write( { 'val':value } )
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

            ### And also instance properties?

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

class BuildExportWorldHandler(BuildBaseHandler):
    @tornado.gen.coroutine
    def get(self, wid):
        wid = ObjectId(wid)
        (world, locations) = yield self.find_build_world(wid)
        
        # The handling of this export stuff is a nuisance. I don't want
        # to load the entire world data set into memory. But the json
        # module isn't set up for yieldy output.
        #
        # Therefore, evil hackery! We make assumptions about the formatting
        # of json.dump output, and stick in stuff iteratively. This requires
        # care with commas, because the format of JSON is annoying.

        rootobj = collections.OrderedDict()
        rootobj['name'] =  world.get('name', '???')
        rootobj['wid'] = str(wid)
        
        if 'creator' in world:
            rootobj['creator_uid'] = str(world['creator'])
            player = yield motor.Op(self.application.mongodb.players.find_one,
                                    { '_id':world['creator'] },
                                    { 'name':1 })
            if player:
                rootobj['creator'] = player['name']
                
        if 'copyable' in world:
            rootobj['copyable'] = world['copyable']
        if 'instancing' in world:
            rootobj['instancing'] = world['instancing']

        rootdump = json.dumps(rootobj, indent=True, ensure_ascii=False)
        assert rootdump.endswith('\n}')
        rootdumphead, rootdumptail = rootdump[0:-2], rootdump[-2:]
        slugname = sluggify(rootobj['name'])
        
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.set_header("Content-Disposition", "attachment; filename=%s.json" % (slugname,))
        self.write(rootdumphead)
        
        encoder = JSONEncoderExtra(indent=True, sort_keys=True, ensure_ascii=False)

        #### portals and portlists

        worldprops = []
        cursor = self.application.mongodb.worldprop.find({'wid':wid, 'locid':None}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            worldprops.append(prop)
        # cursor autoclose

        if worldprops:
            worldprops.sort(key=lambda prop:prop['_id']) ### or other criterion?
            for prop in worldprops:
                del prop['_id']

            res = encoder.encode(worldprops)
            self.write(',\n "realmprops": ')
            self.write(res)

        playerprops = []
        cursor = self.application.mongodb.wplayerprop.find({'wid':wid, 'uid':None}, {'key':1, 'val':1})
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            playerprops.append(prop)
        # cursor autoclose

        if playerprops:
            playerprops.sort(key=lambda prop:prop['_id']) ### or other criterion?

            for prop in playerprops:
                del prop['_id']

            res = encoder.encode(playerprops)
            self.write(',\n "playerprops": ')
            self.write(res)

        self.write(',\n "locations": [\n')
        
        for ix, loc in enumerate(locations):
            locobj = collections.OrderedDict()
            locobj['key'] = loc['key']
            locobj['name'] = loc.get('name', '???')
            
            locdump = json.dumps(locobj, indent=True, ensure_ascii=False)
            assert locdump.endswith('\n}')
            locdumphead, locdumptail = locdump[0:-2], locdump[-2:]

            self.write(locdumphead)

            locprops = []
            cursor = self.application.mongodb.worldprop.find({'wid':wid, 'locid':loc['_id']}, {'key':1, 'val':1})
            while (yield cursor.fetch_next):
                prop = cursor.next_object()
                locprops.append(prop)
            # cursor autoclose

            if locprops:
                locprops.sort(key=lambda prop:prop['_id']) ### or other criterion?
                
                for prop in locprops:
                    del prop['_id']

                res = encoder.encode(locprops)
                self.write(',\n "props": ')
                self.write(res)
            
            self.write(locdumptail)
            if ix < len(locations)-1:
                self.write(',\n')
            else:
                self.write('\n')
            
        self.write(' ]')

        self.write(rootdumptail)
        self.write('\n')
        
