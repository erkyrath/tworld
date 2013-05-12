
import tornado.gen
import motor

from twcommon import wcproto
from twcommon.excepts import MessageException, ErrorMessageException

import two.execute
from two.task import DIRTY_ALL, DIRTY_LOCALE, DIRTY_FOCUS

class Command:
    # As commands are defined with the @command decorator, they are stuffed
    # in this dict.
    all_commands = {}

    def __init__(self, name, func, isserver=False, noneedmongo=False, preconnection=False, doeswrite=False):
        self.name = name
        self.func = tornado.gen.coroutine(func)
        self.isserver = isserver
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
            app.queue_command({'cmd':'refreshconn', 'connid':conn.connid})
            app.log.info('Player %s has reconnected (uid %s)', conn.email, conn.uid)

    @command('disconnect', isserver=True, noneedmongo=True)
    def cmd_disconnect(app, task, cmd, stream):
        for (connid, conn) in app.playconns.as_dict().items():
            if conn.twwcid == cmd.twwcid:
                try:
                    app.playconns.remove(connid)
                except:
                    pass
        app.log.warning('Tweb has disconnected; now %d connections remain', len(app.playconns.as_dict()))
    
    @command('logplayerconntable', isserver=True, noneedmongo=True)
    def cmd_logplayerconntable(app, task, cmd, stream):
        app.playconns.dumplog()
        
    @command('refreshconn', isserver=True, doeswrite=True)
    def cmd_refreshconn(app, task, cmd, stream):
        # Refresh one connection (not all the player's connections!)
        ### Probably oughta be a player command, not a server command.
        conn = app.playconns.get(cmd.connid)
        task.set_dirty(conn, DIRTY_ALL)
    
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
        app.queue_command({'cmd':'refreshconn', 'connid':connid})
        app.log.info('Player %s has connected (uid %s)', conn.email, conn.uid)

    @command('playerclose')
    def cmd_playerclose(app, task, cmd, conn):
        app.log.info('Player %s has disconnected (uid %s)', conn.email, conn.uid)
        try:
            app.playconns.remove(conn.connid)
        except Exception as ex:
            app.log.error('Failed to remove on playerclose %d: %s', conn.connid, ex)
    
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
        cmd._args = ls[1:]
        res = yield newcmd.func(app, task, cmd, conn)
        return res

    @command('meta_help')
    def cmd_meta_help(app, task, cmd, conn):
        raise MessageException('No slash commands are currently implemented.')

    @command('meta_refresh')
    def cmd_meta_refresh(app, task, cmd, conn):
        conn.write({'cmd':'message', 'text':'Refreshing display...'})
        app.queue_command({'cmd':'refreshconn', 'connid':conn.connid})
        
    @command('meta_actionmaps')
    def cmd_meta_actionmaps(app, task, cmd, conn):
        ### debug
        val = 'Locale action map: %s' % (conn.localeactions,)
        conn.write({'cmd':'message', 'text':val})
        val = 'Focus action map: %s' % (conn.focusactions,)
        conn.write({'cmd':'message', 'text':val})

    @command('meta_dependencies')
    def cmd_meta_dependencies(app, task, cmd, conn):
        ### debug
        val = 'Locale dependency set: %s' % (conn.localedependencies,)
        conn.write({'cmd':'message', 'text':val})
        val = 'Focus dependency set: %s' % (conn.focusdependencies,)
        conn.write({'cmd':'message', 'text':val})
        val = 'Populace dependency set: %s' % (conn.populacedependencies,)
        conn.write({'cmd':'message', 'text':val})
        
    @command('meta_exception')
    def cmd_meta_exception(app, task, cmd, conn):
        ### debug
        raise Exception('You asked for an exception.')

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
        oval = '%s %s, \u201C%s\u201D' % (playername, says, cmd.text,)
        for oconn in app.playconns.all():
            ### same location! and use task.write_event!
            if conn.uid == oconn.uid:
                oconn.write({'cmd':'event', 'text':val})
            else:
                oconn.write({'cmd':'event', 'text':oval})

    @command('pose')
    def cmd_pose(app, task, cmd, conn):
        res = yield motor.Op(app.mongodb.players.find_one,
                             {'_id':conn.uid},
                             {'name':1})
        playername = res['name']
        val = '%s %s' % (playername, cmd.text,)
        for oconn in app.playconns.all():
            ### same location! and use task.write_event!
            oconn.write({'cmd':'event', 'text':val})

    @command('action', doeswrite=True)
    def cmd_action(app, task, cmd, conn):
        # First check that the action is one currently visible to the player.
        action = conn.localeactions.get(cmd.action)
        if action is None:
            action = conn.focusactions.get(cmd.action)
        if action is None:
            raise ErrorMessageException('Action is not available.')
        res = yield two.execute.perform_action(app, task, conn, action)
        
    @command('dropfocus', doeswrite=True)
    def cmd_dropfocus(app, task, cmd, conn):
        playstate = yield motor.Op(app.mongodb.playstate.find_one,
                                   {'_id':conn.uid},
                                   {'focus':1})
        app.log.info('### playstate: %s', playstate)
        yield motor.Op(app.mongodb.playstate.update,
                       {'_id':conn.uid},
                       {'$set':{'focus':None}})
        task.set_dirty(conn.uid, DIRTY_FOCUS)
        
    return Command.all_commands
