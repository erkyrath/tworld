#!/usr/bin/env python3

### Stuff this into either tweb or tworld, or else use a common config file.

mongo_database = 'mydb'

initial_config = {
    'playerfields': {
        'desc': 'an ordinary explorer.',
        'pronoun': 'it',
        },
    }

import pymongo

client = pymongo.MongoClient()
db = client[mongo_database]

# Index for "config": key
db.config.create_index('key', unique=True)
# Create some config entries:
for (key, val) in initial_config.items():
    db.config.insert({'key':key, 'val':val})

# Index for "sessions": sid
db.sessions.create_index('sid', unique=True)

# Indexes for "players": email, name
db.players.create_index('email', unique=True)
db.players.create_index('name', unique=True)

### Create the admin player (no password)
