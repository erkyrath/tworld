import types
import errno
import socket

import tornado.ioloop
import tornado.iostream

from twcommon import wcproto

class WebConnectionTable(object):
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = self.app.log

        self.ioloop = None
        self.listensock = None
        self.map = {}  # maps twwcids to IOStreams (normally just one)

    def get(self, twwcid):
        return self.map.get(twwcid, None)

    def listen(self):
        self.ioloop = tornado.ioloop.IOLoop.current()
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.listensock = sock
        #sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,
            (sock.getsockopt (socket.SOL_SOCKET, socket.SO_REUSEADDR) | 1))
        sock.setblocking(0)
        sock.bind( ('localhost', self.app.opts.tworld_port) )
        sock.listen(32)
        
        self.ioloop.add_handler(
            sock.fileno(),
            self.listen_ready,
            tornado.ioloop.IOLoop.READ)
        
        self.log.info('Listening on port %d', self.app.opts.tworld_port)

    def listen_ready(self, fd, events):
        while True:
            sock = None
            try:
                (sock, addr) = self.listensock.accept()
                (host, port) = addr
            except socket.error as ex:
                if ex.args[0] not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                return
            
            sock.setblocking(0)
            
            stream = WebConnIOStream(self, sock, host)
            assert stream.twwcid not in self.map, 'WebConn ID is already in use!'
            self.map[stream.twwcid] = stream
            self.log.info('Accepted: %s (now %d connected)', stream, len(self.map))

            stream.read_until_close(stream.twclose, stream.twread)

class WebConnIOStream(tornado.iostream.IOStream):
    # Counter for generating twwcid values. These are only used internally
    # as dict keys -- we don't share them with tweb.
    counter = 1
    
    def __init__(self, table, socket, host):
        tornado.iostream.IOStream.__init__(self, socket)
        self.twhost = host
        self.twtable = table
        self.twbuffer = bytearray()
        self.twwcid = WebConnIOStream.counter
        WebConnIOStream.counter += 1

    def __repr__(self):
        return '<WebConnIOStream %d (%s)>' % (self.twwcid, self.twhost,)
        
    def twread(self, dat):
        if not self.twtable:
            return  # must have already closed
        self.twbuffer.extend(dat)
        while True:
            # This slices a chunk off the buffer and returns it, if a
            # complete chunk is available.
            try:
                tup = wcproto.check_buffer(self.twbuffer, namespace=True)
                if not tup:
                    return
                (connid, raw, obj) = tup
                self.twtable.app.queue_command(obj, connid, self.twwcid)
            except Exception as ex:
                self.twtable.log.info('Malformed message: %s', ex)

    def twclose(self, dat):
        try:
            self.twtable.map.pop(self.twwcid, None)
            # Say goodbye to all connections on this stream!
            # But we do this as a queued command. Until it comes around,
            # we might see some write failures.
            obj = types.SimpleNamespace(cmd='disconnect', twwcid=self.twwcid)
            self.twtable.app.queue_command(obj, 0, 0)
        except:
            pass
        self.twtable.log.error('Closed: %s', self)
        self.twbuffer = None
        self.twtable = None
        self.twwcid = None
        
