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
DBVERSION = 6

import sys
import os
import unicodedata
import binascii
import types
import logging
import datetime

import pymongo
from bson.objectid import ObjectId

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

tornado.options.define(
    'localize', type=str,
    help='pathname of localization data file')

tornado.options.define(
    'resetpw', type=str,
    help='reset the password for the given user (name or email address)')

# Parse 'em up.
tornado.options.parse_command_line()
opts = tornado.options.options

if opts.python_path:
    sys.path.insert(0, opts.python_path)

import twcommon.access
from twcommon.misc import sluggify


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

curversion = None
res = db.config.find_one({'key':'dbversion'})
if res:
    curversion = res['val']

def upgrade_to_v2():
    print('Upgrading to v2...')
    cursor = db.players.find({}, {'name':1})
    for player in cursor:
        namekey = sluggify(player['name'])
        db.players.update({'_id':player['_id']}, {'$set':{'namekey':namekey}})

def upgrade_to_v3():
    print('Upgrading to v3...')
    cursor = db.players.find({}, {'scid':1})
    for player in cursor:
        db.scopeaccess.update({'uid':player['_id'], 'scid':player['scid']},
                              {'uid':player['_id'], 'scid':player['scid'], 'level':twcommon.access.ACC_FOUNDER}, upsert=True)

def upgrade_to_v4():
    print('Upgrading to v4...')
    db.portals.remove({'inwid':{'$gt':ObjectId("000000000000000000000000")}})
    db.portals.drop_index('inwid_1')
    db.portals.drop_index('plistid_1')
    db.portals.update({}, {'$set':{'iid':None}}, multi=True)

def upgrade_to_v5():
    print('Upgrading to v5...')
    plists = {}
    cursor = db.portlists.find({'type':'world'})
    for plist in cursor:
        plists[plist['_id']] = plist
    print('...%d world portlists found' % (len(plists),))
    plistids = sorted(plists.keys())
    for (ix, plistid) in enumerate(plistids):
        plist = plists[plistid]
        key = 'pkey_%s' % (ix,)
        plist['key'] = key
        db.portlists.update({'_id':plistid}, {'$set':{'key':key}})
    props = []
    cursor = db.worldprop.find()
    for prop in cursor:
        val = prop['val']
        if type(val) is dict and val.get('type') == 'portlist':
            props.append(prop)
    print('...%d world portlist properties found' % (len(props),))
    for prop in props:
        val = prop['val']
        plist = plists.get(val['plistid'], None)
        if plist:
            val['plistkey'] = plist['key']
            if 'focusport' in val:
                val['focus'] = True
            db.worldprop.update({'_id':prop['_id']}, {'$set':{'val':val}})

def upgrade_to_v6():
    print('Upgrading to v6...')
    db.worlds.update({'createtime':None},
                     {'$set':{'createtime':datetime.datetime.now(datetime.timezone.utc),}},
                     multi=True)

# if curversion is None, we're brand-new.
if curversion is not None and curversion < DBVERSION:
    if not opts.upgradedb:
        print('Database schema (%d) is behind the current version (%d). Must use --upgradedb option!' % (curversion, DBVERSION,))
        sys.exit(1)
    if curversion < 2:
        upgrade_to_v2()
    if curversion < 3:
        upgrade_to_v3()
    if curversion < 4:
        upgrade_to_v4()
    if curversion < 5:
        upgrade_to_v5()
    if curversion < 6:
        upgrade_to_v6()
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
# Sparse index
db.players.create_index('guest', sparse=True)

# Compound index
db.playstate.create_index([('iid', pymongo.ASCENDING), ('locid', pymongo.ASCENDING)])

db.playprefs.create_index('uid')  # not unique
# Compound index
db.playprefs.create_index([('uid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

db.pwrecover.create_index('key', unique=True)

# Compound index
db.locations.create_index([('wid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.instances.create_index([('wid', pymongo.ASCENDING), ('scid', pymongo.ASCENDING)], unique=True)

# Compound index
db.worldprop.create_index([('wid', pymongo.ASCENDING), ('locid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.instanceprop.create_index([('iid', pymongo.ASCENDING), ('locid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.wplayerprop.create_index([('wid', pymongo.ASCENDING), ('uid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.iplayerprop.create_index([('iid', pymongo.ASCENDING), ('uid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

# Compound index
db.propaccess.create_index([('wid', pymongo.ASCENDING), ('fromwid', pymongo.ASCENDING), ('key', pymongo.ASCENDING)], unique=True)

db.trashprop.create_index('wid')
db.trashprop.create_index('changed')

# Compound index
db.portals.create_index([('plistid', pymongo.ASCENDING), ('iid', pymongo.ASCENDING)])

# Sparse index
# (I'd make a unique sparse compound (wid, key) index, if mongodb supported it)
db.portlists.create_index('wid', sparse=True)

# Compound index
db.scopeaccess.create_index([('uid', pymongo.ASCENDING), ('scid', pymongo.ASCENDING)], unique=True)

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

    db.scopeaccess.insert({'uid':adminuid, 'scid':scid, 'level':twcommon.access.ACC_FOUNDER})

    portlist = {
        'type': 'pers',
        'uid': adminuid,
        }
    
    plistid = db.portlists.insert(portlist)
    db.players.update({'_id':adminuid},
                      {'$set': {'plistid': plistid}})


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
    
# The localize entries.

default_localize_entries = """
# Here we define the default localization entries.
# + marks entries that the Javascript client (or tweb) needs to know about.

+misc.world: world
+misc.location: location
+misc.instance: instance
+misc.creator: creator

+client.tool.title.portals: Portals
+client.tool.title.this_portal: This Portal
+client.tool.title.insttool: This Instance
+client.tool.title.preferences: Preferences
+client.tool.title.eventlog: Logging

+client.tool.menu.return_to_start: Return to Start
+client.tool.menu.set_panic_portal: Set as Panic Portal
+client.tool.menu.delete_own_portal: Remove Portal from List
+client.tool.menu.enable_log: Log Event Pane
+client.tool.menu.select_log: Select Logged Text
+client.tool.menu.clear_log: Clear Log

+client.button.cancel: Cancel
+client.button.delete: Delete
+client.button.edit_collection: Edit Collection
+client.button.done_editing: Done Editing
+client.button.add_portal: Add Portal

+client.label.copy_portal: Copy this portal to your collection
+client.label.not_copyable: This portal cannot be copied
+client.label.only_solo: Only your personal instance is available
+client.label.only_shared: Only the global instance is available
+client.label.flexible: Travel instead to...
+client.label.back_to_plist: (Back to the collection)
+client.label.enter_portal: Enter the portal.
+client.label.plist_is_empty: The collection is empty.
+client.label.created_by: created by %s
+client.label.created_by_paren: (created by %s)
+client.label.select_portal_to_add: Select a portal from your list to add to this collection.

+client.eventpane.start: Click on the links above to explore. Type in this pane to chat with nearby players.

+label.in_transition: (In transition)
label.created_by: Created by %s
label.global_instance_paren: (Global instance)
label.personal_instance_you_paren: (Personal instance)
label.personal_instance_paren: (Personal: %s)
label.group_instance_paren: (Group: %s)

action.portout: The world fades away.
action.portin: You are somewhere new.
action.oportout: %s disappears.
action.oportin: %s appears.
action.oleave: %s leaves.
action.oarrive: %s arrives.

message.desc_own_portlist: You consult your portal collection.
message.instance_no_access: You do not have access to this instance.
message.panic_portal_set: Panic portal set to %s, %s.
+message.no_portaldesc: The destination is hazy.
message.copy_already_have: This portal is already in your collection.
message.copy_ok: You copy the portal to your collection.
message.delete_own_portal_ok: You remove the portal from your collection.
message.widget_no_access: You do not have permission to edit this.
message.plist_add_ok: You add your portal to this collection.
message.plist_add_already_have: This portal is already in this collection.
message.plist_delete_ok: You delete the portal from this collection.
message.plist_delete_not_instance: This portal is not deletable.

"""

def parse_localization(fl):
    res = []
    lang = None
    for ln in fl:
        ln = ln.strip()
        if not ln or ln.startswith('#'):
            continue
        if ln.startswith('*'):
            lang = ln[1:].strip()
            continue
        clientflag = False
        if ln.startswith('+'):
            clientflag = True
            ln = ln[1:].strip()
        key, dummy, val = ln.partition(':')
        if not dummy:
            continue
        key = key.strip()
        val = val.strip()
        res.append( (key, lang, clientflag, val) )
    return res

force_localize = False
if opts.localize:
    fl = open(opts.localize)
    locls = parse_localization(fl)
    fl.close()
    force_localize = True
else:
    locls = parse_localization(default_localize_entries.split('\n'))

loccount = 0
for (key, lang, client, val) in locls:
    obj = { 'key':key, 'lang':lang, 'val':val }
    if client:
        obj['client'] = True
    if not force_localize:
        res = db.localize.find_one({ 'key':key, 'lang':lang })
        if res:
            continue
    db.localize.update({ 'key':key, 'lang':lang },
                       obj, upsert=True)
    loccount += 1

if loccount:
    print('Updated %d localization entries' % (loccount,))
    
if opts.resetpw:
    if '@' in opts.resetpw:
        player = db.players.find_one({ 'email':opts.resetpw })
    else:
        player = db.players.find_one({ 'name':opts.resetpw })
        if not player:
            player = db.players.find_one({ 'namekey':opts.resetpw })
    if not player:
        raise Exception('No such player: ' + opts.resetpw)
    print('Enter password for %s (%s)' % (player['name'], player['email']))
    import getpass
    import hashlib
    
    newpw = getpass.getpass()
    newpw2 = getpass.getpass()
    if newpw != newpw2:
        raise Exception('Passwords do not match')

    password = unicodedata.normalize('NFKC', newpw)
    password = password.encode()  # to UTF8 bytes
    pwsalt = binascii.hexlify(os.urandom(8))
    saltedpw = pwsalt + b':' + password
    cryptpw = hashlib.sha1(saltedpw).hexdigest().encode()
    
    db.players.update({'_id':player['_id']},
                      {'$set':{'pwsalt': pwsalt, 'password': cryptpw}})
    print('Password set.')
    
