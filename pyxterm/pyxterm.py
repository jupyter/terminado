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

import logging
import os
import re
import signal
import sys
import threading
import time
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

AUTH_TYPES = ("none", "login")

class TermSocket(tornado.websocket.WebSocketHandler):
    def __init__(self, application, request, **kwargs):
        super(TermSocket, self).__init__(application, request, **kwargs)
        logging.info("TermSocket.__init__: %s", request.uri)

        self.term_name = ""
        self.term_cookie = ""

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

    def open(self, term_name='tty1'):
        if not self.origin_check():
            raise tornado.web.HTTPError(404, "Websocket origin mismatch")

        logging.info("TermSocket.open:")
        access_code = ""

        self.pty_callbacks = [
            ('read', self.on_pty_read),
            ('died', self.on_pty_died),
        ]
        self.term_name = term_name
        try:
            self.terminal, _,  self.term_cookie = \
                self.application.term_manager.terminal(term_name=term_name,
                                                       access_code=access_code,
                                                       callbacks=self.pty_callbacks)

        except Exception as e:
            message = str(e)
            logging.error(message)
            self.term_remote_call("alert", message)
            self.close()
            raise

        self.term_remote_call("setup", {})
        logging.info("TermSocket.open: Opened %s", self.term_name)

    def on_pty_read(self, text):
        self.send_json_message(['stdout', text])

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

    def send_json_message(self, content):
        json_msg = json.dumps(content)
        self.write_message(json_msg)

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
    
    def _parse_message(self, message):
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
        
        return command, content

    def on_message(self, message):
        ##logging.info("TermSocket.on_message: %s - (%s) %s", self.term_name, type(message), len(message) if isinstance(message, bytes) else message[:250])
        command, _ = self._parse_message(message)
            
        kill_term = False
        try:
            send_cmd = True
            if command[0] == "kill_term":
                kill_term = True
            elif command[0] == "errmsg":
                logging.error("Terminal %s: %s", self.term_name, command[1])
                send_cmd = False

            if send_cmd:
                if command[0] == "stdin":
                    text = command[1].replace("\r\n","\n").replace("\r","\n")
                    self.terminal.pty_write(text)
                else:
                    self.terminal.remote_call(*command)
                if kill_term:
                    self.terminal.kill()
                    self.application.term_manager.discard(self.term_name)

        except Exception as excp:
            logging.error("TermSocket.on_message: ERROR %s", excp)
            self.term_remote_call("errmsg", str(excp))
            return

    def on_close(self):
        self.terminal.unregister_multi(self.pty_callbacks)

    def on_pty_died(self):
        self.send_json_message(['disconnect', 1])
        self.close()

class NewTerminalHandler(tornado.web.RequestHandler):
    """Redirect to an unused terminal name"""
    def get(self):
        terminal, term_name, cookie = self.application.term_manager.terminal()
        self.redirect("/" + term_name, permanent=False)

class TerminalPageHandler(tornado.web.RequestHandler):
    """Render the /ttyX pages"""
    def get(self, term_name):
        return self.render("termpage.html", static=self.static_url,
                           ws_url_path="/_websocket/"+term_name)

class Application(tornado.web.Application):
    def __init__(self, term_manager, **kwargs):
        self.term_manager = term_manager
        handlers = [
                (r"/_websocket/(%s)" % TERM_NAME_RE_PART, TermSocket),
                (r"/new/?", NewTerminalHandler),
                (r"/(tty\d+)/?", TerminalPageHandler),
                ]
        
        if 'template_path' not in kwargs:
            kwargs['template_path'] = os.path.join(os.path.dirname(__file__), "templates")
        if 'static_path' not in kwargs:
            kwargs['static_path'] = Doc_rootdir
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
        if options.auth_type == "login":
            sys.exit("--auth_type=login cannot be combined with specified shell command")
        shell_command = args[:]
    elif options.auth_type == "login":
        if os.geteuid():
            sys.exit("Error: Must run server as root for --auth_type=login")
        if not options.https and external_host != "localhost":
            sys.exit("Error: At this time --auth_type=login is permitted only with https or localhost (for security reasons)")
        shell_command = ["login"]
    else:
        shell_command = ["bash"]

    tem_str = options.term_options.strip().replace(" ","")
    term_options = set(tem_str.split(",") if tem_str else [])
    term_settings = {"type": options.term_type, "max_terminals": options.max_terminals,
                     "https": options.https, "logging": options.logging,
                     "options": term_options, "server_url": server_url, "auth_type": options.auth_type}

    app_settings = {"log_function": lambda x:None}

    term_manager = pyxshell.TermManager(shell_command=shell_command, server_url="",
                                        term_settings=term_settings)

    application = Application(term_manager=term_manager, **app_settings)

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
