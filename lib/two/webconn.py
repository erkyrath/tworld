"""
Keep track of the tweb servers that are connected.

(The way tworld is currently built, there will be no more than one tweb
connected at a time. But we have some of the infrastructure necessary
for several.)
"""

import types
import errno
import socket

import tornado.ioloop
import tornado.iostream
import tornado.platform

from twcommon import wcproto

class WebConnectionTable(object):
    """WebConnectionTable manages the set of WebConnIOStreams connected
    at any given time.
    """
    
    def __init__(self, app):
        # Keep a link to the owning application.
        self.app = app
        self.log = self.app.log

        self.ioloop = None
        self.listensock = None
        self.map = {}  # maps twwcids to IOStreams (normally just one)

    def close(self):
        """Close every socket, including the listener, in preparation
        for a shutdown.
        """
        if (self.listensock):
            self.listensock.close()
            self.listensock = None
        for conn in self.all():
            conn.close()

    def get(self, twwcid):
        """Look up a WebConnIOStream by its twwcid.
        """
        return self.map.get(twwcid, None)

    def all(self):
        """A (non-dynamic) list of all tweb connections.
        """
        return list(self.map.values())

    def listen(self):
        """Begin listening for incoming tweb connections. This is called
        when the ioloop begins.
        """
        self.ioloop = tornado.ioloop.IOLoop.current()
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.listensock = sock
        tornado.platform.auto.set_close_exec(sock.fileno())
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
        """Callback: invoked when somebody connects to the listening socket.
        We accept the connection (perhaps several, if they're piled up)
        and begin reading data from it.
        """
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
    """The connection to the tweb server. This is an ordinary Tornado
    async stream connection.
    """
    
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
        """Callback: invoked when the stream receives new data.
        """
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
        """Callback: invoked when the stream closes.
        """
        try:
            self.twtable.map.pop(self.twwcid, None)
            # Say goodbye to all connections on this stream!
            # But we do this as a queued command. Until it comes around,
            # we might see some write failures.
            self.twtable.app.queue_command(
                {'cmd':'disconnect', 'twwcid':self.twwcid}, 0, 0)
        except:
            pass
        self.twtable.log.warning('Closed: %s', self)
        # Clean up dangling references.
        self.twhost = None
        self.twbuffer = None
        self.twtable = None
        self.twwcid = None
        
