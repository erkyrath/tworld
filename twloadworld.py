#!/usr/bin/env python3

import sys
import os
import json
import datetime

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

tornado.options.define(
    'removeworld', type=bool,
    help='remove world completely')

tornado.options.define(
    'remove', type=bool,
    help='remove the named room or room.prop')

tornado.options.define(
    'display', type=bool,
    help='remove the named room or room.prop')

# Parse 'em up.
args = tornado.options.parse_command_line()
opts = tornado.options.options

if opts.python_path:
    sys.path.insert(0, opts.python_path)

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
        self.locations = {}

class Location(object):
    def __init__(self, name, key=None):
        self.name = name
        if key is None:
            self.key = sluggify(name)
        else:
            self.key = key
        self.props = {}
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
            curprop = 'desc'
            continue

        if isindent and curprop is not None:
            if not curloc:
                append_to_prop(world.props, curprop, ln)
            else:
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
            curprop = key
        else:
            if key in curloc.props:
                error('Location key defined twice in %s: %s' % (curloc.key, key,))
            curloc.props[key] = propval
            curprop = key
            
    fl.close()
    return world

def parse_prop(prop):
    if prop.startswith('*'):
        key, dummy, val = prop[1:].partition(' ')
        if not val:
            error('%s must be followed by a value' % (key,))
            return None
        val = sluggify(val.strip())
        if key == 'move':
            return {'type':'move', 'loc':val}
        elif key == 'focus':
            return {'type':'focus', 'key':val}
        elif key == 'event':
            return {'type':'event', 'text':val}
        elif key == 'text':
            return {'type':'text', 'text':val}
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
        val['text'] += ('\n\n' + ln)
    else:
        error('Cannot append to property %s' % (key,))

errorcount = 0

def error(msg):
    global errorcount
    errorcount = errorcount + 1
    print('Error: %s' % (msg,))

filename = args.pop(0)

world = parse_world(filename)

if errorcount:
    print('%d errors; not writing to database.' % (errorcount,))
    sys.exit(1)

#client = pymongo.MongoClient()
#db = client[opts.mongo_database]



