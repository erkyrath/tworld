import errno
import socket
import logging

import tornado.ioloop

class Tworld(object):
    def __init__(self, opts):
        self.opts = opts

        self.log = logging.getLogger('tworld')

        self.listensock = None

    def listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.listensock = sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(0)
        sock.bind( ('localhost', self.opts.tworld_port) )
        sock.listen(32)
        
        tornado.ioloop.IOLoop.instance().add_handler(
            sock.fileno(),
            self.listen_ready,
            tornado.ioloop.IOLoop.READ)
        
        self.log.info('Listening on port %d', self.opts.tworld_port)

    def listen_ready(self, fd, events):
        while True:
            try:
                (sock, addr) = self.listensock.accept()
            except socket.error as ex:
                if ex.args[0] not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                return
            sock.setblocking(0)
            self.log.info('Accepted connection from %s', addr)
