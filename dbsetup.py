#!/usr/bin/env python3

### Stuff this into either tweb or tworld, or else use a common config file.

mongo_database = 'mydb'

import pymongo

client = pymongo.MongoClient()
db = client[mongo_database]

# Index for "sessions": sid
db.sessions.create_index('sid', unique=True)

# Indexes for "players": email, name
db.players.create_index('email', unique=True)
db.players.create_index('name', unique=True)
