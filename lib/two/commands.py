
import tornado.gen
import motor

from twcommon import wcproto
from twcommon.excepts import MessageException, ErrorMessageException

import two.describe

class Command:
    # As commands are defined with the @command decorator, they are stuffed
    # in this dict.
    all_commands = {}

    def __init__(self, name, func, isserver=False, noneedmongo=False, preconnection=False):
        self.name = name
        self.func = tornado.gen.coroutine(func)
        self.isserver = isserver
        self.noneedmongo = noneedmongo
        self.preconnection = preconnection
        
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

    Note that the third argument will be a IOStream for server commands,
    but a PlayerConnection for player commands. Never the twain shall
    meet.

    These functions wind up as entries in the Command.all_commands dict.
    The arguments to @command wind up as properties of the Command object
    that wraps the function. Oh, and the function is always a
    tornado.gen.coroutine -- you don't need to declare that.
    """

    @command('connect', isserver=True, noneedmongo=True)
    def cmd_connect(app, cmd, stream):
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
    def cmd_disconnect(app, cmd, stream):
        for (connid, conn) in app.playconns.as_dict().items():
            if conn.twwcid == cmd.twwcid:
                try:
                    app.playconns.remove(connid)
                except:
                    pass
        app.log.warning('Tweb has disconnected; now %d connections remain', len(app.playconns.as_dict()))
    
    @command('logplayerconntable', isserver=True, noneedmongo=True)
    def cmd_logplayerconntable(app, cmd, stream):
        app.playconns.dumplog()
        
    @command('refreshconn', isserver=True)
    def cmd_refreshconn(app, cmd, stream):
        # Refresh one connection (not all the player's connections!)
        conn = app.playconns.get(cmd.connid)
        yield two.describe.generate_locale(app, conn)
    
    @command('playeropen', noneedmongo=True, preconnection=True)
    def cmd_playeropen(app, cmd, conn):
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
    def cmd_playerclose(app, cmd, conn):
        app.log.info('Player %s has disconnected (uid %s)', conn.email, conn.uid)
        try:
            app.playconns.remove(conn.connid)
        except Exception as ex:
            app.log.error('Failed to remove on playerclose %d: %s', conn.connid, ex)
    
    @command('uiprefs')
    def cmd_uiprefs(app, cmd, conn):
        # Could we handle this in tweb? I guess, if we cared.
        for (key, val) in cmd.map.__dict__.items():
            res = yield motor.Op(app.mongodb.playprefs.update,
                                 {'uid':conn.uid, 'key':key},
                                 {'uid':conn.uid, 'key':key, 'val':val},
                                 upsert=True)

    @command('meta')
    def cmd_meta(app, cmd, conn):
        ls = cmd.text.split()
        if not ls:
            raise MessageException('You must supply a command after the slash. Try \u201C/help\u201D.')
        key = ls[0]
        newcmd = Command.all_commands.get('meta_'+key)
        if not newcmd:
            raise MessageException('Command \u201C/%s\u201D not understood. Try \u201C/help\u201D.' % (key,))
        cmd._args = ls[1:]
        res = yield newcmd.func(app, cmd, conn)
        return res

    @command('meta_help')
    def cmd_meta_help(app, cmd, conn):
        raise MessageException('No slash commands are currently implemented.')

    @command('meta_refresh')
    def cmd_meta_refresh(app, cmd, conn):
        app.queue_command({'cmd':'refreshconn', 'connid':conn.connid})
        
    @command('say')
    def cmd_say(app, cmd, conn):
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
        for oconn in app.playconns.all():
            if conn.uid == oconn.uid:
                val = 'You %s, \u201C%s\u201D' % (say, cmd.text,)
            else:
                val = '%s %s, \u201C%s\u201D' % (playername, says, cmd.text,)
            oconn.write({'cmd':'event', 'text':val})

    @command('pose')
    def cmd_pose(app, cmd, conn):
        res = yield motor.Op(app.mongodb.players.find_one,
                             {'_id':conn.uid},
                             {'name':1})
        playername = res['name']
        val = '%s %s' % (playername, cmd.text,)
        for oconn in app.playconns.all():
            oconn.write({'cmd':'event', 'text':val})

    return Command.all_commands
