import datetime
from bson.objectid import ObjectId
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

    # Maps type(val) references to their standard names. This skips
    # dict and dict types; those are handled separately.
    typenamemap = {
        type(None): 'none',
        int: 'int',
        bool: 'bool',
        float: 'float',
        list: 'list',
        str: 'str',
        ObjectId: 'ObjectId',
        datetime.datetime: 'datetime',
        }
    # All the dict sub-types that we recognize (for the purpose of
    # remote access).
    subtypenames = set([ 'text', 'code', 'gentext' ])
    # All the strings which are valid in a propaccess types list.
    alltypenameset = subtypenames.union(typenamemap.values()).union(['read'])

    def __init__(self, world, fromworld):
        self.wid = world['_id']
        self.fromwid = fromworld['_id']
        
        if world['creator'] == fromworld['creator']:
            self.allaccess = True
            self.keymap = None
        else:
            self.allaccess = False
            self.keymap = {}   # maps key names to permission sets

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
            self.keymap[ent['key']] = set(ent['types'])
        # cursor autoclose
        
        if not self.keymap:
            raise Exception('Cannot access another creator\'s world without permission')
        return

    def canread(self, key):
        if self.allaccess:
            return True
        if 'read' in self.keymap:
            return True
        return False

    def canwrite(self, key, val):
        if self.allaccess:
            return True
        typ = type(val)
        if typ is dict:
            subtyp = val.get('type', None)
            if type(subtyp) is str and subtyp in RemoteAccessMap.subtypenames:
                typname = subtyp
            else:
                typname = 'dict'
        else:
            typname = RemoteAccessMap.typenamemap.get(typ)
        if typname in self.keymap:
            return True
        return False

    def candelete(self, key):
        if self.allaccess:
            return True
        # We permit delete if there's any write permission at all; that is,
        # any permission other than 'read'.
        if len(self.keymap) > 1:
            return True
        if len(self.keymap) == 1 and ('read' not in self.keymap):
            return True
        return False
