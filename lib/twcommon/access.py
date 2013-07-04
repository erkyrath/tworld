
ACC_BANNED  = 0
ACC_VISITOR = 1
ACC_MEMBER  = 2
ACC_OWNER   = 3
ACC_CREATOR = 4

map = {
    'BANNED':  ACC_BANNED,
    'VISITOR': ACC_VISITOR,
    'MEMBER':  ACC_MEMBER,
    'OWNER':   ACC_OWNER,
    'CREATOR': ACC_CREATOR,
    }

def level_named(val):
    val = val.upper()
    return map[val]
