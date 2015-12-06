#!/usr/bin/env python3

"""
twcommand: Copyright (c) 2015, Andrew Plotkin
(Available under the MIT License; see LICENSE file.)

This script logs into live Tworld server (with regular web authentication)
and then performs a command. Currently just one command is supported:

    holler msg (requires admin)
"""

import sys
import os
import optparse
import urllib
import urllib.parse
import urllib.request
import html.parser
import http.cookiejar
import getpass
import unicodedata

popt = optparse.OptionParser(usage='twcommand.py [opts] cmd [args...]')

popt.add_option('-l', '--list',
                action='store_true', dest='listcmds',
                help='list the available commands')
popt.add_option('-n', '--name',
                action='store', dest='name',
                help='user name')
popt.add_option('--password',
                action='store', dest='password',
                help='user password')
popt.add_option('-u', '--url',
                action='store', dest='url',
                help='server URL (default: http://localhost)')
popt.add_option('-s', '--host', '--server',
                action='store', dest='server', default='localhost',
                help='server hostname (default: localhost)')
popt.add_option('-p', '--port',
                action='store', type=int, dest='port',
                help='server port')

(opts, args) = popt.parse_args()

if opts.listcmds:
    print('login: just log in, take no other action')
    print('holler msg...: broadcast a line of text to all logged-in players. (requires admin)')
    sys.exit(0)
    
if not args:
    popt.print_help()
    sys.exit(-1)

if not opts.name:
    raise Exception('You must supply a name (--name)')

if not opts.password:
    password = getpass.getpass()
    opts.password = unicodedata.normalize('NFKC', password)

class Tag:
    def __init__(self, tag, attrs=None):
        self.tag = tag
        if attrs is None:
            self.attrs = {}
        else:
            self.attrs = dict(attrs)
        self.children = []

    def __repr__(self):
        if not self.attrs:
            return '<Tag "%s">' % (self.tag,)
        else:
            ls = [ '%s="%s"' % (key, val) for (key, val) in self.attrs.items() ]
            return '<Tag "%s" %s>' % (self.tag, ' '.join(ls))

class ExtractParser(html.parser.HTMLParser):
    def __init__(self, parent, child):
        html.parser.HTMLParser.__init__(self)
        self.parenttag = parent
        self.childtag = child
        self.results = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == self.parenttag and self.current is None:
            self.current = Tag(tag, attrs)
            self.results.append(self.current)
        if tag == self.childtag and self.current is not None:
            child = Tag(tag, attrs)
            self.current.children.append(child)

    def handle_endtag(self, tag):
        if tag == self.parenttag and self.current is not None:
            self.current = None
    
def extract(html, parent, child):
    parser = ExtractParser(parent, child)
    parser.feed(html)
    return parser.results
    
def login():
    print('Logging in to %s' % (baseurl,))

    req = urllib.request.Request(url=baseurl)
    response = urlopener.open(req)
    html = response.read().decode('utf-8')
    
    ls = extract(html, 'form', 'input')
    login = None
    for form in ls:
        inputmap = {}
        for child in form.children:
            name = child.attrs.get('name')
            if name:
                inputmap[name] = child
            if name == 'commit' and child.attrs.get('type') == 'submit':
                login = inputmap
    if not login:
        raise Exception('No login form on main page')

    xsrf = login['_xsrf'].attrs.get('value')

    map = { '_xsrf':xsrf, 'name':opts.name, 'password':opts.password }
    data = urllib.parse.urlencode(map).encode()
    req = urllib.request.Request(url=baseurl, method='POST', data=data)
    response = urlopener.open(req)
    html = response.read().decode('utf-8')

    session = None
    for cookie in cookiejar:
        if cookie.name == 'sessionid':
            session = cookie
            break
    if session is None:
        raise Exception('Login failed')
        

def logout():
    req = urllib.request.Request(url=urllib.parse.urljoin(baseurl, '/logout'))
    response = urlopener.open(req)
    html = response.read().decode('utf-8')

def cmd_nop(args):
    pass

def cmd_holler(args):
    msg = (' '.join(args)).strip()
    if not msg:
        raise Exception('holler: no argument')
    url = urllib.parse.urljoin(baseurl, '/admin')
    
    req = urllib.request.Request(url=url)
    response = urlopener.open(req)
    html = response.read().decode('utf-8')

    ls = extract(html, 'form', 'input')
    holler = None
    for form in ls:
        inputmap = {}
        for child in form.children:
            name = child.attrs.get('name')
            if name:
                inputmap[name] = child
            if name == 'holler' and child.attrs.get('type') == 'submit':
                holler = inputmap
    if not holler:
        raise Exception('No holler form on main page')

    xsrf = holler['_xsrf'].attrs.get('value')

    map = { '_xsrf':xsrf, 'holler':'holler', 'message':msg }
    data = urllib.parse.urlencode(map).encode()
    req = urllib.request.Request(url=url, method='POST', data=data)
    response = urlopener.open(req)
    html = response.read().decode('utf-8')

cmdlist = {
    'login': cmd_nop,
    'holler': cmd_holler
}
    
cmd = args.pop(0)

if cmd not in cmdlist:
    raise Exception('Unknown command: ' + cmd)

if opts.url:
    baseurl = opts.url
else:
    if not opts.port:
        netloc = opts.server
    else:
        netloc = opts.server + (':%d' % (opts.port,))
    baseurl = urllib.parse.urlunsplit( ('http', netloc, '', '', '') )

cookiejar = http.cookiejar.CookieJar()
urlopener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))

login()
cmdlist[cmd](args)
logout()



