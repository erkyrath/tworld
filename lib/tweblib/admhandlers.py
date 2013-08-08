"""
The admin-related URI request handlers used by Tweb.
"""

import datetime
import random
import re

from bson.objectid import ObjectId
import tornado.web
import tornado.gen

import motor

import tweblib.handlers
import twcommon.misc

class AdminBaseHandler(tweblib.handlers.MyRequestHandler):
    """Base class for the handlers for admin pages. This has some common
    functionality.
    """
    @tornado.gen.coroutine
    def prepare(self):
        """
        Called before every get/post invocation for this handler. We use
        the opportunity to look up the session status, and then make sure
        the player is an administrator.
        """
        yield self.find_current_session()
        if self.twsessionstatus != 'auth':
            raise tornado.web.HTTPError(403, 'You are not signed in.')
        res = yield motor.Op(self.application.mongodb.players.find_one,
                             { '_id':self.twsession['uid'] })
        if not res or not res.get('admin', False):
            raise tornado.web.HTTPError(403, 'You do not have admin access.')

class AdminMainHandler(AdminBaseHandler):
    """Handler for the Admin page, which is rudimentary and not worth much
    right now.
    """
    @tornado.gen.coroutine
    def get(self):
        uptime = (twcommon.misc.now() - self.application.twlaunchtime)
        uptime = datetime.timedelta(seconds=int(uptime.total_seconds()))
        self.render('admin.html',
                    uptime=uptime,
                    mongoavailable=(self.application.mongodb is not None),
                    tworldavailable=(self.application.twservermgr.tworldavailable),
                    conntable=self.application.twconntable.as_dict())

    @tornado.gen.coroutine
    def post(self):
        if (self.get_argument('playerconntable', None)):
            msg = { 'cmd':'logplayerconntable' }
            self.application.twservermgr.tworld_write(0, msg)
        self.redirect('/admin')

class AdminSessionsHandler(AdminBaseHandler):
    """Handler for the Admin page which displays recent sessions.
    """
    @tornado.gen.coroutine
    def get(self):
        now = twcommon.misc.now()
        PER_PAGE = 16
        page = 0
        sessions = []
        cursor = self.application.mongodb.sessions.find(
            {},
            sort=[('starttime', motor.pymongo.DESCENDING)],
            skip=page*PER_PAGE,
            limit=PER_PAGE)
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            sessions.append(prop)
            try:
                delta = now - prop['starttime']
                prop['sincestarttime'] = datetime.timedelta(seconds=int(delta.total_seconds()))
            except:
                pass
        # cursor autoclose
        self.render('admin_sessions.html',
                    sessions=sessions)

class AdminPlayersHandler(AdminBaseHandler):
    """Handler for the Admin page which displays the players list.
    """
    @tornado.gen.coroutine
    def get(self):
        now = twcommon.misc.now()
        PER_PAGE = 16
        try:
            page = int(self.get_argument('page', 0))
            page = max(0, page)
        except:
            page = 0
        players = []
        cursor = self.application.mongodb.players.find(
            {},
            sort=[('createtime', motor.pymongo.DESCENDING)],
            skip=page*PER_PAGE,
            limit=PER_PAGE)
        while (yield cursor.fetch_next):
            prop = cursor.next_object()
            players.append(prop)
        # cursor autoclose
        self.render('admin_players.html',
                    page=page,
                    hasnext=int(len(players) == PER_PAGE), hasprev=int(page > 0),
                    players=players)

class AdminPlayerHandler(AdminBaseHandler):
    """Handler for the Admin page which displays a player record.
    """
    @tornado.gen.coroutine
    def get(self, uid):
        uid = ObjectId(uid)
        player = yield motor.Op(self.application.mongodb.players.find_one,
                                { '_id':uid })
        if not player:
            raise tornado.web.HTTPError(404, 'Player not found.')

        loc = None
        instance = None
        scope = None
        world = None
        
        playstate = yield motor.Op(self.application.mongodb.playstate.find_one,
                                   { '_id':uid })
        if playstate:
            if playstate['locid']:
                loc = yield motor.Op(self.application.mongodb.locations.find_one,
                                     { '_id':playstate['locid'] })
            if playstate['iid']:
                instance = yield motor.Op(self.application.mongodb.instances.find_one,
                                          { '_id':playstate['iid'] })
            if instance:
                scope = yield motor.Op(self.application.mongodb.scopes.find_one,
                                       { '_id':instance['scid'] })
                world = yield motor.Op(self.application.mongodb.worlds.find_one,
                                       { '_id':instance['wid'] })

        locname = '(none)'
        if loc:
            locname = loc.get('name', '???')
        worldname = '(none)'
        if world:
            worldname = world.get('name', '???')
        scopetype = '(none)'
        if scope:
            scopetype = scope.get('type', '???')

        playername = player.get('name', '???')
        self.render('admin_player.html',
                    player=player, playername=playername,
                    connlist=self.application.twconntable.for_uid(uid),
                    playstate=playstate,
                    isadmin=player.get('admin', False),
                    isbuild=player.get('build', False),
                    worldname=worldname, scopetype=scopetype, locname=locname)

    @tornado.gen.coroutine
    def post(self, uid):
        uid = ObjectId(uid)
        player = yield motor.Op(self.application.mongodb.players.find_one,
                                { '_id':uid })
        
        if (self.get_argument('playerbuildflag', None)):
            newflag = not player.get('build', False)
            yield motor.Op(self.application.mongodb.players.update,
                           { '_id':uid },
                           { '$set':{'build':newflag} })
        
            self.redirect(self.request.path)
            return

        if (self.get_argument('playerkillconn', None)):
            connid = int(self.get_argument('connid'))
            conn = self.application.twconntable.find(connid)
            conn.close('Connection closed by administrator.')
            self.redirect(self.request.path)
            return

        raise Exception('Unknown form type')
