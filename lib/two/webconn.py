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
        self.webconns = set()   # set of IOStreams (normally just one)

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
            self.webconns.add(stream)
            self.log.info('Accepted: %s (now %d connected)', stream, len(self.webconns))

            stream.read_until_close(stream.twclose, stream.twread)

class WebConnIOStream(tornado.iostream.IOStream):
    def __init__(self, table, socket, host):
        tornado.iostream.IOStream.__init__(self, socket)
        self.twhost = host
        self.twtable = table
        self.twbuffer = bytearray()

    def __repr__(self):
        return '<WebConnIOStream (%s)>' % (self.twhost,)
        
    def twread(self, dat):
        self.twtable.log.info('### stream_read %s', dat)
        self.twbuffer.extend(dat)
        while True:
            # This slices a chunk off the buffer and returns it, if a
            # complete chunk is available.
            try:
                tup = wcproto.check_buffer(self.twbuffer)
                if not tup:
                    return
            except Exception as ex:
                self.log.info('Malformed message: %s', ex)
            self.twtable.log.info('### received message %s', tup)

    def twclose(self, dat):
        try:
            self.twtable.webconns.remove(self)
            ### say goodbye to all connections on this stream!
        except:
            pass
        self.twtable.log.info('Closed: %s (now %d connected)', self, len(self.twtable.webconns))
        self.twbuffer = None
        self.twtable = None
        
