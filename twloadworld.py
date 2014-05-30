#!/usr/bin/env python3

"""
twloadworld: Copyright (c) 2013, Andrew Plotkin
(Available under the MIT License; see LICENSE file.)

This script reads a world definition file and pushes it into the database.
This is an administrator tool; it does no permission checking and can
modify or overwrite any world.

I built this as a temporary measure, awaiting a full-fledged world-creation
interface. However, I suspect it will remain useful for various cases
(wiping and rebuilding a Tworld database, etc).
"""

import sys
import os
import datetime
import ast
import keyword

import bson
from bson.objectid import ObjectId
import pymongo

import tornado.options

# Set up all the options. (Generally found in the config file.)

# Clever hack to parse a config file off the command line.
tornado.options.define(
    'config', type=str,
    help='configuration file',
    callback=lambda path: tornado.options.parse_config_file(path, final=False))

tornado.options.define(
    'python_path', type=str,
    help='Python modules directory (optional)')

tornado.options.define(
    'mongo_database', type=str, default='tworld',
    help='name of mongodb database')

###
#tornado.options.define(
#    'removeworld', type=bool,
#    help='remove world completely')

tornado.options.define(
    'remove', type=bool,
    help='only remove the named room or room.prop')

tornado.options.define(
    'display', type=bool,
    help='only display the named room or room.prop')

tornado.options.define(
    'check', type=bool,
    help='only check consistency of the file')

# Parse 'em up.
args = tornado.options.parse_command_line()
opts = tornado.options.options

# But tornado options don't support options after arguments. Hack to work
# around this.
if '--check' in args:
    args.remove('--check')
    opts.check = True
if '--display' in args:
    args.remove('--display')
    opts.display = True
if '--remove' in args:
    args.remove('--remove')
    opts.remove = True
if '--removeworld' in args:
    args.remove('--removeworld')
    opts.removeworld = True

if opts.python_path:
    sys.path.insert(0, opts.python_path)

import twcommon.access
import twcommon.interp
from twcommon.misc import sluggify

if not args:
    print('usage: twloadworld.py worldfile [ room ... or room.prop ... ]')
    sys.exit(-1)

class World(object):
    
    def __init__(self):
        self.creator = 'Admin'
        self.wid = None
        self.name = None
        self.copyable = True
        self.instancing = 'standard'
        self.props = {}
        self.proplist = []
        self.playerprops = {}
        self.playerproplist = []
        self.locations = {}
        self.locationlist = []
        self.portals = {}

    def check_symbols_used(self):
        self.symbolsused = set()
        all_interptext_props = []
        all_code_props = []
        for (key, propval) in self.props.items():
            if keyword.iskeyword(key):
                print('Warning: prop "%s" in %s is a keyword' % (key, None))
            if is_interp_text(propval):
                all_interptext_props.append( (propval['text'], None) )
            if is_code(propval):
                all_code_props.append( (key, propval['text'], None) )
            if is_move(propval):
                if propval['loc'] not in self.locations:
                    print('Warning: move prop "%s" in %s goes to undefined loc: %s' % (key, None, propval['loc']))
        for (lockey, loc) in self.locations.items():
            for (key, propval) in loc.props.items():
                if keyword.iskeyword(key):
                    print('Warning: prop "%s" in %s is a keyword' % (key, lockey))
                if is_interp_text(propval):
                    all_interptext_props.append( (propval['text'], lockey) )
                if is_code(propval):
                    all_code_props.append( (key, propval['text'], lockey) )
                if is_move(propval):
                    if propval['loc'] not in self.locations:
                        print('Warning: move prop "%s" in %s goes to undefined loc: %s' %(key, lockey, propval['loc']))
            
        for (key, text, lockey) in all_code_props:
            try:
                ast.parse(text, filename='%s.%s' % (lockey, key,))
            except Exception as ex:
                print('Warning: code prop "%s" in %s does not parse: %s' % (key, lockey, ex))

        for (text, lockey) in all_interptext_props:
            for nod in twcommon.interp.parse(text):
                if isinstance(nod, twcommon.interp.Link):
                    self.symbolsused.add( (nod.target, lockey) )
                if isinstance(nod, twcommon.interp.Interpolate):
                    self.symbolsused.add( (nod.expr, lockey) )

        for (symbol, lockey) in self.symbolsused:
            if not symbol.isidentifier():
                try:
                    ast.parse(symbol)
                except:
                    print('Warning: code snippet "%s" in %s does not parse.' % (symbol, lockey,))                    
                continue
            if lockey is None:
                loc = None
            else:
                loc = self.locations[lockey]
            if loc and symbol in loc.props:
                continue
            if symbol in self.props:
                continue
            print('Warning: symbol "%s" in %s is not defined.' % (symbol, lockey,))

class Location(object):
    def __init__(self, name, key=None):
        self.name = name
        if key is None:
            self.key = sluggify(name)
        else:
            self.key = key
        self.locid = None
        self.props = {}
        self.proplist = []
    def __repr__(self):
        return '<Location %s: "%s">' % (self.key, self.name)

def parse_world(filename):
    world = World()
    curloc = None
    curprop = None
    
    fl = open(filename)
    while True:
        ln = fl.readline()
        if not ln:
            break
        ln = ln.rstrip()
        isindent = 0
        val = ln.lstrip()
        if len(val) < len(ln):
            isindent = len(ln) - len(val)
            ln = val
            
        if not ln or ln.startswith('#'):
            continue
        if ln.startswith('***'):
            break

        if ln.startswith('*'):
            # New location.
            curprop = None
            lockey, dummy, locname = ln[1:].partition(':')
            lockey = lockey.strip()
            locname = locname.strip()
            if not locname:
                locname = lockey
                lockey = sluggify(locname)
            if lockey in world.locations:
                error('Location defined twice: %s' % (lockey,))
            curloc = Location(locname, lockey)
            world.locations[lockey] = curloc
            world.locationlist.append(lockey)
            curprop = 'desc'
            continue

        if isindent and curprop is not None:
            ### Fails to handle extending player props
            if not curloc:
                if curprop not in world.proplist:
                    world.proplist.append(curprop)
                append_to_prop(world.props, curprop, ln, indent=isindent)
            else:
                if curprop not in curloc.proplist:
                    curloc.proplist.append(curprop)
                append_to_prop(curloc.props, curprop, ln, indent=isindent)
            continue

        key, dummy, val = ln.partition(':')
        if not dummy:
            error('Line does not define a property: %s' % (ln[:36],))
            continue

        key = key.strip()
        val = val.strip()

        if not curloc and key.startswith('$'):
            curprop = None
            if key == '$wid':
                world.wid = val
            elif key == '$name':
                world.name = val
            elif key == '$creator':
                world.creator = val
            elif key == '$copyable':
                world.copyable = not (val.lower()[0] in ['0', 'n', 'f'])
            elif key == '$instancing':
                world.instancing = val
                if val not in ('shared', 'solo', 'standard'):
                    error('$instancing value must be shared, solo, or standard')
            elif key.startswith('$player.'):
                key = key[8:].strip()
                propval = parse_prop(val)
                if key in world.playerprops:
                    error('Player key defined twice: %s' % (key,))
                world.playerprops[key] = propval
                world.playerproplist.append(key)
                curprop = key
                continue
            else:
                error('Unknown $key: %s' % (key,))
            continue
        
        if not key.isidentifier():
            error('Property key is not valid: %s' % (key,))

        propval = parse_prop(val)
            
        if not curloc:
            if key in world.props:
                error('World key defined twice: %s' % (key,))
            world.props[key] = propval
            world.proplist.append(key)
            curprop = key
        else:
            if key in curloc.props:
                error('Location key defined twice in %s: %s' % (curloc.key, key,))
            curloc.props[key] = propval
            curloc.proplist.append(key)
            curprop = key
            
    fl.close()
    world.check_symbols_used()
    return world

def parse_prop(prop):
    if prop.startswith('*'):
        key, dummy, val = prop[1:].partition(' ')
        
        if not val and key not in ('code', 'gentext'):
            error('%s must be followed by a value' % (key,))
            return None
        
        if key == 'portlist':
            plistkey, dummy, val = val.partition(' ')
            res = {'type':'portlist', 'plistkey':plistkey,
                   '_templist':[]}
            if 'single' in val.split():
                res['focus'] = True
            return res
        
        if key == 'move':
            val = sluggify(val.strip())
            return {'type':'move', 'loc':val}
        elif key == 'focus':
            val = sluggify(val.strip())
            return {'type':'focus', 'key':val}
        elif key == 'event':
            return {'type':'event', 'text':val}
        elif key == 'panic':
            return {'type':'panic', 'text':val} # theoretically the text is optional
        elif key == 'text':
            return {'type':'text', 'text':val}
        elif key == 'gentext':
            return {'type':'gentext', 'text':val}
        elif key == 'code':
            return {'type':'code', 'text':val}
        elif key == 'selfdesc':
            return {'type':'selfdesc', 'text':val}
        elif key == 'editstr':
            return {'type':'editstr', 'key':val}
        elif key == 'datetime':
            val = datetime.datetime.strptime(val, '%Y-%m-%d')
            return datetime.datetime(year=val.year, month=val.month, day=val.day, tzinfo=datetime.timezone.utc)
        else:
            error('Unknown special property type: *%s' % (key,))
            return None

    try:
        propval = ast.literal_eval(prop)
        # We test-encode the new value to bson, so that we can be strict
        # and catch errors.
        dummy = bson.BSON.encode({'val':propval}, check_keys=True)
        return propval
    except:
        pass
        
    return {'type':'text', 'text':prop}

def append_to_prop(dic, key, ln, indent=0):
    val = dic.get(key, None)
    if not val:
        val = {'type':'text', 'text':ln}
        dic[key] = val
    elif type(val) is str:
        val += ('\n\n' + ln)
        dic[key] = val
    elif type(val) is dict and ln.startswith('-'):
        subkey, dummy, subval = ln[1:].partition(':')
        if not dummy:
            error('Continuation *line must contain a colon')
            return
        subkey = subkey.strip()
        subval = subval.strip()
        if val.get('type', None) == 'portlist' and subkey == 'portal':
            subls = [ s2val.strip() for s2val in subval.split(',') ]
            if len(subls) != 4:
                error('Portal property must have four fields')
                return None
            val['_templist'].append(subls)
        else:
            val[subkey] = subval
    elif type(val) is dict and val.get('type', None) in ('code', 'gentext'):
        if '_baseindent' not in val:
            val['_baseindent'] = indent
        indentstr = '  ' * (indent - val['_baseindent'])
        if not val['text'].strip():
            val['text'] = ''
        else:
            indentstr = '\n' + indentstr
        val['text'] += (indentstr + ln)
    elif type(val) is dict and 'text' in val:
        # Covers {text}, {event}
        val['text'] += ('\n\n' + ln)
    else:
        error('Cannot append to property %s' % (key,))

def transform_prop(world, db, val):
    if type(val) is not dict:
        return val
    key = val.get('type', None)

    if key == 'editstr':
        if 'editaccess' in val:
            val['editaccess'] = twcommon.access.level_named(val['editaccess'])
    
    if key == 'portlist':
        if val['plistkey'] in world.portlistmap:
            plistid = world.portlistmap[val['plistkey']]['_id']
        else:
            plistid = db.portlists.insert({'type':'world', 'wid':world.wid, 'key':val['plistkey']})
            print('Created portlist %s (%s)' % (val['plistkey'], plistid,))
        # Clean out the portlist and rebuild it
        db.portals.remove({'plistid':plistid, 'iid':None})
        listpos = 0.0
        portid = None
        for quad in val['_templist']:
            tocreator = db.players.find_one({'name':quad[1]})
            if not tocreator:
                error('Creator not found for portal: %s, %s' % (quad[0], quad[1]))
                return '[Portal world creator not found]'
            toworld = db.worlds.find_one({'name':quad[0], 'creator':tocreator['_id']})
            if not toworld:
                error('World not found for portal: %s' % (quad[0],))
                return '[Portal world not found]'
            toloc = db.locations.find_one({'wid':toworld['_id'], 'key':quad[3]})
            if not toloc:
                error('Location not found for portal: %s, %s' % (quad[0], quad[3]))
                return '[Portal location not found]'
            query = { 'plistid':plistid, 'iid':None, 'wid':toworld['_id'], 'locid':toloc['_id'] }
            if quad[2] in ('personal', 'global', 'same'):
                query['scid'] = quad[2]
            else:
                query['scid'] = ObjectId(quad[2])
            query['listpos'] = listpos
            listpos += 1.0
            portid = db.portals.insert(query)
            print('Created portal %s (%s)' % (quad, portid,))
        newval = { 'type':'portlist', 'plistkey':val['plistkey'] }
        if 'text' in val:
            newval['text'] = val['text']
        if 'focus' in val:
            newval['focus'] = True
        if 'editaccess' in val:
            newval['editaccess'] = twcommon.access.level_named(val['editaccess'])
        if 'readaccess' in val:
            newval['readaccess'] = twcommon.access.level_named(val['readaccess'])
        return newval
            
    
    return val
        
def prop_to_string(val):
    if type(val) is not dict:
        return repr(val)
    key = val.get('type', None)
    if key == 'move':
        return '*move %s' % (val['loc'],)
    if key == 'focus':
        return '*focus %s' % (val['key'],)
    if key == 'event':
        res = '*event %s' % (val['text'],)
        if 'otext' in val:
            res += ('\n\t- otext: ' + val['otext'])
        return res
    if key == 'panic':
        res = '*panic %s' % (val['text'],)
        if 'otext' in val:
            res += ('\n\t- otext: ' + val['otext'])
        return res
    if key == 'selfdesc':
        res = '*selfdesc %s' % (val['text'],)
        return res
    if key == 'text':
        val = val['text']
        if '\n\n' in val:
            return val.replace('\n\n', '\n\t')
        return val
    if key == 'gentext':
        val = val['text']
        if '\n' not in text:
            return '*gentext %s' % (text,)
        else:
            ls = [ '  '+val for val in text.split('\n') ]
            text = '\n'.join(ls)
            return '*gentext\n%s' % (text,)
    if key == 'code':
        text = val['text']
        if '\n' not in text:
            return '*code %s' % (text,)
        else:
            ls = [ '  '+val for val in text.split('\n') ]
            text = '\n'.join(ls)
            return '*code\n%s' % (text,)
    return repr(val)

def is_interp_text(res):
    ### events also?
    return (type(res) is dict and res.get('type', None) == 'text')

def is_code(res):
    return (type(res) is dict and res.get('type', None) == 'code')

def is_move(res):
    return (type(res) is dict and res.get('type', None) == 'move')

errorcount = 0

def error(msg):
    global errorcount
    errorcount = errorcount + 1
    print('Error: %s' % (msg,))

filename = args.pop(0)

world = parse_world(filename)

if errorcount:
    print('%d errors; stopping here.' % (errorcount,))
    sys.exit(1)

if opts.display:
    if not args:
        args = ['.', '$player'] + world.locationlist
    for val in args:
        if '.' in val:
            lockey, dummy, key = val.partition('.')
        else:
            lockey, key = (val, None)
        if not key:
            key = None

        if not lockey:
            print('* (world properties)')
            print()
            if key is None:
                for key in world.proplist:
                    print('%s: %s' % (key, prop_to_string(world.props[key])))
                    print()
            else:
                if key not in world.props:
                    error('Property not found in %s: %s' % ('*', key))
                    continue
                print('%s: %s' % (key, prop_to_string(world.props[key])))
                print()
            continue

        if lockey == '$player':
            print('* (player properties)')
            print()
            if key is None:
                for key in world.playerproplist:
                    print('%s: %s' % (key, prop_to_string(world.playerprops[key])))
                    print()
            else:
                if key not in world.playerprops:
                    error('Property not found in %s: %s' % ('$player', key))
                    continue
                print('%s: %s' % (key, prop_to_string(world.playerprops[key])))
                print()
            continue            
            
        loc = world.locations.get(lockey, None)
        if loc is None:
            error('Location not found: %s' % (lockey,))
            continue
        
        print('* %s: %s' % (loc.key, loc.name))
        print()
        if key is None:
            for key in loc.proplist:
                print('%s: %s' % (key, prop_to_string(loc.props[key])))
                print()
        else:
            if key not in loc.props:
                error('Property not found in %s: %s' % (loc.key, key))
                continue
            print('%s: %s' % (key, prop_to_string(loc.props[key])))
            print()

if opts.display or opts.check:
    sys.exit(0)

client = pymongo.MongoClient(tz_aware=True)
db = client[opts.mongo_database]

dbcreator = db.players.find_one({'name':world.creator})
if not dbcreator:
    error('Creator %s not found in database.' % (world.creator,))

world.creatoruid = dbcreator['_id']

if not world.wid:
    # Look for a world with this name. If not found, create it. If found,
    # use it (if the creator matches)
    dbworld = db.worlds.find_one({'name':world.name})
    if dbworld and dbworld.get('creator') != world.creatoruid:
        error('Found world "%s", but it was not created by %s.' % (world.name, world.creator))
        sys.exit(1)
else:
    # If the world with this wid does not exist, we'll have to create it.
    dbworld = db.worlds.find_one({'_id':ObjectId(world.wid)})

if dbworld:
    wid = dbworld['_id']
    print('Found world "%s" (%s)' % (dbworld['name'], wid))
else:
    dbworld = {
        'creator': world.creatoruid,
        'name': world.name,
        'copyable': world.copyable,
        'instancing': world.instancing,
        }
    wid = db.worlds.insert(dbworld)
    dbworld = db.worlds.find_one({'_id':wid})
    if not dbworld:
        error('Unable to create world!')
        sys.exit(1)
    print('Created world "%s" (%s)' % (dbworld['name'], wid))

world.wid = wid

# Check for existing portlists
world.allportlists = list(db.portlists.find({'type':'world', 'wid':world.wid}))
world.allportlists.sort(key = lambda x:x['_id'])
world.portlistmap = { val['key']:val for val in world.allportlists }

if opts.remove:
    if not args:
        error('Use --removeworld to remove the entire world.')
        sys.exit(1)
    for val in args:
        if '.' in val:
            lockey, dummy, key = val.partition('.')
        else:
            lockey, key = (val, None)
        if not key:
            key = None

        if not lockey:
            if key is None:
                db.worldprop.remove({'wid':wid, 'locid':None})
                print('removing all world properties')
            else:
                db.worldprop.remove({'wid':wid, 'locid':None, 'key':key})
                print('removing world property: %s' % (key,))
            continue
            
        if lockey == '$player':
            if key is None:
                db.wplayerprop.remove({'wid':wid})
                print('removing all player properties')
            else:
                db.wplayerprop.remove({'wid':wid, 'key':key})
                print('removing player property: %s' % (key,))
            continue
            
        loc = world.locations.get(lockey, None)
        if loc is None:
            error('Location not found: %s' % (lockey,))
            continue
        
        if not loc.locid:
            dbloc = db.locations.find_one({'wid':wid, 'key':lockey})
            if dbloc:
                loc.locid = dbloc['_id']
            else:
                error('Location does not exist in database: %s' % (lockey,))
                continue
            
        if key is None:
            db.worldprop.remove({'wid':wid, 'locid':loc.locid})
            print('removing all properties in %s' % (lockey,))
        else:
            db.worldprop.remove({'wid':wid, 'locid':loc.locid, 'key':key})
            print('removing property in %s: %s' % (lockey, key,))

    sys.exit(0)

# The adding-stuff-to-the-database case.
if not args:
    args = ['.', '$player'] + world.locationlist
for val in args:
    if '.' in val:
        lockey, dummy, key = val.partition('.')
    else:
        lockey, key = (val, None)
    if not key:
        key = None

    if not lockey:
        # World properties
        if key is None:
            # All world properties
            for key in world.props:
                val = world.props[key]
                print('Writing world property: %s' % (key,))
                db.worldprop.update({'wid':wid, 'locid':None, 'key':key},
                                    {'wid':wid, 'locid':None, 'key':key, 'val':val},
                                    upsert=True)
        else:
            if key not in world.props:
                error('Property not found in %s: %s' % ('*', key))
                continue
            val = world.props[key]
            print('Writing world property: %s' % (key,))
            db.worldprop.update({'wid':wid, 'locid':None, 'key':key},
                                {'wid':wid, 'locid':None, 'key':key, 'val':val},
                                upsert=True)
        continue
    
    if lockey == '$player':
        # Player properties
        if key is None:
            # All player properties
            for key in world.playerprops:
                val = world.playerprops[key]
                print('Writing player property: %s' % (key,))
                db.wplayerprop.update({'wid':wid, 'uid':None, 'key':key},
                                    {'wid':wid, 'uid':None, 'key':key, 'val':val},
                                    upsert=True)
        else:
            if key not in world.playerprops:
                error('Property not found in %s: %s' % ('$player', key))
                continue
            val = world.playerprops[key]
            print('Writing player property: %s' % (key,))
            db.wplayerprop.update({'wid':wid, 'uid':None, 'key':key},
                                {'wid':wid, 'uid':None, 'key':key, 'val':val},
                                upsert=True)
        continue
    
    loc = world.locations.get(lockey, None)
    if loc is None:
        error('Location not found: %s' % (lockey,))
        continue
    
    if not loc.locid:
        dbloc = db.locations.find_one({'wid':wid, 'key':lockey})
        if dbloc:
            loc.locid = dbloc['_id']
            if dbloc.get('name', None) != loc.name:
                print('Updating location name: %s' % (loc.key,))
                db.locations.update({'_id':loc.locid}, {'$set':{'name':loc.name}})
        else:
            print('Creating location: %s' % (loc.key,))
            dbloc = {
                'wid': wid,
                'key': loc.key,
                'name': loc.name,
                }
            loc.locid = db.locations.insert(dbloc)
            
    if key is None:
        for key in loc.props:
            val = loc.props[key]
            val = transform_prop(world, db, val)
            print('Writing property in %s: %s' % (loc.key, key,))
            db.worldprop.update({'wid':wid, 'locid':loc.locid, 'key':key},
                                {'wid':wid, 'locid':loc.locid, 'key':key, 'val':val},
                                upsert=True)
    else:
        if key not in loc.props:
            error('Property not found in %s: %s' % (loc.key, key))
            continue
        val = loc.props[key]
        val = transform_prop(world, db, val)
        print('Writing property in %s: %s' % (loc.key, key,))
        db.worldprop.update({'wid':wid, 'locid':loc.locid, 'key':key},
                            {'wid':wid, 'locid':loc.locid, 'key':key, 'val':val},
                            upsert=True)
        
