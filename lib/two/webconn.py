import errno
import socket

import tornado.ioloop
import tornado.iostream

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
            
            stream = tornado.iostream.IOStream(sock)
            stream.twhost = host
            self.webconns.add(stream)
            self.log.info('Accepted web connection from %s (now %d connected)', stream.twhost, len(self.webconns))

            stream.read_until_close(
                lambda dat:self.stream_closed(stream, dat),
                lambda dat:self.stream_read(stream, dat))

    def stream_read(self, stream, dat):
        self.log.info('### stream_read %s', dat)

    def stream_closed(self, stream, dat):
        try:
            self.webconns.remove(stream)
        except:
            pass
        self.log.info('End of web connection from %s (now %d connected)', stream.twhost, len(self.webconns))
        
        
