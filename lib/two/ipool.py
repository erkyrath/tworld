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

import datetime

import twcommon.misc
from twcommon.excepts import ExecRunawayException

class InstancePool:

    # How long an instance stays uninhabited before we put it to sleep.
    UNINHABITED_LIMIT = datetime.timedelta(minutes=10.5)

    # Minimum intervals for scheduled events. (We don't want a millisecond
    # timer to start buzzing away.)
    MIN_SCHED_DELAY = datetime.timedelta(seconds=1)
    MIN_SCHED_REPEAT_DELAY = datetime.timedelta(seconds=10)

    # Maximum number of scheduled events at a time.
    MAX_SCHED_EVENTS = 16
    
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
            # Mark the instance as currently inhabited (and ported-into)
            now = twcommon.misc.now()
            instance.lastportin = now
            instance.lastinhabited = now
            return False

        # Newly awakened instance. The caller is responsible for invoking
        # the on_wake hook.
        instance = Instance(self.app, iid)
        self.map[iid] = instance
        return True

    def remove_instance(self, iid):
        """Remove an instance which has been put to sleep.
        """
        instance = self.map.pop(iid, None)  # removes and returns it
        if instance is None:
            return
        instance.remove_timer_events()
        instance.close()

class Instance:
    def __init__(self, app, iid):
        self.app = app
        self.iid = iid
        self.timers = set()

        now = twcommon.misc.now()
        
        # Timestamp of most recent player entry. We initialize this to
        # now, because player entry is what triggers this initialization.
        self.lastportin = now

        # Timestamp of the last time the instance was known to be inhabited.
        self.lastinhabited = now

        # Total number of timer events that have run in this waking period.
        self.totaltimerevents = 0

    def close(self):
        if len(self.timers):
            self.app.log.warning('Instance had %d timers at close!', len(self.timers))
        self.app = None
        self.iid = None
        self.timers = None
        
    def add_timer_event(self, delta, func, repeat=False, cancel=None):
        """Add a timer event to the instance. This is invoked by the
        sched() builtin script function.
        """
        # Make sure the time delta is legal.
        if not repeat:
            if delta < InstancePool.MIN_SCHED_DELAY:
                raise Exception('sched(): delay must be at least %d seconds' % (InstancePool.MIN_SCHED_DELAY.total_seconds(),))
        else:
            if delta < InstancePool.MIN_SCHED_REPEAT_DELAY:
                raise Exception('sched(): repeating delay must be at least %d seconds' % (InstancePool.MIN_SCHED_REPEAT_DELAY.total_seconds(),))

        if len(self.timers) >= InstancePool.MAX_SCHED_EVENTS:
            self.app.log.error('ExecRunawayException: User script exceeded timer event limit!')
            raise ExecRunawayException('sched(): limit of %d events at a time' % (InstancePool.MAX_SCHED_EVENTS,))

        # Add the event.
        timer = TimerEvent(delta, func, repeat=repeat, cancel=cancel)
        self.timers.add(timer)

        # We use IOLoop.add_timeout for both single and repeating events.
        ### This means a bit of inevitable timer drift.
        timer.cancelrock = self.app.ioloop.add_timeout(delta, lambda:self.fire_timer_event(timer))

    def remove_timer_events(self, cancel=None):
        """Remove all timer events which match the given cancel key.
        If the argument is not provided or None, remove *all* timer events
        for the instance.
        """
        if cancel is None:
            ls = list(self.timers)
        else:
            ls = [ timer for timer in self.timers if timer.cancel == cancel ]
        for timer in ls:
            try:
                if timer.cancelrock is not None:
                    self.app.ioloop.remove_timeout(timer.cancelrock)
            except:
                pass
            try:
                self.timers.remove(timer)
            except:
                pass
            # Mark the timer as done-with.
            timer.delta = None

    def fire_timer_event(self, timer):
        """Invoked when a timer event fires. Note that this is *not*
        called from the command queue! We may be in the middle of some
        task. So we do nothing except queue a command and (perhaps)
        reschedule the timer.
        """
        if timer not in self.timers:
            raise Exception('Timer not in instance timers list!')
        if timer.delta is None:
            raise Exception('Timer executing after being cancelled!')
        
        # It's out of the ioloop queue, so this cancelrock is no longer useful.
        timer.cancelrock = None
        
        if timer.repeat:
            # Reschedule repeating events, and leave in timers list.
            timer.cancelrock = self.app.ioloop.add_timeout(timer.delta, lambda:self.fire_timer_event(timer))
        else:
            # Remove from timers list.
            self.timers.remove(timer)

        self.app.queue_command({'cmd':'timerevent', 'iid':self.iid, 'func':timer.func})
        
class TimerEvent:
    """Record of a scheduled timer event. Data-only class.
    """
    def __init__(self, delta, func, repeat=False, cancel=None):
        self.delta = delta
        self.func = func
        self.repeat = repeat
        self.cancel = cancel
        self.cancelrock = None
