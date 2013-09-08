"""
Property cache: sits on top of the database and keeps known values in memory.

(Also keeps known *non*-values in memory; that is, a hit that returns nothing
is cached as a nothing.)

This also tracks mutable values, and is able to write them back to the
database if they change.

Currently, this lives in the app, but its lifespan is just the duration of one
task. A future version may hang around longer.
"""

import tornado.gen
from bson.objectid import ObjectId
import motor

class PropCache:
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = self.app.log

        self.objmap = {}  # maps id(val) to PropEntry
        self.propmap = {}  # maps tuple to PropEntry
        # propmap contains not-found entries; objmap does not.

    def final(self):
        """Shut down and clean up.

        This does not write back dirty data. Be sure to call write_all_dirty()
        before this.
        """
        ls = self.dirty_entries()
        if ls:
            self.log.error('propcache: finalizing while %d dirty entries!', len(ls))
            
        # Empty the maps, because PropEntry might have a backlink to this
        # PropCache someday and that would be a ref cycle.
        self.objmap.clear()
        self.propmap.clear()

        # Shut down.
        self.app = None
        self.objmap = None
        self.propmap = None

    @staticmethod
    def query_for_tuple(tup):
        (db, id1, id2, key) = tup
        if db == 'worldprop':
            return {'wid':id1, 'locid':id2, 'key':key}
        if db == 'instanceprop':
            return {'iid':id1, 'locid':id2, 'key':key}
        if db == 'wplayerprop':
            return {'wid':id1, 'uid':id2, 'key':key}
        if db == 'iplayerprop':
            return {'iid':id1, 'uid':id2, 'key':key}
        raise Exception('Unknown collection: %s' % (db,))

    @tornado.gen.coroutine
    def get(self, tup, dependencies=None):
        """Fetch a value from the database, or the cache if it's cached.

        The tup argument has four entries: ('worldprop', wid, locid, key).
        The meaning of the second and third depend on the database collection
        (the first entry). This is the same format as dependency keys.
        Currently this class understands 'instanceprop', 'worldprop',
        'iplayerprop', 'wplayerprop'.
        
        Returns a PropEntry (if found) or None (if not). The value you
        want is res.val if res is not None.

        (Note that this may return None to indicate that we checked the
        database earlier, found nothing, and cached that fact.)
        """
        if dependencies is not None:
            dependencies.add(tup)
            
        ent = self.propmap.get(tup, None)
        if ent is not None:
            if not ent.found:
                # Cached "not found" value
                return None
            return ent

        dbname = tup[0]
        query = PropCache.query_for_tuple(tup)
        res = yield motor.Op(self.app.mongodb[dbname].find_one,
                             query,
                             {'val':1})
        self.log.debug('### db get: %s %s (%s)', dbname, query, bool(res))
        if not res:
            ent = PropEntry(None, tup, query, found=False)
        else:
            val = res['val']
            ent = PropEntry(val, tup, query, found=True)
            self.objmap[id(val)] = ent
        self.propmap[tup] = ent

        if not ent.found:
            # Cached "not found" value
            return None
        return ent

    @tornado.gen.coroutine
    def set(self, tup, val):
        """Set a new object in the database (and the cache). If we had
        an object cached at this tuple, it's discarded.
        """
        pass ###
        
    @tornado.gen.coroutine
    def delete(self, tup, val):
        """Delete an object from the database (and the cache).
        """
        pass ###
        
    def get_by_object(self, val):
        """Check whether a value is in the cache. This is keyed by the
        *identity* of the value!
        Returns a PropEntry (if found) or None (if not).
        """
        return self.objmap.get(id(val), None)

    def dirty_entries(self):
        return [ ent for ent in self.objmap.values() if ent.dirty() ]

    @tornado.gen.coroutine
    def write_all_dirty(self):
        self.log.debug('### write_all time: cache is %s', self.propmap)
        ls = self.dirty_entries()
        for ent in ls:
            yield self.write_dirty(ent)

    @tornado.gen.coroutine
    def write_dirty(self, ent):
        pass ###

class PropEntry:
    """Represents a database entry, or perhaps the lack of a database entry.
    """
    
    def __init__(self, val, tup, query, found=True):
        self.val = val
        self.tup = tup  # Dependency key
        self.dbname = tup[0]  # Collection name
        self.query = query  # Query in the collection
        self.found = found  # Was a database entry found at all?
        
        if not found:
            self.mutable = False
        else:
            self.mutable = isinstance(val, (list, dict))
            if self.mutable:
                # Keep a copy, to check for possible changes
                self.origval = deepcopy(val)

    def __repr__(self):
        if not self.found:
            val = '(not found)'
        else:
            val = repr(self.val)
            if len(val) > 32:
                val = val[:32] + '...'
        return '<PropEntry %s: %s>' % (self.tup, val)

    def dirty(self):
        """Has this value changed since we cached it?
        (Always false for immutable and not-found values.)
        
        ### This will fail to detect changes that compare equal. That is,
        ### if an array [True] changes to [1], this will not notice the
        ### difference.
        """
        return self.mutable and (self.val != self.origval)

def deepcopy(val):
    """Return a copy of a value. For immutable values, this returns the
    value itself. For mutables, it returns a deep copy.

    This presumes that the value is DB-storable. Therefore, the only
    mutable types are list and dict. (And dict keys are always strings.)
    """
    if isinstance(val, list):
        return [ deepcopy(subval) for subval in val ]
    if isinstance(val, dict):
        return dict([ (key, deepcopy(subval)) for (key, subval) in val.items() ])
    return val

