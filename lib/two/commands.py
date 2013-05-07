
import tornado.gen
import motor

from twcommon import wcproto

# As commands are defined with the @command decorator, they are stuffed
# in here.
all_commands = {}

class Command:
    def __init__(self, name, func, isserver=False, needsmongo=True):
        self.name = name
        self.func = tornado.gen.coroutine(func)
        self.isserver = isserver
        self.needsmongo = needsmongo
        
    def __repr__(self):
        return '<Command "%s">' % (self.name,)


def command(name, isserver=False, needsmongo=True):
    """Decorator.
    """
    def wrap(func):
        cmd = Command(name, func, isserver=isserver, needsmongo=needsmongo)
        if name in all_commands:
            raise Exception('Command name defined twice: "%s"', name)
        all_commands[name] = cmd
        return cmd
    return wrap

def define_commands():
    """
    Define all the commands which will be used by the server. Return them
    in a dict.
    """

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
            try:
                oconn.stream.write(wcproto.message(oconn.connid, {'cmd':'event', 'text':val}))
            except Exception as ex:
                app.log.error('Unable to write to %d: %s', oconn.connid, ex)

    return all_commands
