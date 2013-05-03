
import logging

import two.webconn

class Tworld(object):
    def __init__(self, opts):
        self.opts = opts

        self.log = logging.getLogger('tworld')
        self.webconns = two.webconn.WebConnectionTable(self)

    def listen(self):
        self.webconns.listen()
