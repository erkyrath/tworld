#!/usr/bin/env python3

"""
tweb: Copyright (c) 2013, Andrew Plotkin
(Available under the MIT License; see LICENSE file.)

This is the top-level script which acts as Tworld's web server.

Tweb is built on Tornado (a Python web app framework). It handles normal
page requests for web clients, tracks login sessions, and accepts web
socket connections. All game commands come in over the websockets; tweb
passes those along to the tworld server, and relays back the responses.
"""

import sys
import datetime
import logging
import signal

import tornado.web
import tornado.gen
import tornado.ioloop
import tornado.options

import motor

# Set up all the options. (Generally found in the config file.)

# Clever hack to parse a config file off the command line.
tornado.options.define(
    'config', type=str,
    help='configuration file',
    callback=lambda path: tornado.options.parse_config_file(path, final=False))

tornado.options.define(
    'template_path', type=str,
    help='template directory')
tornado.options.define(
    'static_path', type=str,
    help='static files directory (for /static URLs)')
tornado.options.define(
    'python_path', type=str,
    help='Python modules directory (optional)')

tornado.options.define(
    'app_title', type=str, default='Tworld',
    help='name of app (plain text, appears in <title>)')
tornado.options.define(
    'app_banner', type=str, default='Tworld',
    help='name of app (html, appears in page header <h1>)')

tornado.options.define(
    'top_pages', type=str, multiple=True,
    help='additional pages served from templates')
tornado.options.define(
    'top_static_regex', type=str, multiple=True,
    help='additional static files and directories')
tornado.options.define(
    'top_static_base_path', type=str,
    help='directory for top_static_regex files')

tornado.options.define(
    'port', type=int, default=4000,
    help='port number to listen on')
tornado.options.define(
    'hostname', type=str, default='localhost',
    help='host name to display in absolute URLs')

tornado.options.define(
    'email_from', type=str,
    help='return address for automated email')
tornado.options.define(
    'email_command', type=str,
    help='shell command to send email')

tornado.options.define(
    'debug', type=bool,
    help='application debugging (see Tornado docs)')
tornado.options.define(
    'log_level', type=str, default=None,
    help='logging threshold (default usually WARNING)')
tornado.options.define(
    'log_file_tweb', type=str, default=None,
    help='log file to write to (default is stdout)')

tornado.options.define(
    'ssl_port', type=int,
    help='port number to listen on for https connections')
tornado.options.define(
    'ssl_cert_path', type=str, default=None,
    help='path to SSL cert file')
tornado.options.define(
    'ssl_key_path', type=str, default=None,
    help='path to SSL key file')
tornado.options.define(
    'ssl_key_password', type=str, default=None,
    help='passphrase for SSL key file (default is no passphrase)')

tornado.options.define(
    'tworld_port', type=int, default=4001,
    help='port number for communication between tweb and tworld')

tornado.options.define(
    'mongo_database', type=str, default='tworld',
    help='name of mongodb database')
tornado.options.define(
    'cookie_secret', type=str,
    help='cookie secret key (see Tornado docs)')

# Parse 'em up.
tornado.options.parse_command_line()
opts = tornado.options.options

if opts.python_path:
    sys.path.insert(0, opts.python_path)


# Set up the logging configuration.
logconf = {
    'format': '[%(levelname).1s %(asctime)s: %(module)s:%(lineno)d] %(message)s',
    'datefmt': '%b-%d %H:%M:%S',
    }
if opts.log_level:
    logconf['level'] = opts.log_level
if opts.log_file_tweb:
    logconf['filename'] = opts.log_file_tweb
else:
    logconf['stream'] = sys.stdout
logging.basicConfig(**logconf)


# Set up the SSL configuration.
sslcontext = None
if opts.ssl_port:
    import ssl  # only import if needed
    if (not opts.ssl_cert_path) or (not opts.ssl_key_path):
        logging.getLogger("tornado.general").error('Must supply both ssl_cert_path and ssl_key_path')
    sslcontext = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    sslcontext.load_cert_chain(opts.ssl_cert_path, opts.ssl_key_path, password=opts.ssl_key_password)
    logging.getLogger("tornado.general").info('SSL is configured.')


# Now that we have a python_path, we can import the tworld-specific modules.

import twcommon.localize
import twcommon.autoreload
import twcommon.misc
import tweblib.session
import tweblib.handlers
import tweblib.bhandlers
import tweblib.admhandlers
import tweblib.connections
import tweblib.servers

# Define application options which are always set.
appoptions = {
    'xsrf_cookies': True,
    'static_handler_class': tweblib.handlers.MyStaticFileHandler,
    }

# Pull out some of the config-file options to pass along to the application.
for key in [ 'debug', 'template_path', 'static_path', 'cookie_secret' ]:
    val = getattr(opts, key)
    if val is not None:
        appoptions[key] = val

# Core handlers.
handlers = [
    (r'/', tweblib.handlers.MainHandler),
    (r'/register', tweblib.handlers.RegisterHandler),
    (r'/recover', tweblib.handlers.RecoverHandler),
    (r'/recover/([0-9a-f]+)', tweblib.handlers.Recover2Handler),
    (r'/logout', tweblib.handlers.LogOutHandler),
    (r'/play', tweblib.handlers.PlayHandler),
    (r'/portlink/([0-9a-f]+)', tweblib.handlers.PortLinkHandler),
    (r'/account', tweblib.handlers.AccountHandler),
    (r'/nobuild', tweblib.bhandlers.NoBuildHandler),
    (r'/build', tweblib.bhandlers.BuildMainHandler),
    (r'/build/world/([0-9a-f]+)', tweblib.bhandlers.BuildWorldHandler),
    (r'/build/portlist/([0-9a-f]+)', tweblib.bhandlers.BuildPortListHandler),
    (r'/build/propaccess/([0-9a-f]+)', tweblib.bhandlers.BuildPropAccessWorldHandler),
    (r'/build/trash/([0-9a-f]+)', tweblib.bhandlers.BuildTrashWorldHandler),
    (r'/build/loc/([0-9a-f]+)', tweblib.bhandlers.BuildLocHandler),
    (r'/build/export/([0-9a-f]+)', tweblib.bhandlers.BuildExportWorldHandler),
    (r'/build/addworld', tweblib.bhandlers.BuildAddWorldHandler),
    (r'/build/addloc', tweblib.bhandlers.BuildAddLocHandler),
    (r'/build/delloc', tweblib.bhandlers.BuildDelLocHandler),
    (r'/build/addprop', tweblib.bhandlers.BuildAddPropHandler),
    (r'/build/setprop', tweblib.bhandlers.BuildSetPropHandler),
    (r'/build/addportlist', tweblib.bhandlers.BuildAddPortListHandler),
    (r'/build/delportlist', tweblib.bhandlers.BuildDelPortListHandler),
    (r'/build/addport', tweblib.bhandlers.BuildAddPortHandler),
    (r'/build/setport', tweblib.bhandlers.BuildSetPortHandler),
    (r'/build/setpropaccess', tweblib.bhandlers.BuildSetPropAccessHandler),
    (r'/build/setdata', tweblib.bhandlers.BuildSetDataHandler),
    (r'/admin', tweblib.admhandlers.AdminMainHandler),
    (r'/admin/sessions', tweblib.admhandlers.AdminSessionsHandler),
    (r'/admin/players', tweblib.admhandlers.AdminPlayersHandler),
    (r'/admin/player/([0-9a-f]+)', tweblib.admhandlers.AdminPlayerHandler),
    (r'/websocket', tweblib.handlers.PlayWebSocketHandler),
    ]

# Add in all the top_pages handlers.
for val in opts.top_pages:
    handlers.append( ('/'+val, tweblib.handlers.TopPageHandler, {'page': val}) )

# And any top_static_regex files or directories.
if opts.top_static_regex and opts.top_static_base_path:
    for val in opts.top_static_regex:
        handlers.append( ('/('+val+')', tweblib.handlers.MyStaticFileHandler, {'path': opts.top_static_base_path}) )

# Fallback 404 handler for everything else.
handlers.append( (r'.*', tweblib.handlers.MyNotFoundErrorHandler) )

class TwebApplication(tornado.web.Application):
    """TwebApplication is a customization of the generic Tornado web app
    class.
    """
    
    def init_tworld(self):
        """Perform app-specific initialization.
        """
        # The parsed options (all of them, not just the tornado options)
        self.twopts = opts
        
        # Grab the same logger that tornado uses.
        self.twlog = logging.getLogger("tornado.general")

        # This will be self.twservermgr.mongo[mongo_database], when that's
        # available.
        self.mongodb = None

        # This will be replaced when mongodb connects.
        self.twlocalize = twcommon.localize.Localization()

        # Set up a session manager (for web client sessions).
        self.twsessionmgr = tweblib.session.SessionMgr(self)

        # And a server manager (for mongodb and tworld connections).
        self.twservermgr = tweblib.servers.ServerMgr(self)

        # And a connection table (for talking to tworld).
        self.twconntable = tweblib.connections.ConnectionTable(self)

        # When the IOLoop starts, we'll set up periodic tasks.
        tornado.ioloop.IOLoop.instance().add_callback(self.init_timers)

    def init_timers(self):
        """Perform more app-specific initialization when the IOLoop starts
        running. (This launches timers and so on. Really I could do this
        stuff in init_tworld(), but I like keeping this part separate.)
        """
        self.twlog.info('Launching timers')
        self.twlaunchtime = twcommon.misc.now()
        self.twservermgr.init_timers()

        # Catch SIGINT (ctrl-C) and SIGHUP with our own signal handler.
        # The handler will try to close sockets cleanly and allow messages
        # to drain out.
        # (Not SIGKILL; we leave that as a shut-down-right-now option.)
        self.caughtinterrupt = False
        signal.signal(signal.SIGINT, self.interrupt_handler)
        signal.signal(signal.SIGHUP, self.interrupt_handler)

        # The session expiration monitor. Runs once per minute.
        res = tornado.ioloop.PeriodicCallback(self.twsessionmgr.monitor_sessions, 60000)
        res.start()

        # The pwrecover expiration monitor. Runs once per hour.
        res = tornado.ioloop.PeriodicCallback(self.twsessionmgr.monitor_pwrecover, 3600050)
        res.start()

        # The trashprop expiration monitor. Runs once per hour.
        res = tornado.ioloop.PeriodicCallback(self.twsessionmgr.monitor_trashprop, 3601050)
        res.start()
        

    def interrupt_handler(self, signum, stackframe):
        """Signal handler for SIGINT and SIGHUP. We set a flag to prevent
        further requests, and set a timer for final shutdown.
        """
        if signum == signal.SIGINT:
            signame = 'Interrupt'
        elif signum == signal.SIGHUP:
            signame = 'Hangup'
        else:
            signame = 'Signal %s' % (signum,)
        if self.caughtinterrupt:
            self.twlog.error('%s! Shutting down immediately!', signame)
            raise KeyboardInterrupt()
        self.twlog.warning('%s! Queueing shutdown!', signame)
        self.caughtinterrupt = True
        ioloop = tornado.ioloop.IOLoop.instance()
        def func():
            self.twlog.info('Waiting 1 second for requests to drain...')
            ioloop.add_timeout(datetime.timedelta(seconds=1.0),
                               self.final_shutdown)
        ioloop.add_callback_from_signal(func)

    def autoreload_handler(self):
        self.twlog.warning('Queueing autoreload shutdown!')
        self.caughtinterrupt = True
        ioloop = tornado.ioloop.IOLoop.instance()
        self.twlog.info('Waiting 1 second for requests to drain...')
        ioloop.add_timeout(datetime.timedelta(seconds=1.0),
                           self.final_autoreload)

    def final_shutdown(self):
        self.twservermgr.mongo_disconnect()
        self.twlog.info('Shutting down for real.')
        sys.exit(0)
        
    def final_autoreload(self):
        self.twservermgr.mongo_disconnect()
        self.twlog.info('Autoreloading for real.')
        twcommon.autoreload.autoreload()
        sys.exit(0)   # Should not reach here

    def tworld_players_connected_count(self):
        """How many players are currently connected? This is fast.
        Well, fairly fast -- it doesn't do any database access.
        """
        players = self.twconntable.all()
        ls = [ player.uid for player in players ]
        return len(set(ls))

    def tworld_players_connected_count_active(self):
        """How many players are currently connected, and how many
        are not idle? Returns an ordered pair. Also fast.
        """
        players = self.twconntable.all()
        # Sort by idle time, most-active first.
        players.sort(key=lambda player:player.lastmsgtime, reverse=True)
        map = {}
        now = twcommon.misc.now()
        mindelta = datetime.timedelta(minutes=5)
        activecount = 0
        for player in players:
            if player.uid not in map:
                map[player.uid] = player
                if (now - player.lastmsgtime) < mindelta:
                    activecount += 1
        return ( len(map), activecount )

    @tornado.gen.coroutine
    def tworld_players_connected_list(self):
        """Return a list of structures representing connected players
        and where they are. This is relatively slow and you probably
        don't want it exposed to web-crawlers.
        (Since this is yieldy, I can't make it generally available
        as a ui_method.)
        """
        try:
            players = self.twconntable.all()
            # Sort by idle time, most-active first.
            players.sort(key=lambda player:player.lastmsgtime, reverse=True)
            # Limit how much work we'll do; the first N (unique) players.
            ls = []
            tempset = set()
            for player in players:
                if len(ls) >= 12:
                    break
                if player.uid in tempset:
                    continue
                tempset.add(player.uid)
                ls.append(player)
            players = ls
            ls = list(tempset)
            # At this point, ls is a list of uids, and players is a list of
            # Connection objects.
            # Look up the names of these players
            namemap = {}
            if ls:
                cursor = self.mongodb.players.find({'_id':{'$in':ls}},
                                                   {'name':1})
                while (yield cursor.fetch_next):
                    res = cursor.next_object()
                    if res.get('name', None):
                        namemap[res['_id']] = res['name']
                # cursor autoclose
            # Now look up their instance IDs
            iidmap = {}
            if ls:
                cursor = self.mongodb.playstate.find({'_id':{'$in':ls}},
                                                     {'iid':1})
                while (yield cursor.fetch_next):
                    res = cursor.next_object()
                    if res.get('iid', None):
                        iidmap[res['_id']] = res['iid']
                # cursor autoclose
            # Look up the world IDs for these instances.
            widmap = {}
            ls = list(set(iidmap.values()))
            if ls:
                cursor = self.mongodb.instances.find({'_id':{'$in':ls}},
                                                     {'wid':1})
                while (yield cursor.fetch_next):
                    res = cursor.next_object()
                    if res.get('wid', None):
                        widmap[res['_id']] = res['wid']
                # cursor autoclose
            # Finally, look up the world names for these worlds.
            worldnamemap = {}
            ls = list(set(widmap.values()))
            if ls:
                cursor = self.mongodb.worlds.find({'_id':{'$in':ls}},
                                                  {'name':1})
                while (yield cursor.fetch_next):
                    res = cursor.next_object()
                    worldnamemap[res['_id']] = res.get('name', '???')
                # cursor autoclose
            # Now construct the result array.
            now = twcommon.misc.now()
            mindelta = datetime.timedelta(minutes=5)
            res = []
            for player in players:
                iid = iidmap.get(player.uid, None)
                wid = None
                worldname = '(in transition)'
                if iid:
                    wid = widmap.get(iid, None)
                if wid:
                    worldname = worldnamemap.get(wid, None)
                # Work out how long they've been idle. This should be in
                # a utility module somewhere.
                delta = now - player.lastmsgtime
                if (delta < mindelta):
                    time = 'active'
                else:
                    time = 'idle ' + twcommon.misc.timedelta_two_units(delta)
                val = { 'name':namemap.get(player.uid, '???'),
                        'idle':time,
                        'world':worldname }
                res.append(val)
            return res
        except Exception as ex:
            self.twlog.error('tworld_players_connected_list failed', exc_info=True)
            return []

application = TwebApplication(
    handlers,
    ui_methods={
        'tworld_app_title': lambda handler:opts.app_title,
        'tworld_app_banner': lambda handler:opts.app_banner,
        'tworld_connected_count': lambda handler:handler.application.tworld_players_connected_count(),
        'tworld_connected_count_active': lambda handler:handler.application.tworld_players_connected_count_active(),
        'tworld_portlink': lambda handler:handler.render_portal(handler.twportlink),
        },
    **appoptions)

if opts.debug:
    twcommon.autoreload.sethandler(application.autoreload_handler)

application.init_tworld()
application.listen(opts.port)
if sslcontext:
    application.listen(opts.ssl_port, ssl_options=sslcontext) ### sslport
tornado.ioloop.IOLoop.instance().start()
