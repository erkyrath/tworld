"""
This module has the (rather simplistic) localization/internationalization
support that Tworld uses. These functions are shared by tweb and tworld;
the data herein is passed along to the javascript client as well.

Because this data is used often and changed rarely, we cache it all in
memory. If you update it, you'll have to restart the tweb and tworld
processes, and also ask clients to reload their browser pages. (We might
add reloading notifications in the future.)

This class supports multiple languages; that is, the data table may have
entries for a given key in several languages. The tworld/tweb apps do not
yet make use of this facility, however. (It's not completely trivial,
because messages like oleave/oarrive are currently broadcast to all
listeners without change. Full language support would require localizing
these messages per-listener.)
"""

import tornado.gen
import motor

class Localization:
    """Create a Localization object with the (async) function
    load_localization(). Or you can construct a blank one directly.

    For simplicity, use the object by calling it: loc(key). There is
    no separate get method.
    """
    
    def __init__(self):
        """Initialize a blank object. This is usable; you'll just get
        placeholder defaults for every key.
        """
        # All the language-specific submaps, keyed by language code.
        # The default map (English) is self.langs[None].
        self.langs = { None: {} }

    def __call__(self, key, lang=None):
        """Get the localization of a key, in the given language or the
        default.
        """
        if lang is not None and lang in self.langs:
            res = self.langs[lang].get(key, None)
            if res is not None:
                return res
        res = self.langs[None].get(key, None)
        if res is not None:
            return res
        # Not found. Return a terrible default that people will notice.
        return '** %s **' % (key,)

    def all(self, lang=None):
        """Return the entire map for a given language (including defaults).
        """
        # Make a copy.
        map = dict(self.langs[None])
        if lang is not None and lang in self.langs:
            map.extend(self.langs[lang])
        return map


@tornado.gen.coroutine
def load_localization(app, clientonly=False):
    """Load up the localization data.
    We rely on the fact that the tweb and tworld application classes both
    have an app.mongodb field.
    """
    localization = Localization()
    
    # Go through the entire "localize" collection. Unless we want only
    # the client entries.
    search = {}
    if clientonly:
        search = { 'client': True }
    cursor = app.mongodb.localize.find(search)
    while (yield cursor.fetch_next):
        loc = cursor.next_object()
        lang = loc['lang']
        map = localization.langs.get(lang, None)
        if map is None:
            map = {}
            localization.langs[lang] = map
        map[loc['key']] = loc['val']
        
    return localization
