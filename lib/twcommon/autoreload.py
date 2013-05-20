"""
This is a monkeypatch for tornado.autoreload. It enables us to deal with
an autoreload event on our own schedule, rather than the moment the timer
happens to notice a file change.

To use this, import it and call sethandler(func). When an autoreload change
is detected, your function will be called. (No more than once.) You should
then call autoreload() in this module to actually fork and restart the
process.

(Your function may call autoreload() immediately, or schedule it for some
future time.)
"""

import tornado.autoreload

orig_autoreload_func = None
custom_autoreload_func = None
autoreload_triggered = False

def sethandler(func):
    global orig_autoreload_func
    global custom_autoreload_func
    
    if orig_autoreload_func is not None:
        raise Exception('Cannot call sethandler() more than once!')

    # Copy and replace the _reload() function in tornado.autoreload.
    orig_autoreload_func = tornado.autoreload._reload
    tornado.autoreload._reload = perform

    custom_autoreload_func = func

def perform():
    """This is the replacement function that we drop into tornado.autoreload.
    It may be called several times in a row, so we keep a flag.
    """
    global autoreload_triggered
    
    if custom_autoreload_func is None:
        raise Exception('Must call sethandler() first!')
    if autoreload_triggered:
        # Ignore multiple notifications.
        return
    autoreload_triggered = True
    custom_autoreload_func()

def autoreload():
    """Re-fork this process. This function does not return.
    """
    orig_autoreload_func()


