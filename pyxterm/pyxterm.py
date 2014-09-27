#!/usr/bin/env python

"""pyxterm.py: Python websocket terminal server for term.js, using pxterm.py as the backend

Requires term.js, pyxterm.js pyxshell.py

To test, run:

  ./pyxterm.py --terminal

to start the server an open a terminal. For help, type

  ./pyxterm.py -h

Default URL to a create a new terminal is http://localhost:8700/new

To create a named terminal, open http://localhost:8700/terminal_name

BSD License

"""

#
#  BSD License
#
#  Copyright (c) 2014, Ramalingam Saravanan <sarava@sarava.net>
#  All rights reserved.
#  
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#  
#  1. Redistributions of source code must retain the above copyright notice, this
#     list of conditions and the following disclaimer. 
#  2. Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution. 
#  
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
#  ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
#  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
#  ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
#  (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
#  ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import absolute_import, print_function, with_statement


# Python3-friendly imports
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

import collections
import logging
import os
import re
import signal
import sys
import threading
import time
import uuid
import webbrowser

try:
    import ujson as json
except ImportError:
    import json

import pyxshell
from sslcerts import prepare_ssl_options

import tornado.auth
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

File_dir = os.path.dirname(__file__)
if File_dir == ".":
    File_dir = os.getcwd()    # Need this for daemonizing to work?
Doc_rootdir = os.path.join(File_dir, "_static")

BANNER_HTML = '<center><h2>pyxterm</h2></center>'

STATIC_PATH = "_static"
STATIC_PREFIX = "/"+STATIC_PATH+"/"

# Allowed terminal names
TERM_NAME_RE_PART = "[a-z][a-z0-9_]*"
TERM_NAME_RE = re.compile(r"^%s$" % TERM_NAME_RE_PART)

MAX_COOKIE_STATES = 300
COOKIE_NAME = "PYXTERM_AUTH"
COOKIE_TIMEOUT = 86400

AUTH_DIGITS = 12    # Form authentication code hex-digits
                    # Note: Less than half of the 32 hex-digit state id should be used for form authentication

AUTH_TYPES = ("none", "ssh", "login")

def get_query_auth(state_id):
    return state_id[:AUTH_DIGITS]

def get_first_arg(query_data, argname, default=""):
    return query_data.get(argname, [default])[0]


class TermSocket(tornado.websocket.WebSocketHandler):
    _all_term_sockets = {}
    _all_term_paths = collections.defaultdict(set)
    _term_counter = [0]
    _term_states = OrderedDict()
    _term_connect_cookies = OrderedDict()

    @classmethod
    def get_connect_cookie(cls):
        while len(cls._term_connect_cookies) > 100:
            cls._term_connect_cookies.popitem(last=False)
        new_cookie = uuid.uuid4().hex[:12]
        cls._term_connect_cookies[new_cookie] = {}  # connect_data (from form submission)
        return new_cookie

    @classmethod
    def check_connect_cookie(cls, cookie):
        return cls._term_connect_cookies.pop(cookie, None)            

    @classmethod
    def update_connect_cookie(cls, cookie, connect_data):
        if cookie not in cls._term_connect_cookies:
            return False
        cls._term_connect_cookies[cookie] = connect_data
        return True

    @classmethod
    def get_state(cls, state_id):
        return cls._term_states.get(state_id, None)

    @classmethod
    def get_request_state(cls, request):
        if COOKIE_NAME not in request.cookies:
            return None
        cookie_value = request.cookies[COOKIE_NAME].value
        state_value = cls.get_state(cookie_value)
        if state_value:
            return state_value
        # Note: webcast auth will always be dropped
        cls.drop_state(cookie_value)
        return None

    @classmethod
    def drop_state(cls, state_id):
        cls._term_states.pop(state_id, None)

    @classmethod
    def add_state(cls, user="", email=""):
        state_id = uuid.uuid4().hex
        authstate = {"state_id": state_id,
                     "user": user,
                     "email": email,
                     "time": time.time()}
        if len(cls._term_states) >= MAX_COOKIE_STATES:
            cls._term_states.popitem(last=False)
        cls._term_states[state_id] = authstate
        return authstate

    def __init__(self, application, request, **kwargs):
        super(TermSocket, self).__init__(application, request, **kwargs)
        logging.info("TermSocket.__init__: %s", request.uri)

        self.term_authstate = None
        self.term_path = ""
        self.term_cookie = ""
        self.term_client_id = None

    def origin_check(self):
        if "Origin" in self.request.headers:
            origin = self.request.headers.get("Origin")
        else:
            origin = self.request.headers.get("Sec-Websocket-Origin", None)

        if not origin:
            return False

        host = self.request.headers.get("Host").lower()
        ws_host = urlparse(origin).netloc.lower()
        if host == ws_host:
            return True
        else:
            logging.error("pyxterm.origin_check: ERROR %s != %s", host, ws_host)
            return False

    def term_authenticate(self):
        authstate = self.get_request_state(self.request)
        if authstate:
            return authstate
        return self.add_state()

    def open(self, term_name):
        if not self.origin_check():
            raise tornado.web.HTTPError(404, "Websocket origin mismatch")

        logging.info("TermSocket.open:")

        connect_auth = self.get_query_argument("cauth", "")
        connect_data = self.check_connect_cookie(connect_auth)
        if connect_data is None:
            # Invalid connect cookie
            connect_auth = None

        authstate = self.term_authenticate()
        if not authstate:
            logging.error("TermSocket.open: ERROR authentication failed")
            self.close()
            return

        self.term_authstate = authstate

        query_auth = self.get_query_argument("qauth", "")

        if not connect_auth and (not query_auth or query_auth != get_query_auth(self.term_authstate["state_id"])):
            # Confirm request, if no form data
            ##logging.info("TermSocket.open: Confirm request %s", term_name)
            confirm_url = "/%s/?cauth=%s" % (term_name, self.get_connect_cookie())
            self.term_remote_call("document", BANNER_HTML+'<p><h3>Click to open terminal <a href="%s">%s</a></h3>' % (confirm_url, "/"+term_name))
            self.close()
            return

        # Require access for ssh/login auth types (because there is no user authentication)
        auth_type = self.application.term_settings['auth_type']
        access_code = "" if auth_type == "none" else self.term_authstate["state_id"]
    
        try:
            self.terminal, self.term_path, self.term_cookie = \
                self.application.term_manager.terminal(term_name=term_name,
                                                       access_code=access_code)

        except Exception as e:
            message = str(e)
            logging.error(message)
            self.term_remote_call("alert", message)
            self.close()
            return

        if not query_auth:
            redirect_url = "/%s/?qauth=%s" % (self.term_path, get_query_auth(self.term_authstate["state_id"]))
            self.term_remote_call("redirect", redirect_url, self.term_authstate["state_id"])
            self.close()
            return

        self.terminal.read_callbacks.append(self.on_pty_read)
        loop = tornado.ioloop.IOLoop.instance()
        try:
            loop.add_handler(self.terminal.fd, self.terminal.read_ready, loop.READ)
        except OSError as e:
            import errno
            # We seem to get FileExistsError if the handler was already registered
            if e.errno != errno.EEXIST:
                raise

        self.add_termsocket()

        self.term_remote_call("setup", {"state_id": self.term_authstate["state_id"],
                                        "client_id": self.term_client_id,
                                        "term_path": self.term_path})
        logging.info("TermSocket.open: Opened %s", self.term_path)

    @classmethod
    def get_path_termsockets(cls, path):
        return cls._all_term_paths.get(path, set())

    @classmethod
    def get_termsocket(cls, client_id):
        return cls._all_term_sockets.get(client_id)            

    def add_termsocket(self):
        self._term_counter[0] += 1
        self.term_client_id = str(self._term_counter[0])

        self._all_term_sockets[self.term_client_id] = self     
        self._all_term_paths[self.term_path].add(self.term_client_id)
        return self.term_client_id

    def on_close(self):
        logging.info("TermSocket.on_close: Closing %s", self.term_path)
        self._all_term_sockets.pop(self.term_client_id, None)
        if self.term_path in self._all_term_paths:
            self._all_term_paths[self.term_path].discard(self.term_client_id)

    @classmethod
    def term_remote_callback(cls, term_path, client_id, method, *args):
        client_ids = [client_id] if client_id else cls.get_path_termsockets(term_path)
        try:
            json_msg = json.dumps([method, args])
            ##logging.info("term_remote_callback: %s, %s, %s", args, json.loads(json.dumps(args[0])) if args else "NONE", json_msg)
            for client_id in client_ids:
                termsocket = cls.get_termsocket(client_id)
                if termsocket:
                    termsocket.term_write(json_msg)
        except Exception as excp:
            logging.error("term_remote_callback: ERROR %s", excp)

    def on_pty_read(self, text):
        json_msg = json.dumps(['stdout', text])
        self.write_message(json_msg)

    def term_remote_call(self, method, *args, **kwargs):
        """
        kwargs: content=None, content_type="", content_encoding=""
        """
        logging.error("term_remote_call: %s", method)
        try:
            if not kwargs:
                # Text message
                json_msg = json.dumps([method, args])
                self.term_write(json_msg)
            else:
                # Binary message with UTF-16 JSON prefix
                content = kwargs.get("content")
                assert isinstance(content, bytes), "Content must be of bytes type"
                
                json_prefix = json.dumps([method, args, {"content_type": kwargs.get("content_type",""),
                                                             "content_encoding": kwargs.get("content_encoding",""),
                                                             "content_length": len(content)} ]) + "\n\n"
                content_prefix = json_prefix.encode("utf-16")
                self.term_write(content_prefix+content, binary=True)
        except Exception as excp:
            logging.error("term_remote_call: ERROR %s", excp)

    def term_write(self, data, binary=False):
        try:
            self.write_message(data, binary=binary)
        except Exception as excp:
            logging.error("term_write: ERROR %s", excp)
            closed_excp = getattr(tornado.websocket, "WebSocketClosedError", None)
            if not closed_excp or not isinstance(excp, closed_excp):
                import traceback
                logging.info("Error in websocket: %s\n%s", excp, traceback.format_exc())
            try:
                # Close websocket on write error
                self.close()
            except Exception:
                pass

    def on_message(self, message):
        ##logging.info("TermSocket.on_message: %s - (%s) %s", self.term_path, type(message), len(message) if isinstance(message, bytes) else message[:250])
        if not self.term_path:
            return

        if isinstance(message, bytes):
            # Binary message with UTF-16 JSON prefix
            enc_delim = "\n\n".encode("utf-16")
            offset = message.find(enc_delim)
            if offset < 0:
                raise Exception("Delimiter not found in binary message")
            command = json.loads(message[:offset]).decode("utf-16")
            content = message[offset+len(enc_delim):]
        else:
            command = json.loads(message if isinstance(message,str) else message.encode("UTF-8", "replace"))
            content = None
            
        kill_term = False
        try:
            send_cmd = True
            if command[0] == "kill_term":
                kill_term = True
            elif command[0] == "errmsg":
                logging.error("Terminal %s: %s", self.term_path, command[1])
                send_cmd = False

            if send_cmd:
                if command[0] == "stdin":
                    text = command[1].replace("\r\n","\n").replace("\r","\n")
                    self.terminal.pty_write(text)
                else:
                    self.application.term_manager.remote_term_call(self.term_path, *command)
                if kill_term:
                    self.kill_remote(self.term_path, from_user)

        except Exception as excp:
            logging.error("TermSocket.on_message: ERROR %s", excp)
            self.term_remote_call("errmsg", str(excp))
            return

    def kill_remote(self, term_path, user):
        for client_id in TermSocket.get_path_termsockets(term_path):
            tsocket = TermSocket.get_termsocket(client_id)
            if tsocket:
                tsocket.term_remote_call("document", BANNER_HTML+'<p>CLOSED TERMINAL<p><a href="/">Home</a>')
                tsocket.on_close()
                tsocket.close()
        try:
            self.application.term_manager.kill_term(term_path)
        except Exception:
            pass

class NewTerminalHandler(tornado.web.RequestHandler):
    """Redirect to an unused terminal name"""
    def get(self):
        # XXX: Race condition if two users hit /new ~ simultaneously
        term_name = self.application.term_manager.next_available_name()
        print(".. Redirecting", term_name)
        self.redirect("/" + term_name, permanent=False)

class Application(tornado.web.Application):
    def __init__(self, term_manager, term_settings, **kwargs):
        self.term_manager = term_manager
        self.term_settings = term_settings
        handlers = [
                (r"/_websocket/(%s)" % TERM_NAME_RE_PART, TermSocket),
                (STATIC_PREFIX+r"(.*)", tornado.web.StaticFileHandler, {"path": Doc_rootdir}),
                (r"/new/?", NewTerminalHandler),
                (r"/()tty\d+/?", tornado.web.StaticFileHandler, {"path": Doc_rootdir, "default_filename": "index.html"}),
                ]
        super(Application, self).__init__(handlers, **kwargs)

def run_server(options, args):

    http_port = options.port
    http_host = options.host
    external_host = options.external_host or http_host
    external_port = options.external_port or http_port
    if options.https:
        server_url = "https://"+external_host+("" if external_port == 443 else ":%d" % external_port)
    else:
        server_url = "http://"+external_host+("" if external_port == 80 else ":%d" % external_port)
    new_url = server_url + "/new"

    if args:
        if options.auth_type in ("login", "ssh"):
            sys.exit("--auth_type=login/ssh cannot be combined with specified shell command")
        shell_command = args[:]
    elif options.auth_type == "login":
        if os.geteuid():
            sys.exit("Error: Must run server as root for --auth_type=login")
        if not options.https and external_host != "localhost":
            sys.exit("Error: At this time --auth_type=login is permitted only with https or localhost (for security reasons)")
        shell_command = ["login"]
    elif options.auth_type == "ssh":
        if not pyxshell.match_program_name("sshd"):
            sys.exit("Error: sshd must be running for --auth_type=ssh")
        shell_command = ["ssh"]
    else:
        shell_command = ["bash"]

    tem_str = options.term_options.strip().replace(" ","")
    term_options = set(tem_str.split(",") if tem_str else [])
    term_settings = {"type": options.term_type, "max_terminals": options.max_terminals,
                     "https": options.https, "logging": options.logging,
                     "options": term_options, "server_url": server_url, "auth_type": options.auth_type}

    app_settings = {"log_function": lambda x:None}

    term_manager = pyxshell.TermManager(TermSocket.term_remote_callback,
                                        shell_command=shell_command, server_url="",
                                        term_settings=term_settings)

    application = Application(term_manager=term_manager, term_settings=term_settings,
                              **app_settings)

    ##logging.warning("DocRoot: "+Doc_rootdir);

    IO_loop = tornado.ioloop.IOLoop.instance()

    ssl_options = prepare_ssl_options(options)

    Http_server = tornado.httpserver.HTTPServer(application, ssl_options=ssl_options)
    Http_server.listen(http_port, address=http_host)
    if options.logging:
        Log_filename = "pyxterm.log"
        pyxshell.setup_logging(logging.INFO, Log_filename, logging.INFO)
        logging.error("**************************Logging to %s", Log_filename)
    else:
        pyxshell.setup_logging(logging.WARNING)
        logging.error("**************************Logging to console")

    if options.terminal:
        try:
            webbrowser.open_new_tab(new_url)
        except Exception as excp:
            print("Error in creating terminal; please open URL %s in browser (%s)" % (new_url, excp), file=sys.stderr)

    def stop_server():
        print("\nStopping server", file=sys.stderr)
        if Http_server:
            Http_server.stop()
        def stop_server_aux():
            IO_loop.stop()

        # Need to stop IO_loop only after all other scheduled shutdowns have completed
        IO_loop.add_callback(stop_server_aux)

    def sigterm(signal, frame):
        logging.warning("SIGTERM signal received")
        IO_loop.add_callback(stop_server)
    signal.signal(signal.SIGTERM, sigterm)

    try:
        ioloop_thread = threading.Thread(target=IO_loop.start)
        ioloop_thread.start()
        time.sleep(1)   # Time to start thread
        print("Pyxterm server started", file=sys.stderr)
        print("Open URL %s in browser to connect" % new_url, file=sys.stderr)
        print("Type ^C to stop", file=sys.stderr)
        while Http_server:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)

    finally:
        if term_manager:
            term_manager.shutdown()
    IO_loop.add_callback(stop_server)

def main():
    from optparse import OptionParser
    usage = "usage: %prog [<shell_command>]"
    parser = OptionParser(usage=usage)
    parser.add_option("", "--host", dest="host", default="localhost",
                      help="Host (default: localhost)")
    parser.add_option("", "--port", dest="port", default=8700, type="int",
                      help="Port to listen on (default: 8700)")
    parser.add_option("", "--external_host", dest="external_host", default="",
                      help="External host (default: same as host)")
    parser.add_option("", "--external_port", dest="external_port", default=0, type="int",
                      help="External port (default: same as port)")
    parser.add_option("", "--https", dest="https", default=False, action="store_true",
                      help="Enable https")
    parser.add_option("", "--auth_type", dest="auth_type", default="none",
                      help="Authentication type: %s (default: ssh)" % "/".join(AUTH_TYPES))
    parser.add_option("", "--client_cert", dest="client_cert", default="",
                      help="Path to client CA cert (or '.')")
    parser.add_option("", "--term_type", dest="term_type", default="xterm",
                      help="Terminal type (default: xterm)")
    parser.add_option("", "--term_options", dest="term_options", default="",
                      help="Terminal options (comma-separated, no spaces)")
    parser.add_option("", "--max_terminals", dest="max_terminals", default=100, type="int",
                      help="Maximum number of terminals")
    parser.add_option("-t", "--terminal", dest="terminal", default=False, action="store_true",
                      help="Open new terminal window at start")
    parser.add_option("-l", "--logging", dest="logging", default=False, action="store_true",
                      help="Enable logging")

    (options, args) = parser.parse_args()

    if options.auth_type not in AUTH_TYPES:
        sys.exit("--auth_type must be one of %s" % (AUTH_TYPES,))

    tornado.options.options.logging = "none"    # Disable tornado logging
    tornado.options.parse_command_line([])      # Parse "dummy" command line

    run_server(options, args)

if __name__ == "__main__":
    main()
