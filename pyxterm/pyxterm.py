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

import json
import logging
import re

import tornado.auth
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket

# Allowed terminal names
TERM_NAME_RE_PART = "[a-z][a-z0-9_]*"
TERM_NAME_RE = re.compile(r"^%s$" % TERM_NAME_RE_PART)

MAX_COOKIE_STATES = 300
COOKIE_NAME = "PYXTERM_AUTH"
COOKIE_TIMEOUT = 86400

AUTH_DIGITS = 12    # Form authentication code hex-digits
                    # Note: Less than half of the 32 hex-digit state id should be used for form authentication

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

class TerminalPageHandler(tornado.web.RequestHandler):
    """Render the /ttyX pages"""
    def get(self, term_name):
        return self.render("termpage.html", static=self.static_url,
                           ws_url_path="/_websocket/"+term_name)