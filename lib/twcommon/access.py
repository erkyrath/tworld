
ACC_BANNED  = 0
ACC_VISITOR = 1
ACC_MEMBER  = 2
ACC_OWNER   = 3
ACC_FOUNDER = 4

defs = [
    ('BANNED',  ACC_BANNED),
    ('VISITOR', ACC_VISITOR),
    ('MEMBER',  ACC_MEMBER),
    ('OWNER',   ACC_OWNER),
    ('FOUNDER', ACC_FOUNDER),
    ]

map    = { key:val for (key,val) in defs }
revmap = { val:key for (key,val) in defs }

def level_named(val):
    """Return the access level constant (int) with a given name. The name
    is case-insensitive. If the name is not found, raises KeyError.
    """
    val = val.upper()
    return map[val]

def name_for_level(val):
    """Return the name (upper-case string) for a given access level.
    """
    return revmap[val]

def level_name_list():
    """Return the list of access level names as a string:
        '"banned", "visitor", "member", "owner", "founder"'
    """
    ls = [ '"'+val.lower()+'"' for (val, dummy) in defs ]
    return ', '.join(ls)
