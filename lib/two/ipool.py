"""
The collection of instances which are currently "awake", that is, in use
by players. We use this to optimize resource usage -- timer events, in
particular. (A future version will probably use this for property caching
as well.)

The scheduling queue for script events is based on these principles:

- An instance is "awake" whenever any players are in it. Once it is empty,
  after some period of time, it goes "asleep".
- The world can provide on_wake and on_sleep properties to do work on these
  transitions.
- When an instance is asleep, it has no timer events in the queue. (All
  its events are dropped after the on_sleep call.) The on_wake call is
  responsible for setting these up if necessary.
- The sched queue is purely in-memory; it has no database representation.
  This means that if the server crashes or is shut down, all instances
  are de facto asleep -- and the on_sleep call will not occur. Don't rely
  on it.
- When the server starts up, on_wake calls occur for every inhabited
  instance. (Alternatively, we may boot all those players to the void and
  let the wake-ups occur if/when they reappear.)
"""

import twcommon.misc

class InstancePool:
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = self.app.log

        # The map containing all currently-awake instances.
        # Maps iids (ObjectIds) to Instance objects.
        self.map = {}

    def count(self):
        """How many instances are currently awake?
        """
        return len(self.map)

    def get(self, iid):
        """Look up an instance by its iid.
        """
        return self.map.get(iid, None)

    def all(self):
        """A (non-dynamic) list of all awake instances.
        """
        return list(self.map.values())

    def notify_instance(self, iid):
        """Notify an instance that it should be awake. If it is not already,
        this adds it to the pool and returns True.
        """
        instance = self.map.get(iid, None)
        if instance is not None:
            instance.lastportin = twcommon.misc.now()
            return False

        instance = Instance(iid)
        self.map[iid] = instance
        return True

class Instance:
    def __init__(self, iid):
        self.iid = iid
        
        # Timestamp of most recent player entry. We initialize this to
        # now, because player entry is what triggers this initialization.
        self.lastportin = twcommon.misc.now()
