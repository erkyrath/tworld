
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

map    = dict([ (key,val) for (key,val) in defs ])
revmap = dict([ (val,key) for (key,val) in defs ])

def level_named(val):
    val = val.upper()
    return map[val]

def name_for_level(val):
    return revmap[val]

def level_name_list():
    ls = [ '"'+val.lower()+'"' for (val, dummy) in defs ]
    return ', '.join(ls)
