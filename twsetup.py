#!/usr/bin/env python3

import sys
import os
import binascii
import types
import logging
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
    'mongo_database', type=str, default='tworld',
    help='name of mongodb database')

tornado.options.define(
    'admin_email', type=str,
    help='email address of server admin')

# Parse 'em up.
tornado.options.parse_command_line()
opts = tornado.options.options


client = pymongo.MongoClient()
db = client[opts.mongo_database]

initial_config = {
    'playerfields': {
        'desc': 'an ordinary explorer.',
        'pronoun': 'it',
        },
    'startworldloc': 'start',
    }

# All the indexes we need. (Except _id, which comes free.)

db.config.create_index('key', unique=True)

db.sessions.create_index('sid', unique=True)

db.players.create_index('email', unique=True)
db.players.create_index('name', unique=True)

# Compound index
db.playstate.create_index([('iid', pymongo.ASCENDING), ('locid', pymongo.ASCENDING)])

db.playprefs.create_index('uid')  # not unique
# Compound index
db.playprefs.create_index([('uid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.locations.create_index([('wid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.instances.create_index([('wid', pymongo.ASCENDING), ('scid', pymongo.ASCENDING)], unique=True)

# Compound index
db.worldprop.create_index([('wid', pymongo.ASCENDING), ('locid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.instanceprop.create_index([('iid', pymongo.ASCENDING), ('locid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)


# Create some config entries if they don't exist, but leave them alone
# if they do exist.

for (key, val) in initial_config.items():
    oldval = db.config.find_one({'key':key})
    if oldval is None:
        db.config.insert({'key':key, 'val':val})


# The global scope.

globalscope = db.scopes.find_one({'type':'glob'})
if not globalscope:
    globalscopeid = db.scopes.insert({'type':'glob'})
    db.config.update({'key':'globalscopeid'},
                     {'key':'globalscopeid', 'val':globalscopeid}, upsert=True)


# The admin player, and associated state.

adminplayer = db.players.find_one({'admin':True})
if adminplayer:
    adminuid = adminplayer['_id']
else:
    print('No admin player exists; creating.')

    if not opts.admin_email:
        raise Exception('You must define admin_email in the config file!')
    adminplayer = {
        'name': 'Admin',
        'admin': True,
        'email': opts.admin_email,
        'pwsalt': binascii.hexlify(os.urandom(8)),
        'password': b'x',   # cannot use this password until changed
        'createtime': datetime.datetime.now(),
        }

    adminplayer.update(initial_config['playerfields'])

    adminuid = db.players.insert(adminplayer)
    
    playstate = {
        '_id': adminuid,
        'iid': None,
        'locid': None,
        'focus': None,
        }
    db.playstate.insert(playstate)

    scope = {
        'type': 'pers',
        'uid': adminuid,
        }
    
    scid = db.scopes.insert(scope)
    db.players.update({'_id':adminuid},
                      {'$set': {'scid': scid}})


# The starting world (solo).

world = db.worlds.find_one()
if not world:
    print('No world exists; creating start world.')

    world = {
        'creator': adminuid,
        'name': 'Beginning',
        'copyable': True,
        'instancing': 'solo',
        }
    
    worldid = db.worlds.insert(world)
    db.config.update({'key':'startworldid'},
                     {'key':'startworldid', 'val':worldid}, upsert=True)
    
    startloc = {
        'wid': worldid,
        'key': initial_config['startworldloc'],
        'name': 'The Start',
        }
    startlocid = db.locations.insert(startloc)

    desc = {
        'wid': worldid,
        'locid': startlocid,
        'key': 'desc',
        'val': 'You are at the start.',
        }
    db.worldprop.insert(desc)
    
