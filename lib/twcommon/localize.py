"""
This module has the (rather simplistic) localization/internationalization
support that Tworld uses. These functions are shared by tweb and tworld;
the data herein is passed along to the javascript client as well.

Because this data is used often and changed rarely, we cache it all in
memory. If you update it, you'll have to restart the tweb and tworld
processes, and also ask clients to reload their browser pages. (We might
add reloading notifications in the future.)
"""

import tornado.gen
import motor

class Localization:
    def __init__(self):
        """Initialize a blank object. This is usable; you'll just get
        placeholder defaults for every key.
        """
        # All the language-specific submaps, keyed by language code.
        # The default map (English) is self.langs[None].
        self.langs = { None: {} }

    def get(self, key, lang=None):
        if lang is not None and lang in self.langs:
            res = self.langs[lang].get(key, None)
            if res is not None:
                return res
        res = self.langs[None].get(key, None)
        if res is not None:
            return res
        # Not found. Return a terrible default that people will notice.
        return '** %s **' % (key,)
        
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
        search = { client:True }
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
