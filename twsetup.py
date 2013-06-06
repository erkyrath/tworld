#!/usr/bin/env python3

"""
twsetup: Copyright (c) 2013, Andrew Plotkin
(Available under the MIT License; see LICENSE file.)

This script sets up the Mongo database with the bare minimum of data
needed to run Tworld. You will typically run this exactly once when
setting up your server.

For development purposes, this is also able to upgrade an earlier database
schema to the current version. Use the --upgradedb option in this case.
"""

# The database version created by this version of the script.
DBVERSION = 2

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
    'python_path', type=str,
    help='Python modules directory (optional)')

tornado.options.define(
    'mongo_database', type=str, default='tworld',
    help='name of mongodb database')

tornado.options.define(
    'admin_email', type=str,
    help='email address of server admin')

tornado.options.define(
    'upgradedb', type=bool,
    help='upgrade an old database to the current schema')

# Parse 'em up.
tornado.options.parse_command_line()
opts = tornado.options.options

if opts.python_path:
    sys.path.insert(0, opts.python_path)

from two.interp import sluggify


# Open the client connection.

client = pymongo.MongoClient(tz_aware=True)
db = client[opts.mongo_database]

initial_config = {
    'dbversion': DBVERSION,
    'playerfields': {
        'desc': 'an ordinary explorer.',
        'pronoun': 'it',
        },
    'startworldloc': 'start',
    'firstportal': None,
    }

curversion = 0
res = db.config.find_one({'key':'dbversion'})
if res:
    curversion = res['val']

def upgrade_to_v2():
    print('Upgrading to v2...')
    cursor = db.players.find({}, {'name':1})
    for player in cursor:
        namekey = sluggify(player['name'])
        db.players.update({'_id':player['_id']}, {'$set':{'namekey':namekey}})
    
if curversion < DBVERSION:
    if not opts.upgradedb:
        print('Database schema (%d) is behind the current version (%d). Must use --upgradedb option!' % (curversion, DBVERSION,))
        sys.exit(1)
    if curversion < 2:
        upgrade_to_v2()
    db.config.update({'key':'dbversion'},
                     {'key':'dbversion', 'val':DBVERSION}, upsert=True)
else:
    if opts.upgradedb:
        print('Upgrade is not required.')

# All the indexes we need. (Except _id, which comes free.)

db.config.create_index('key', unique=True)

db.sessions.create_index('sid', unique=True)

db.players.create_index('email', unique=True)
db.players.create_index('name', unique=True)
db.players.create_index('namekey')

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

# Sparse indexes
db.portals.create_index('inwid', sparse=True)
db.portals.create_index('plistid', sparse=True)

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
        'namekey': sluggify('Admin'),
        'admin': True,
        'email': opts.admin_email,
        'pwsalt': binascii.hexlify(os.urandom(8)),
        'password': b'x',   # cannot use this password until changed
        'createtime': datetime.datetime.now(datetime.timezone.utc),
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
    
