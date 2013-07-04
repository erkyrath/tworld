
import ast

import tornado.gen
import bson
from bson.objectid import ObjectId
import motor

import twcommon.misc
import twcommon.localize
from twcommon import wcproto
from twcommon.excepts import MessageException, ErrorMessageException

class Command:
    # As commands are defined with the @command decorator, they are stuffed
    # in this dict.
    all_commands = {}

    def __init__(self, name, func, isserver=False, restrict=None, noneedmongo=False, preconnection=False, doeswrite=False):
        self.name = name
        self.func = tornado.gen.coroutine(func)
        # isserver could be merged into restrict='server', since restrict
        # only applies to player commands.
        self.isserver = isserver
        self.restrict = restrict
        self.noneedmongo = noneedmongo
        self.preconnection = preconnection
        self.doeswrite = doeswrite
        
    def __repr__(self):
        return '<Command "%s">' % (self.name,)


def command(name, **kwargs):
    """Decorator for command functions.
    """
    def wrap(func):
        cmd = Command(name, func, **kwargs)
        if name in Command.all_commands:
            raise Exception('Command name defined twice: "%s"', name)
        Command.all_commands[name] = cmd
        return cmd
    return wrap

def define_commands():
    """
    Define all the commands which will be used by the server. Return them
    in a dict.

    Note that the last argument will be a IOStream for server commands,
    but a PlayerConnection for player commands. Never the twain shall
    meet.

    These functions wind up as entries in the Command.all_commands dict.
    The arguments to @command wind up as properties of the Command object
    that wraps the function. Oh, and the function is always a
    tornado.gen.coroutine -- you don't need to declare that.
    """

    @command('shutdownprocess', isserver=True, noneedmongo=True)
    def cmd_shutdownprocess(app, task, cmd, stream):
        """Shut down the process. We do this from a command, so that we
        can say for sure that no other command is in flight.
        This will be the last command to execute.
        """
        restartreason = getattr(cmd, 'restarting', False)
        if restartreason:
            val = 'Server broadcast: Server is restarting!'
        else:
            val = 'Server broadcast: Server is shutting down!'
        for stream in app.webconns.all():
            stream.write(wcproto.message(0, {'cmd':'messageall', 'text':val}))
        app.shutdown(restartreason)
        # At this point ioloop is still running, but the command queue
        # is frozen. A sys.exit will be along shortly.

    @command('dbconnected', isserver=True, doeswrite=True)
    def cmd_dbconnected(app, task, cmd, stream):
        # We've connected (or reconnected) to mongodb. Re-synchronize any
        # data that we had cached from there.
        # Right now this means: Load up the localization data.
        # Awaken any inhabited instances.
        # Go through the list of players who are in the world.
        try:
            task.app.localize = yield twcommon.localize.load_localization(task.app)
        except Exception as ex:
            task.log.warning('Caught exception (loading localization data): %s', ex, exc_info=app.debugstacktraces)
        
        iidset = set()
        cursor = app.mongodb.playstate.find({'iid':{'$ne':None}},
                                            {'_id':1, 'iid':1})
        while (yield cursor.fetch_next):
            playstate = cursor.next_object()
            iid = playstate['iid']
            if iid:
                iidset.add(iid)
        cursor.close()
        iidls = list(iidset)
        iidls.sort()  # Just for consistency
        for iid in iidls:
            awakening = app.ipool.notify_instance(iid)
            if awakening:
                ### figure out lastawake, put in local!
                app.log.info('Awakening instance %s', iid)
                instance = yield motor.Op(app.mongodb.instances.find_one,
                                          {'_id':iid})
                loctx = two.task.LocContext(None, wid=instance['wid'], scid=instance['scid'], iid=iid)
                task.resetticks()
                # If the instance/world has an on_wake property, run it.
                try:
                    awakenhook = yield two.symbols.find_symbol(app, loctx, 'on_wake')
                except:
                    awakenhook = None
                if awakenhook and twcommon.misc.is_typed_dict(awakenhook, 'code'):
                    ctx = two.evalctx.EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)
                    try:
                        yield ctx.eval(awakenhook, evaltype=EVALTYPE_RAW)
                    except Exception as ex:
                        task.log.warning('Caught exception (awakening instance): %s', ex, exc_info=app.debugstacktraces)

    @command('checkuninhabited', isserver=True, doeswrite=True)
    def cmd_checkuninhabited(app, task, cmd, stream):
        # Go through all the awake instances. Those that are still
        # inhabited, bump their timers. Those that have not been inhabited
        # for a while, put to sleep.
        # Go through the list of players who are in the world.
        iidset = set()
        cursor = app.mongodb.playstate.find({'iid':{'$ne':None}},
                                            {'_id':1, 'iid':1})
        while (yield cursor.fetch_next):
            playstate = cursor.next_object()
            iid = playstate['iid']
            if iid:
                iidset.add(iid)
        cursor.close()
        iidls = list(iidset)
        for iid in iidls:
            instance = app.ipool.get(iid)
            # These instances should always be in the pool, but we'll
            # do a safety check anyway.
            if instance:
                instance.lastinhabited = task.starttime
        tooold = task.starttime - app.ipool.UNINHABITED_LIMIT
        for instance in app.ipool.all():
            iid = instance.iid
            if instance.lastinhabited < tooold:
                app.log.info('Sleeping instance %s', iid)
                instance = yield motor.Op(app.mongodb.instances.find_one,
                                          {'_id':iid})
                loctx = two.task.LocContext(None, wid=instance['wid'], scid=instance['scid'], iid=iid)
                task.resetticks()
                # If the instance/world has an on_sleep property, run it.
                try:
                    sleephook = yield two.symbols.find_symbol(app, loctx, 'on_sleep')
                except:
                    sleephook = None
                if sleephook and twcommon.misc.is_typed_dict(sleephook, 'code'):
                    ctx = two.evalctx.EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)
                    try:
                        yield ctx.eval(sleephook, evaltype=EVALTYPE_RAW)
                    except Exception as ex:
                        task.log.warning('Caught exception (sleeping instance): %s', ex, exc_info=app.debugstacktraces)
                app.ipool.remove_instance(iid)
    
    @command('connect', isserver=True, noneedmongo=True)
    def cmd_connect(app, task, cmd, stream):
        assert stream is not None, 'Tweb connect command from no stream.'
        stream.write(wcproto.message(0, {'cmd':'connectok'}))

        # Accept any connections that tweb is holding.
        for connobj in cmd.connections:
            if not app.mongodb:
                # Reject the players.
                stream.write(wcproto.message(0, {'cmd':'playernotok', 'connid':connobj.connid, 'text':'The database is not available.'}))
                continue
            conn = app.playconns.add(connobj.connid, connobj.uid, connobj.email, stream)
            stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':conn.connid}))
            app.queue_command({'cmd':'connrefreshall', 'connid':conn.connid})
            app.log.info('Player %s has reconnected (uid %s)', conn.email, conn.uid)
            # But don't queue a portin command, because people are no more
            # likely to be in the void than usual.
        
        # Broadcast a message to the returned players.
        val = 'Server broadcast: Server has restarted!'
        stream.write(wcproto.message(0, {'cmd':'messageall', 'text':val}))

    @command('disconnect', isserver=True, noneedmongo=True)
    def cmd_disconnect(app, task, cmd, stream):
        for (connid, conn) in app.playconns.as_dict().items():
            if conn.twwcid == cmd.twwcid:
                try:
                    app.playconns.remove(connid)
                except:
                    pass
        app.log.warning('Tweb has disconnected; now %d connections remain', len(app.playconns.as_dict()))

    @command('checkdisconnected', isserver=True, doeswrite=True)
    def cmd_checkdisconnected(app, task, cmd, stream):
        # Construct a list of players who are in the world, but
        # disconnected.
        ls = []
        inworld = 0
        cursor = app.mongodb.playstate.find({'iid':{'$ne':None}},
                                            {'_id':1})
        while (yield cursor.fetch_next):
            playstate = cursor.next_object()
            conncount = app.playconns.count_for_uid(playstate['_id'])
            inworld += 1
            if not conncount:
                ls.append(playstate['_id'])
        cursor.close()

        app.log.info('checkdisconnected: %d players in world, %d are disconnected', inworld, len(ls))
        ### Keep a two-strikes list, so that players are knocked out after some minimum interval
        for uid in ls:
            app.queue_command({'cmd':'tovoid', 'uid':uid, 'portin':False})

    @command('tovoid', isserver=True, doeswrite=True)
    def cmd_tovoid(app, task, cmd, stream):
        # If portto is None, we'll wind up porting to the player's panic
        # location.
        portto = getattr(cmd, 'portto', None)
        
        task.write_event(cmd.uid, app.localize('action.portout')) # 'The world fades away.'
        others = yield task.find_locale_players(uid=cmd.uid, notself=True)
        if others:
            res = yield motor.Op(app.mongodb.players.find_one,
                                 {'_id':cmd.uid},
                                 {'name':1})
            playername = res['name']
            task.write_event(others, app.localize('action.oportout') % (playername,)) # '%s disappears.'
        # Move the player to the void.
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':cmd.uid},
                       {'$set':{'focus':None, 'iid':None, 'locid':None,
                                'portto':portto,
                                'lastlocid': None,
                                'lastmoved':task.starttime }})
        task.set_dirty(cmd.uid, DIRTY_FOCUS | DIRTY_LOCALE | DIRTY_WORLD | DIRTY_POPULACE)
        task.set_data_change( ('playstate', cmd.uid, 'iid') )
        task.set_data_change( ('playstate', cmd.uid, 'locid') )
        task.clear_loctx(cmd.uid)
        if cmd.portin:
            app.schedule_command({'cmd':'portin', 'uid':cmd.uid}, 1.5)
        
    @command('logplayerconntable', isserver=True, noneedmongo=True)
    def cmd_logplayerconntable(app, task, cmd, stream):
        app.playconns.dumplog()
        
    @command('timerevent', isserver=True, doeswrite=True)
    def cmd_timerevent(app, task, cmd, stream):
        iid = cmd.iid
        instance = app.ipool.get(iid)
        if not instance:
            raise ErrorMessageException('instance is not awake')
        instance = yield motor.Op(app.mongodb.instances.find_one,
                                  {'_id':iid})
        loctx = two.task.LocContext(None, wid=instance['wid'], scid=instance['scid'], iid=iid)
        func = cmd.func
        if twcommon.misc.is_typed_dict(func, 'code'):
            functype = EVALTYPE_RAW
        else:
            func = str(func)
            functype = EVALTYPE_CODE
        ctx = two.evalctx.EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)
        try:
            yield ctx.eval(func, evaltype=functype)
        except Exception as ex:
            task.log.warning('Caught exception (timer event): %s', ex, exc_info=app.debugstacktraces)
        
    @command('connrefreshall', isserver=True, doeswrite=True)
    def cmd_connrefreshall(app, task, cmd, stream):
        # Refresh one connection (not all the player's connections!)
        conn = app.playconns.get(cmd.connid)
        if not conn:
            return
        task.set_dirty(conn, DIRTY_ALL)
        app.queue_command({'cmd':'connupdateplist', 'connid':cmd.connid})
        app.queue_command({'cmd':'connupdatescopes', 'connid':cmd.connid})
        ### probably queue a connupdatefriends, too
    
    @command('connupdateplist', isserver=True)
    def cmd_connupdateplist(app, task, cmd, stream):
        # Re-send the player's portlist to one connection.
        conn = app.playconns.get(cmd.connid)
        if not conn:
            return
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':conn.uid},
                                {'plistid':1})
        if not player:
            return
        playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                   {'_id':conn.uid},
                                   {'iid':1})
        if not playstate:
            return
        plistid = player['plistid']
        iid = playstate['iid']
        cursor = app.mongodb.portals.find({'plistid':plistid})
        ls = []
        while (yield cursor.fetch_next):
            portal = cursor.next_object()
            ls.append(portal)
        cursor.close()
        map = {}
        for portal in ls:
            desc = yield two.execute.portal_description(app, portal, conn.uid, uidiid=iid, location=True, short=True)
            if desc:
                strid = str(portal['_id'])
                desc['portid'] = strid
                desc['listpos'] = portal.get('listpos', 0.0)
                map[strid] = desc
        conn.write({'cmd':'updateplist', 'clear': True, 'map':map})

    @command('connupdatescopes', isserver=True)
    def cmd_connupdatescopes(app, task, cmd, stream):
        # Re-send the player's available scope list to one connection.
        conn = app.playconns.get(cmd.connid)
        if not conn:
            return
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':conn.uid},
                                {'plistid':1, 'scid':1})
        if not player:
            return

        map = {}
        config = yield motor.Op(app.mongodb.config.find_one,
                                {'key':'globalscopeid'})
        scope = yield two.execute.scope_description(app, config['val'], conn.uid)
        if scope:
            map[scope['id']] = scope

        scope = yield two.execute.scope_description(app, player['scid'], conn.uid)
        if scope:
            map[scope['id']] = scope
            
        ### And any personal scopes you have access to
        ### And any group scopes you have access to

        conn.write({'cmd':'updatescopes', 'clear':True, 'map':map})

    @command('buildcopyportal', isserver=True, doeswrite=True)
    def cmd_buildcopyportal(app, task, cmd, stream):
        uid = ObjectId(cmd.uid)
        wid = ObjectId(cmd.wid)
        locid = ObjectId(cmd.locid)
        
        world = yield motor.Op(app.mongodb.worlds.find_one,
                                {'_id':wid})
        if not world:
            raise ErrorMessageException('buildcopyportal: no such world: %s' % (wid,))
        if world['creator'] != uid:
            raise ErrorMessageException('buildcopyportal: world not owned by player: %s' % (wid,))

        loc = yield motor.Op(app.mongodb.locations.find_one,
                             {'_id':locid})
        if not loc:
            raise ErrorMessageException('buildcopyportal: no such location: %s' % (locid,))

        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':uid},
                                {'scid':1, 'plistid':1})
        plistid = player['plistid']
        
        # This command comes from the build interface; the player is creating
        # a new link to his own world. We go with a personal-scope link,
        # unless the world is global-only.
        if world['instancing'] == 'shared':
            config = yield motor.Op(app.mongodb.config.find_one,
                                    {'key':'globalscopeid'})
            scid = config['val']
        else:
            scid = player['scid']

        portid = yield two.execute.create_portal_for_player(app, uid, plistid, wid, scid, locid)
        app.log.info('Build portal created: %s', portid)
        
    @command('notifydatachange', isserver=True, doeswrite=True)
    def cmd_notifydatachange(app, task, cmd, stream):
        ls = cmd.change
        # We may need to handle other data-key formats eventually. But
        # right now, it's all [db, wid, locid/uid, key] where db is
        # 'worldprop' or 'wplayerprop' and the id values may be None
        # or ObjectId.
        if type(ls[1]) is str:
            ls[1] = ObjectId(ls[1])
        if type(ls[2]) is str:
            ls[2] = ObjectId(ls[2])
        key = tuple(ls)
        app.log.info('Build change notification: %s', key)
        task.set_data_change(key)
        
    @command('playeropen', noneedmongo=True, preconnection=True)
    def cmd_playeropen(app, task, cmd, conn):
        assert conn is None, 'playeropen command with connection not None'
        connid = cmd._connid
        
        if not app.mongodb:
            # Reject the players anyhow.
            try:
                cmd._stream.write(wcproto.message(0, {'cmd':'playernotok', 'connid':connid, 'text':'The database is not available.'}))
            except:
                pass
            return
            
        conn = app.playconns.add(connid, cmd.uid, cmd.email, cmd._stream)
        cmd._stream.write(wcproto.message(0, {'cmd':'playerok', 'connid':connid}))
        app.queue_command({'cmd':'connrefreshall', 'connid':connid})
        app.log.info('Player %s has connected (uid %s)', conn.email, conn.uid)
        # If the player is in the void, put them somewhere.
        app.queue_command({'cmd':'portin', 'uid':conn.uid})

    @command('playerclose')
    def cmd_playerclose(app, task, cmd, conn):
        app.log.info('Player %s has disconnected (uid %s)', conn.email, conn.uid)
        try:
            app.playconns.remove(conn.connid)
        except Exception as ex:
            app.log.error('Failed to remove on playerclose %d: %s', conn.connid, ex)
    
    @command('portin', isserver=True, doeswrite=True)
    def cmd_portin(app, task, cmd, stream):
        # When a player is in the void, this command should come along
        # shortly thereafter and send them to a destination.
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':cmd.uid},
                                {'name':1, 'scid':1, 'plistid':1})
        playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                   {'_id':cmd.uid})
        if not player or not playstate:
            raise ErrorMessageException('Portin: no such player: %s' % (cmd.uid,))
        playername = player['name']
        if playstate.get('iid', None) and playstate.get('locid', None):
            app.log.info('Player %s is already in the world', playername)
            return
        # Figure out what destination was set. If none, default to the
        # player's chosen panic location. If none, try the start world.
        newloc = playstate.get('portto', None)
        if newloc:
            newwid = newloc['wid']
            newscid = newloc['scid']
            newlocid = newloc['locid']
        else:
            # Look through the player's list and find the preferred entry.
            plistid = player['plistid']
            res = yield motor.Op(app.mongodb.portals.find_one,
                                 {'plistid':plistid, 'preferred':True})
            if res:
                newwid = res['wid']
                newscid = res['scid']
                newlocid = res['locid']
            else:
                # Last hope: the start world.
                res = yield motor.Op(app.mongodb.config.find_one,
                                     {'key':'startworldloc'})
                lockey = res['val']
                res = yield motor.Op(app.mongodb.config.find_one,
                                     {'key':'startworldid'})
                newwid = res['val']
                newscid = player['scid']
                res = yield motor.Op(app.mongodb.locations.find_one,
                                     {'wid':newwid, 'key':lockey})
                newlocid = res['_id']
        app.log.debug('Player portin to %s, %s, %s', newwid, newscid, newlocid)
        
        instance = yield motor.Op(app.mongodb.instances.find_one,
                                  {'wid':newwid, 'scid':newscid})
        if instance:
            minaccess = instance.get('minaccess', ACC_VISITOR)
        else:
            minaccess = ACC_VISITOR
        if False: ### check minaccess against scope access!
            task.write_event(cmd.uid, app.localize('message.instance_no_access')) # 'You do not have access to this instance.'
            return

        # This is the one and only spot in the server code where a player
        # *enters* a new instance. It's also the place where instances
        # are created.
        
        if instance:
            newiid = instance['_id']
        else:
            newiid = yield motor.Op(app.mongodb.instances.insert,
                                    {'wid':newwid, 'scid':newscid})
            app.log.info('Created instance %s (world %s, scope %s)', newiid, newwid, newscid)
            # If the new instance has an on_init property, run it.
            loctx = two.task.LocContext(None, wid=newwid, scid=newscid, iid=newiid)
            task.resetticks()
            try:
                inithook = yield two.symbols.find_symbol(app, loctx, 'on_init')
            except:
                inithook = None
            if inithook and twcommon.misc.is_typed_dict(inithook, 'code'):
                ctx = two.evalctx.EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)
                try:
                    yield ctx.eval(inithook, evaltype=EVALTYPE_RAW)
                except Exception as ex:
                    task.log.warning('Caught exception (initing instance): %s', ex, exc_info=app.debugstacktraces)

        awakening = app.ipool.notify_instance(newiid)
        if awakening:
            ### figure out lastawake, put in local!
            app.log.info('Awakening instance %s', newiid)
            loctx = two.task.LocContext(None, wid=newwid, scid=newscid, iid=newiid)
            task.resetticks()
            # If the instance/world has an on_wake property, run it.
            try:
                awakenhook = yield two.symbols.find_symbol(app, loctx, 'on_wake')
            except:
                awakenhook = None
            if awakenhook and twcommon.misc.is_typed_dict(awakenhook, 'code'):
                ctx = two.evalctx.EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)
                try:
                    yield ctx.eval(awakenhook, evaltype=EVALTYPE_RAW)
                except Exception as ex:
                    task.log.warning('Caught exception (awakening instance): %s', ex, exc_info=app.debugstacktraces)

        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':cmd.uid},
                       {'$set':{'iid':newiid,
                                'locid':newlocid,
                                'focus':None,
                                'lastmoved': task.starttime,
                                'lastlocid': None,
                                'portto':None }})
        task.set_dirty(cmd.uid, DIRTY_FOCUS | DIRTY_LOCALE | DIRTY_WORLD | DIRTY_POPULACE)
        task.set_data_change( ('playstate', cmd.uid, 'iid') )
        task.set_data_change( ('playstate', cmd.uid, 'locid') )
        task.clear_loctx(cmd.uid)
        
        # We set everybody in the destination room DIRTY_POPULACE.
        others = yield task.find_locale_players(uid=cmd.uid, notself=True)
        if others:
            task.set_dirty(others, DIRTY_POPULACE)
            task.write_event(others, app.localize('action.oportin') % (playername,)) # '%s appears.'
        task.write_event(cmd.uid, app.localize('action.portin')) # 'You are somewhere new.'
        
    @command('uiprefs')
    def cmd_uiprefs(app, task, cmd, conn):
        # Could we handle this in tweb? I guess, if we cared.
        # Note that this command isn't marked writable, because it only
        # writes to an obscure collection that never affects anybody's
        # display.
        for (key, val) in cmd.map.__dict__.items():
            res = yield motor.Op(app.mongodb.playprefs.update,
                                 {'uid':conn.uid, 'key':key},
                                 {'uid':conn.uid, 'key':key, 'val':val},
                                 upsert=True)

    @command('meta')
    def cmd_meta(app, task, cmd, conn):
        ls = cmd.text.split()
        if not ls:
            raise MessageException('You must supply a command after the slash. Try \u201C/help\u201D.')
        key = ls[0]
        newcmd = Command.all_commands.get('meta_'+key)
        if not newcmd:
            raise MessageException('Command \u201C/%s\u201D not understood. Try \u201C/help\u201D.' % (key,))
        app.queue_command({'cmd':newcmd.name, 'args':ls[1:]}, connid=conn.connid)

    @command('meta_help')
    def cmd_meta_help(app, task, cmd, conn):
        conn.write({'cmd':'message', 'text':'Seltani quick help:'})
        conn.write({'cmd':'message', 'text':'Type to speak out loud (to nearby players). A message that begins with a colon (":dance") will appear as a pose ("Belford dances").'})
        conn.write({'cmd':'message', 'text':'Other commands:'})
        conn.write({'cmd':'message', 'text':'/refresh: Reload the current location. (Or you can use your browser\'s refresh button.)'})
        conn.write({'cmd':'message', 'text':'/panic: Jump to your selected panic location. \xA0 /panicstart: Jump back to the start world.'})
        return

    @command('meta_refresh')
    def cmd_meta_refresh(app, task, cmd, conn):
        conn.write({'cmd':'message', 'text':'Refreshing display...'})
        app.queue_command({'cmd':'connrefreshall', 'connid':conn.connid})

    @command('meta_scopeaccess', restrict='debug')
    def cmd_meta_scopeaccess(app, task, cmd, conn):
        loctx = yield task.get_loctx(conn.uid)
        level = yield two.execute.scope_access_level(app, conn.uid, loctx.wid, loctx.scid)
        val = 'Access level to current scope: %s' % (level,)
        conn.write({'cmd':'message', 'text':val})        

    @command('meta_actionmaps', restrict='debug')
    def cmd_meta_actionmaps(app, task, cmd, conn):
        val = 'Locale action map: %s' % (conn.localeactions,)
        conn.write({'cmd':'message', 'text':val})
        val = 'Populace action map: %s' % (conn.populaceactions,)
        conn.write({'cmd':'message', 'text':val})
        val = 'Focus action map: %s' % (conn.focusactions,)
        conn.write({'cmd':'message', 'text':val})

    @command('meta_dependencies', restrict='debug')
    def cmd_meta_dependencies(app, task, cmd, conn):
        val = 'Locale dependency set: %s' % (conn.localedependencies,)
        conn.write({'cmd':'message', 'text':val})
        val = 'Populace dependency set: %s' % (conn.populacedependencies,)
        conn.write({'cmd':'message', 'text':val})
        val = 'Focus dependency set: %s' % (conn.focusdependencies,)
        conn.write({'cmd':'message', 'text':val})
        
    @command('meta_showipool', restrict='debug')
    def cmd_meta_showipool(app, task, cmd, conn):
        ls = app.ipool.all()
        instls = ', '.join([ str(val.iid) for val in ls ])
        raise MessageException('Instance pool has %d awake instances: %s' % (len(ls), instls))

    @command('meta_panic')
    def cmd_meta_panic(app, task, cmd, conn):
        app.queue_command({'cmd':'tovoid', 'uid':conn.uid, 'portin':True})

    @command('meta_panicstart')
    def cmd_meta_panicstart(app, task, cmd, conn):
        app.queue_command({'cmd':'portstart'}, connid=task.connid, twwcid=task.twwcid)

    @command('meta_getprop', restrict='creator')
    def cmd_meta_getprop(app, task, cmd, conn):
        if len(cmd.args) != 1:
            raise MessageException('Usage: /getprop key')
        origkey = cmd.args[0]
        key = origkey
        playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                   {'_id':conn.uid},
                                   {'iid':1, 'locid':1})
        iid = playstate['iid']
        if not iid:
            # In the void, there should be no actions.
            raise ErrorMessageException('You are between worlds.')
        instance = yield motor.Op(app.mongodb.instances.find_one,
                                  {'_id':iid})
        wid = instance['wid']
        locid = playstate['locid']
        if '.' in key:
            lockey, dummy, key = key.partition('.')
            if not lockey:
                locid = None
            elif lockey == '@':
                locid = '@'
            else:
                location = yield motor.Op(app.mongodb.locations.find_one,
                                          {'wid':wid, 'key':lockey},
                                          {'_id':1})
                if not location:
                    raise ErrorMessageException('No such location: %s' % (lockey,))
                locid = location['_id']
        if locid == '@':
            res = yield motor.Op(app.mongodb.iplayerprop.find_one,
                             {'iid':iid, 'uid':conn.uid, 'key':key})
            if res:
                raise MessageException('Player instance property: %s = %s' % (key, repr(res['val'])))
            res = yield motor.Op(app.mongodb.wplayerprop.find_one,
                                 {'wid':wid, 'uid':conn.uid, 'key':key})
            if res:
                raise MessageException('Player world property: %s = %s' % (key, repr(res['val'])))
            raise MessageException('Player instance/world property not set: %s' % (key,))
        res = yield motor.Op(app.mongodb.instanceprop.find_one,
                             {'iid':iid, 'locid':locid, 'key':key})
        if res:
            raise MessageException('Instance property: %s = %s' % (origkey, repr(res['val'])))
        res = yield motor.Op(app.mongodb.worldprop.find_one,
                                 {'wid':wid, 'locid':locid, 'key':key})
        if res:
            raise MessageException('World property: %s = %s' % (origkey, repr(res['val'])))
        raise MessageException('Instance/world property not set: %s' % (origkey,))

    @command('meta_delprop', restrict='creator', doeswrite=True)
    def cmd_meta_delprop(app, task, cmd, conn):
        if len(cmd.args) != 1:
            raise MessageException('Usage: /delprop key')
        origkey = cmd.args[0]
        key = origkey
        playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                   {'_id':conn.uid},
                                   {'iid':1, 'locid':1})
        iid = playstate['iid']
        if not iid:
            # In the void, there should be no actions.
            raise ErrorMessageException('You are between worlds.')
        instance = yield motor.Op(app.mongodb.instances.find_one,
                                  {'_id':iid})
        wid = instance['wid']
        locid = playstate['locid']
        if '.' in key:
            lockey, dummy, key = key.partition('.')
            if not lockey:
                locid = None
            elif lockey == '@':
                locid = '@'
            else:
                location = yield motor.Op(app.mongodb.locations.find_one,
                                          {'wid':wid, 'key':lockey},
                                          {'_id':1})
                if not location:
                    raise ErrorMessageException('No such location: %s' % (lockey,))
                locid = location['_id']
        if locid == '@':
            res = yield motor.Op(app.mongodb.iplayerprop.find_one,
                             {'iid':iid, 'uid':conn.uid, 'key':key})
            if not res:
                raise MessageException('Player instance property not set: %s' % (key,))
            yield motor.Op(app.mongodb.iplayerprop.remove,
                       {'iid':iid, 'uid':conn.uid, 'key':key})
            task.set_data_change( ('iplayerprop', iid, conn.uid, key) )
            raise MessageException('Player instance property deleted: %s' % (key,))
        res = yield motor.Op(app.mongodb.instanceprop.find_one,
                             {'iid':iid, 'locid':locid, 'key':key})
        if not res:
            raise MessageException('Instance property not set: %s' % (origkey,))
        yield motor.Op(app.mongodb.instanceprop.remove,
                       {'iid':iid, 'locid':locid, 'key':key})
        task.set_data_change( ('instanceprop', iid, locid, key) )
        raise MessageException('Instance property deleted: %s' % (origkey,))
                
    @command('meta_setprop', restrict='creator', doeswrite=True)
    def cmd_meta_setprop(app, task, cmd, conn):
        if len(cmd.args) == 0:
            raise MessageException('Usage: /setprop key val')
        origkey = cmd.args[0]
        key = origkey
        newval = ' '.join(cmd.args[1:])
        try:
            newval = ast.literal_eval(newval)
            # We test-encode the new value to bson, so that we can be strict
            # and catch errors.
            dummy = bson.BSON.encode({'val':newval}, check_keys=True)
        except Exception as ex:
            raise ErrorMessageException('Invalid property value: %s (%s)' % (newval, ex))
        playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                   {'_id':conn.uid},
                                   {'iid':1, 'locid':1})
        iid = playstate['iid']
        if not iid:
            # In the void, there should be no actions.
            raise ErrorMessageException('You are between worlds.')
        instance = yield motor.Op(app.mongodb.instances.find_one,
                                  {'_id':iid})
        wid = instance['wid']
        locid = playstate['locid']
        if '.' in key:
            lockey, dummy, key = key.partition('.')
            if not lockey:
                locid = None
            elif lockey == '@':
                locid = '@'
            else:
                location = yield motor.Op(app.mongodb.locations.find_one,
                                          {'wid':wid, 'key':lockey},
                                          {'_id':1})
                if not location:
                    raise ErrorMessageException('No such location: %s' % (lockey,))
                locid = location['_id']
        if not key.isidentifier():
            ### Permits Unicode identifiers, but whatever
            raise ErrorMessageException('Symbol assignment to invalid key: %s' % (key,))
        if locid == '@':
            yield motor.Op(app.mongodb.iplayerprop.update,
                       {'iid':iid, 'uid':conn.uid, 'key':key},
                       {'iid':iid, 'uid':conn.uid, 'key':key, 'val':newval},
                       upsert=True)
            task.set_data_change( ('iplayerprop', iid, conn.uid, key) )
            raise MessageException('Player instance property set: %s = %s' % (key, repr(newval)))            
        yield motor.Op(app.mongodb.instanceprop.update,
                       {'iid':iid, 'locid':locid, 'key':key},
                       {'iid':iid, 'locid':locid, 'key':key, 'val':newval},
                       upsert=True)
        task.set_data_change( ('instanceprop', iid, locid, key) )
        raise MessageException('Instance property set: %s = %s' % (origkey, repr(newval)))
                
    @command('meta_move', restrict='creator', doeswrite=True)
    def cmd_meta_move(app, task, cmd, conn):
        if len(cmd.args) != 1:
            raise MessageException('Usage: /move location-key')
        lockey = cmd.args[0]

        loctx = yield task.get_loctx(conn.uid)
        location = yield motor.Op(app.mongodb.locations.find_one,
                                  {'wid':loctx.wid, 'key':lockey},
                                  {'_id':1})
        if not location:
            raise ErrorMessageException('No such location: %s' % (lockey,))
        ctx = two.evalctx.EvalPropContext(task, loctx=loctx, level=LEVEL_EXECUTE)

        yield ctx.perform_move(location['_id'], 'Your location changes.', False, None, False, None, False)
        
    @command('meta_holler', restrict='admin')
    def cmd_meta_holler(app, task, cmd, conn):
        val = 'Admin broadcast: ' + (' '.join(cmd.args))
        for stream in app.webconns.all():
            stream.write(wcproto.message(0, {'cmd':'messageall', 'text':val}))

    @command('meta_shutdown', restrict='admin')
    def cmd_meta_shutdown(app, task, cmd, conn):
        app.queue_command({'cmd':'shutdownprocess'})
        
    @command('meta_debugstacktraces', restrict='admin')
    def cmd_meta_debugstacktraces(app, task, cmd, conn):
        app.debugstacktraces = not app.debugstacktraces
        raise MessageException('debugstacktraces now %s' % (app.debugstacktraces,))
        
    @command('portstart', doeswrite=True)
    def cmd_portstart(app, task, cmd, conn):
        # Fling the player back to the start world. (Not necessarily the
        # same as a panic or initial login!)
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':conn.uid},
                                {'scid':1})
        res = yield motor.Op(app.mongodb.config.find_one,
                             {'key':'startworldloc'})
        lockey = res['val']
        res = yield motor.Op(app.mongodb.config.find_one,
                             {'key':'startworldid'})
        newwid = res['val']
        newscid = player['scid']
        res = yield motor.Op(app.mongodb.locations.find_one,
                             {'wid':newwid, 'key':lockey})
        newlocid = res['_id']
        
        app.queue_command({'cmd':'tovoid', 'uid':conn.uid, 'portin':True,
                           'portto':{'wid':newwid, 'scid':newscid, 'locid':newlocid}})
        
    @command('plistselect', doeswrite=True)
    def cmd_plistselect(app, task, cmd, conn):
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':conn.uid},
                                {'plistid':1})
        portal = yield motor.Op(app.mongodb.portals.find_one,
                                {'_id':ObjectId(cmd.portid), 'plistid':player['plistid']})
        if not portal:
            raise ErrorMessageException('No such portal in your collection.')
        focusobj = ['portal', portal['_id'], None, None]
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':conn.uid},
                       {'$set':{'focus':focusobj}})
        task.set_dirty(conn.uid, DIRTY_FOCUS)

        
    @command('setpreferredportal')
    def cmd_setpreferredportal(app, task, cmd, conn):
        # This updates the database, but not in a way that notifies anybody.
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':conn.uid},
                                {'plistid':1})
        portal = yield motor.Op(app.mongodb.portals.find_one,
                                {'_id':ObjectId(cmd.portid), 'plistid':player['plistid']})
        if not portal:
            raise ErrorMessageException('No such portal in your collection.')
        # Remove all preferred flags for this player
        yield motor.Op(app.mongodb.portals.update,
                       {'plistid':player['plistid'], 'preferred':True},
                       {'$unset': {'preferred':1}},
                       multi=True)
        # And set the new one
        yield motor.Op(app.mongodb.portals.update,
                       {'_id':portal['_id']},
                       {'$set': {'preferred':True}})
        desc = yield two.execute.portal_description(app, portal, conn.uid, location=True)
        raise MessageException(app.localize('message.panic_portal_set') % (desc['world'], desc['location'])) # 'Panic portal set to %s, %s.'
        
    @command('deleteownportal', doeswrite=True)
    def cmd_deleteownportal(app, task, cmd, conn):
        player = yield motor.Op(app.mongodb.players.find_one,
                                {'_id':conn.uid},
                                {'plistid':1})
        portal = yield motor.Op(app.mongodb.portals.find_one,
                                {'_id':ObjectId(cmd.portid), 'plistid':player['plistid']})
        if not portal:
            raise ErrorMessageException('No such portal in your collection.')
        yield motor.Op(app.mongodb.portals.remove,
                       {'_id':portal['_id']})
        map = { str(portal['_id']):False }
        conn.write({'cmd':'updateplist', 'map':map})
        conn.write({'cmd':'message', 'text':app.localize('message.delete_own_portal_ok')}) # 'You remove the portal from your collection.'
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':conn.uid},
                       {'$set':{'focus':None}})
        task.set_dirty(conn.uid, DIRTY_FOCUS)
        
    @command('selfdesc', doeswrite=True)
    def cmd_selfdesc(app, task, cmd, conn):
        if getattr(cmd, 'pronoun', None):
            if cmd.pronoun not in ("he", "she", "it", "they", "name"):
                raise ErrorMessageException('Invalid pronoun: %s' % (cmd.pronoun,))
            yield motor.Op(app.mongodb.players.update,
                           {'_id':conn.uid},
                           {'$set': {'pronoun':cmd.pronoun}})
            task.set_data_change( ('players', conn.uid, 'pronoun') )
        if getattr(cmd, 'desc', None):
            val = str(cmd.desc)
            if len(val) > twcommon.misc.MAX_DESCLINE_LENGTH:
                val = val[0:twcommon.misc.MAX_DESCLINE_LENGTH]
            yield motor.Op(app.mongodb.players.update,
                           {'_id':conn.uid},
                           {'$set': {'desc':val}})
            task.set_data_change( ('players', conn.uid, 'desc') )
        
    @command('say')
    def cmd_say(app, task, cmd, conn):
        res = yield motor.Op(app.mongodb.players.find_one,
                             {'_id':conn.uid},
                             {'name':1})
        playername = res['name']
        if cmd.text.endswith('?'):
            (say, says) = ('ask', 'asks')
        elif cmd.text.endswith('!'):
            (say, says) = ('exclaim', 'exclaims')
        else:
            (say, says) = ('say', 'says')
        val = 'You %s, \u201C%s\u201D' % (say, cmd.text,)
        task.write_event(conn.uid, val)
        others = yield task.find_locale_players(notself=True)
        if others:
            oval = '%s %s, \u201C%s\u201D' % (playername, says, cmd.text,)
            task.write_event(others, oval)

    @command('pose')
    def cmd_pose(app, task, cmd, conn):
        res = yield motor.Op(app.mongodb.players.find_one,
                             {'_id':conn.uid},
                             {'name':1})
        playername = res['name']
        val = '%s %s' % (playername, cmd.text,)
        everyone = yield task.find_locale_players()
        task.write_event(everyone, val)

    @command('action', doeswrite=True)
    def cmd_action(app, task, cmd, conn):
        # First check that the action is one currently visible to the player.
        action = conn.localeactions.get(cmd.action)
        if action is None:
            action = conn.focusactions.get(cmd.action)
        if action is None:
            action = conn.populaceactions.get(cmd.action)
        if action is None:
            raise ErrorMessageException('Action is not available.')
        res = yield two.execute.perform_action(task, cmd, conn, action)
        
    @command('dropfocus', doeswrite=True)
    def cmd_dropfocus(app, task, cmd, conn):
        playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                   {'_id':conn.uid},
                                   {'focus':1})
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':conn.uid},
                       {'$set':{'focus':None}})
        task.set_dirty(conn.uid, DIRTY_FOCUS)
        
    return Command.all_commands

# Late imports, to avoid circularity
import two.execute
import two.evalctx
import two.task
from two.evalctx import LEVEL_EXECUTE
from two.evalctx import EVALTYPE_RAW, EVALTYPE_CODE
from two.task import DIRTY_ALL, DIRTY_WORLD, DIRTY_LOCALE, DIRTY_POPULACE, DIRTY_FOCUS
from twcommon.access import ACC_VISITOR
