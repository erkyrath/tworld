"""
Property cache: sits on top of the database and keeps known values in memory.

(Also keeps known *non*-values in memory; that is, a hit that returns nothing
is cached so that we can return that fact.)

When a property is changed or deleted, we add a cache entry with the dirty
flag. At the end of the task, we call write_all_dirty() to resolve these
back to the database (update or delete).

This also tracks mutable values. If a list or dict changes, write_all_dirty()
detects that too and does an update.

Currently, this lives in the app, but its lifespan is just the duration of one
task. A future version may hang around longer.

### Future version should also do work in write_all_dirty() to break apart
### objmap sets larger than 1. Deepcopy all values, so that there's no
### id sharing any more.
"""

import tornado.gen
from bson.objectid import ObjectId
import motor

# Collections that code may update. (As opposed to 'worldprop', etc,
# which may only be updated by build code.)
writable_collections = set(['instanceprop', 'iplayerprop'])

class PropCache:
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = self.app.log

        self.propmap = {}  # maps tuple to PropEntry
        self.objmap = {}  # maps id(val) to set of PropEntry
        # objmap only contains entries for mutable values. A given value
        # may be in more than one property; that's why objmap contains
        # sets. (But we break these apart at write_all_dirty() time.)

    def final(self):
        """Shut down and clean up.

        This does not write back dirty data. Be sure to call write_all_dirty()
        before this.
        """
        ls = self.dirty_entries()
        if len(ls):
            self.log.error('propcache: finalizing while %d dirty entries!', len(ls))
            
        # Empty the maps, because PropEntry might have a backlink to this
        # PropCache someday and that would be a ref cycle.
        self.objmap.clear()
        self.propmap.clear()

        # Shut down.
        self.app = None
        self.objmap = None
        self.propmap = None

    def dump(self):
        """Print out cache contents. For debugging only.
        """
        print('Propcache: %d entries' % (len(self.propmap)))
        for ent in self.propmap.values():
            print('  %s' % (ent,))
        if self.objmap:
            print('...and %d in objmap' % (len(self.objmap)))
            for (id, oset) in self.objmap.items():
                print('  %s: %s' % (id, oset,))

    @staticmethod
    def query_for_tuple(tup):
        """Takes a four-el tuple (see below). Returns an object suitable
        for use in a mongodb operation, e.g.:
        yield motor.Op(self.app.mongodb[tup[0]].find_one, query)
        """
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
        if not res:
            ent = PropEntry(None, tup, query, found=False)
        else:
            val = res['val']
            ent = PropEntry(val, tup, query, found=True)
            
        self.propmap[tup] = ent
        if ent.mutable:
            assert ent.found
            oset = self.objmap.get(ent.id, None)
            if oset is None:
                self.objmap[ent.id] = set((ent,))
            else:
                oset.add(ent)

        if not ent.found:
            # Cached "not found" value
            return None
        return ent

    @tornado.gen.coroutine
    def set(self, tup, val):
        """Set a new (dirty) object in the cache. If we had an object cached
        at this tuple, it's discarded. (No database write occurs here.)
        """
        ent = self.propmap.get(tup, None)
        if ent:
            if ent.found and ent.val is val:
                # It's already there (exactly the same object).
                return
            # A property is cached. Drop this entry.
            del self.propmap[tup]
            if ent.mutable:
                oset = self.objmap.get(ent.id, None)
                if oset is not None:
                    oset.discard(ent)
                    if not oset:
                        del self.objmap[ent.id]
            ent = None

        # Create new entry.
        dbname = tup[0]
        assert dbname in writable_collections
        query = PropCache.query_for_tuple(tup)
        ent = PropEntry(val, tup, query, found=True, dirty=True)
        self.propmap[tup] = ent
        if ent.mutable:
            oset = self.objmap.get(ent.id, None)
            if oset is None:
                self.objmap[ent.id] = set((ent,))
            else:
                oset.add(ent)
        
    @tornado.gen.coroutine
    def delete(self, tup):
        """Set a new (dirty) object in the cache, representing not-found.
        (No database write occurs here.)
        """
        ent = self.propmap.get(tup, None)
        if ent:
            if not ent.found:
                # It's already non-there.
                return
            # A property is cached. Drop this entry.
            del self.propmap[tup]
            if ent.mutable:
                oset = self.objmap.get(ent.id, None)
                if oset is not None:
                    oset.discard(ent)
                    if not oset:
                        del self.objmap[ent.id]
            ent = None

        # Create new (not-found) entry.
        dbname = tup[0]
        assert dbname in writable_collections
        query = PropCache.query_for_tuple(tup)
        ent = PropEntry(None, tup, query, found=False, dirty=True)
        self.propmap[tup] = ent
        
    def get_by_object(self, val):
        """Check whether a value is in the cache. This is keyed by the
        *identity* of the value! Only locates mutable entries.
        Returns a PropEntry (if found) or None (if not). If an object
        is shared between several properties, returns an arbitrary one.
        """
        oset = self.objmap.get(id(val), None)
        if oset:
            return list(oset)[0]
        return None

    def dirty_entries(self):
        return [ ent for ent in self.propmap.values() if ent.isdirty() ]

    @tornado.gen.coroutine
    def write_all_dirty(self):
        ls = self.dirty_entries()
        for ent in ls:
            yield self.resolve_dirty(ent)

    @tornado.gen.coroutine
    def resolve_dirty(self, ent):
        dbname = ent.tup[0]
        if dbname not in writable_collections:
            # Maybe we should update the equivalent writable entry here,
            # but we'll just skip it.
            self.log.warning('Unable to update %s entry: %s', dbname, ent.key)
            if ent.mutable:
                ent.origval = deepcopy(ent.val)
            return

        if ent.found:
            # Resolve update.
            newval = dict(ent.query)
            newval['val'] = ent.val
            yield motor.Op(self.app.mongodb[dbname].update,
                           ent.query, newval,
                           upsert=True)
            if ent.mutable:
                ent.origval = deepcopy(ent.val)
        else:
            # Resolve delete.
            yield motor.Op(self.app.mongodb[dbname].remove,
                           ent.query)
        ent.dirty = False

class PropEntry:
    """Represents a database entry, or perhaps the lack of a database entry.
    """
    
    def __init__(self, val, tup, query, found=True, dirty=False):
        self.val = val
        self.tup = tup  # Dependency key
        self.dbname = tup[0]  # Collection name
        self.key = tup[-1]
        self.query = query  # Query in the collection
        self.found = found  # Was a database entry found at all?
        self.dirty = dirty  # Needs to be written back?

        # Mutable entries will be added to objmap.
        if not found:
            self.mutable = False
        else:
            self.id = id(val)
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
        isdirty = 'DIRTY:' if self.isdirty() else ''
        return '<PropEntry %s%s: %s>' % (isdirty, self.tup, val)

    def isdirty(self):
        """Has this value changed since we cached it?
        (Always true if we created this entry for a set/delete.)
        
        ### This will fail to detect changes that compare equal. That is,
        ### if an array [1] changes to [1.0], this will not notice the
        ### difference.
        """
        if self.dirty:
            return True
        if self.mutable and (self.val != self.origval):
            return True

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

