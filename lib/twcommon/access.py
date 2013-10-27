import tornado.gen

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

class RemoteAccessMap:
    """This represents the set of permissions that one world's code
    ("fromworld") has to another world's data ("world"). The two arguments
    must be world objects from the DB.

    (Between worlds of the same creator, we allow any access. Between
    worlds of different creators, the permissions are defined by entries
    in the propaccess table; see the loadentries method.)
    """

    def __init__(self, world, fromworld):
        self.wid = world['_id']
        self.fromwid = fromworld['_id']
        
        if world['creator'] == fromworld['creator']:
            self.allaccess = True
            self.keymap = None
        else:
            self.allaccess = False
            self.keymap = {}

    def __repr__(self):
        return '<RemoteAccessMap for %s from %s>' % (self.wid, self.fromwid)

    @tornado.gen.coroutine
    def loadentries(self, app):
        """Load the propaccess entries that are relevant to this map.
        (Yieldy, since we access the database.) If there are no entries,
        this immediately raises an exception.

        Only call this if self.allaccess is false.
        """
        if self.allaccess:
            raise Exception('You should not call the loadentries method when the creator matches!')
        
        cursor = app.mongodb.propaccess.find({'wid':self.wid, 'fromwid':self.fromwid},
                                             {'key':1, 'types':1})
        while (yield cursor.fetch_next):
            ent = cursor.next_object()
            self.keymap[ent['key']] = ent['types']
        # cursor autoclose
        
        if not self.keymap:
            raise Exception('Cannot access another creator\'s world without permission')
        return
