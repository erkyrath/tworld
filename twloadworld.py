#!/usr/bin/env python3

import sys
import os
import json
import datetime

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

import two.interp
from two.interp import sluggify

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
        self.locations = {}
        self.locationlist = []

    def check_symbols_used(self):
        self.symbolsused = set()
        all_interp_props = []
        for (key, propval) in self.props.items():
            if is_interp_text(propval):
                all_interp_props.append( (propval['text'], None) )
        for (lockey, loc) in self.locations.items():
            for (key, propval) in loc.props.items():
                if is_interp_text(propval):
                    all_interp_props.append( (propval['text'], lockey) )
            

        for (text, lockey) in all_interp_props:
            for nod in two.interp.parse(text):
                if isinstance(nod, two.interp.Link):
                    self.symbolsused.add( (nod.target, lockey) )
                if isinstance(nod, two.interp.Interpolate):
                    self.symbolsused.add( (nod.expr, lockey) )

        for (symbol, lockey) in self.symbolsused:
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
        isindent = False
        val = ln.lstrip()
        if len(val) < len(ln):
            ln = val
            isindent = True
            
        if not ln or ln.startswith('#'):
            continue

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
            if not curloc:
                if curprop not in world.proplist:
                    world.proplist.append(curprop)
                append_to_prop(world.props, curprop, ln)
            else:
                if curprop not in curloc.proplist:
                    curloc.proplist.append(curprop)
                append_to_prop(curloc.props, curprop, ln)
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
            elif key == '$instancing':
                world.instancing = val
                if val not in ('shared', 'solo', 'standard'):
                    error('$instancing value must be shared, solo, or standard')
            else:
                error('Unknown key: %s' % (key,))
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
        if not val:
            error('%s must be followed by a value' % (key,))
            return None
        if key == 'move':
            val = sluggify(val.strip())
            return {'type':'move', 'loc':val}
        elif key == 'focus':
            val = sluggify(val.strip())
            return {'type':'focus', 'key':val}
        elif key == 'event':
            return {'type':'event', 'text':val}
        elif key == 'text':
            return {'type':'text', 'text':val}
        elif key == 'code':
            return {'type':'code', 'text':val}
        else:
            error('Unknown special property type: *%s' % (key,))
            return None

    try:
        return json.loads(prop)
    except:
        pass
        
    return {'type':'text', 'text':prop}

def append_to_prop(dic, key, ln):
    val = dic.get(key, None)
    if not val:
        val = {'type':'text', 'text':ln}
        dic[key] = val
    elif type(val) is str:
        val += ('\n\n' + ln)
        dic[key] = val
    elif type(val) is dict and 'text' in val:
        # Covers {text}, {event}, {code}
        val['text'] += ('\n\n' + ln)
    else:
        error('Cannot append to property %s' % (key,))

def prop_to_string(val):
    if type(val) is not dict:
        return json.dumps(val)
    key = val.get('type', None)
    if key == 'move':
        return '*move %s' % (val['loc'],)
    if key == 'focus':
        return '*focus %s' % (val['key'],)
    if key == 'event':
        return '*event %s' % (val['text'],)
    if key == 'text':
        val = val['text']
        if '\n\n' in val:
            return val.replace('\n\n', '\n\t')
        return val
    if key == 'code':
        return '*code %s' % (val['text'],)
    return json.dumps(val)

def is_interp_text(res):
    ### events also?
    return (type(res) is dict and res.get('type', None) == 'text')

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
        args = ['.'] + world.locationlist
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

client = pymongo.MongoClient()
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
        'copyable': True,
        'instancing': world.instancing,
        }
    wid = db.worlds.insert(dbworld)
    dbworld = db.worlds.find_one({'_id':wid})
    if not dbworld:
        error('Unable to create world!')
        sys.exit(1)
    print('Created world "%s" (%s)' % (dbworld['name'], wid))

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
    args = ['.'] + world.locationlist
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
    
    loc = world.locations.get(lockey, None)
    if loc is None:
        error('Location not found: %s' % (lockey,))
        continue
    
    if not loc.locid:
        dbloc = db.locations.find_one({'wid':wid, 'key':lockey})
        if dbloc:
            loc.locid = dbloc['_id']
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
            print('Writing property in %s: %s' % (loc.key, key,))
            db.worldprop.update({'wid':wid, 'locid':loc.locid, 'key':key},
                                {'wid':wid, 'locid':loc.locid, 'key':key, 'val':val},
                                upsert=True)
    else:
        if key not in loc.props:
            error('Property not found in %s: %s' % (loc.key, key))
            continue
        val = loc.props[key]
        print('Writing property in %s: %s' % (loc.key, key,))
        db.worldprop.update({'wid':wid, 'locid':loc.locid, 'key':key},
                            {'wid':wid, 'locid':loc.locid, 'key':key, 'val':val},
                            upsert=True)
        
