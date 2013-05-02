#!/usr/bin/env python3

### Stuff this into either tweb or tworld, or else use a common config file.

import pymongo

client = pymongo.MongoClient()

# Index for "sessions": sid
client.mydb.sessions.create_index('sid', unique=True)

# Indexes for "players": email, name
client.mydb.players.create_index('email', unique=True)
client.mydb.players.create_index('name', unique=True)
