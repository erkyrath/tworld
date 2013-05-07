
import tornado.gen
import motor

from twcommon import wcproto

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


def command(name, isserver=False, noneedmongo=False, preconnection=False):
    """Decorator.
    """
    def wrap(func):
        cmd = Command(name, func, isserver=isserver, noneedmongo=noneedmongo, preconnection=preconnection)
        if name in Command.all_commands:
            raise Exception('Command name defined twice: "%s"', name)
        Command.all_commands[name] = cmd
        return cmd
    return wrap

def define_commands():
    """
    Define all the commands which will be used by the server. Return them
    in a dict.
    """

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
        app.queue_command({'cmd':'refreshconn', 'connid':connid}, 0, 0)
        app.log.info('Player %s has connected (uid %s)', conn.email, conn.uid)
        return str(conn) ###

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

    @command('say')
    def cmd_say(app, cmd, conn):
        res = yield motor.Op(app.mongodb.players.find_one,
                             {'_id':conn.uid},
                             {'name':1})
        playername = res['name']
        for oconn in app.playconns.all():
            if conn.uid == oconn.uid:
                val = 'You say, \u201C%s\u201D' % (cmd.text,)
            else:
                val = '%s says, \u201C%s\u201D' % (playername, cmd.text,)
            oconn.write({'cmd':'event', 'text':val})

    return Command.all_commands
