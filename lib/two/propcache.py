"""
Property cache: sits on top of the database and keeps known values in memory.

(Also keeps known *non*-values in memory; that is, a hit that returns nothing
is cached as a nothing.)

This also tracks mutable values, and is able to write them back to the
database if they change.

Currently, this lives in a task and its lifespan is just the duration of the
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

        self.objmap = {}
        self.propmap = {}

    def final(self):
        """Shut down and clean up.

        This does not write back dirty data. Be sure to call write_all_dirty()
        before this.
        """
        if self.dirty_entries():
            self.log.error('propcache: finalizing while dirty!')
            
        # Empty the maps, because maybe I'll add a backlink to the PropEntry
        # object and that would be a ref cycle.
        self.objmap.clear()
        self.propmap.clear()

        # Shut down.
        self.app = None
        self.objmap = None
        self.propmap = None

    def dirty_entries(self):
        return [ ent for ent in self.objmap.values() if ent.dirty() ]

    @tornado.gen.coroutine
    def write_all_dirty(self):
        ls = self.dirty_entries()
        ###

class PropEntry:
    def __init__(self, val):
        self.val = val
        self.found = True  # Was a database entry found at all?
        self.mutable = isinstance(val, (list, dict))

        if self.mutable:
            # Keep a copy, to check for possible changes
            self.origval = deepcopy(val)

    def dirty(self):
        """Has this value changed since we cached it?
        (Always false for immutable values.)
        
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

