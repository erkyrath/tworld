
ACC_BANNED  = 0
ACC_VISITOR = 1
ACC_MEMBER  = 2
ACC_OWNER   = 3
ACC_CREATOR = 4

map = {
    'banned':  ACC_BANNED,
    'visitor': ACC_VISITOR,
    'member':  ACC_MEMBER,
    'owner':   ACC_OWNER,
    'creator': ACC_CREATOR,
    }

def level_named(val):
    val = val.lower()
    return map[val]
