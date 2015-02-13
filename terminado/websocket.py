"""Tornado websocket handler to serve a terminal interface.
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

from __future__ import absolute_import, print_function

# Python3-friendly imports
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

import json
import logging

import tornado.web
import tornado.websocket

def _cast_unicode(s):
    if isinstance(s, bytes):
        return s.decode('utf-8')
    return s

class TermSocket(tornado.websocket.WebSocketHandler):
    """Handler for a terminal websocket"""
    def initialize(self, term_manager):
        self.term_manager = term_manager
        self.term_name = ""
        self.size = (None, None)
        self.terminal = None

        self._log = logging.getLogger(__name__)

    def origin_check(self):
        """Reject connections from other origin pages.
        
        This is superfluous with Tornado >= 4, as the same check was added to
        Tornado itself. For now, we keep this around for older versions of
        Tornado.
        """
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
            self._log.error("pyxterm.origin_check: ERROR %s != %s", host, ws_host)
            return False

    def open(self, url_component=None):
        """Websocket connection opened.
        
        Call our terminal manager to get a terminal, and connect to it as a
        client.
        """
        if not self.origin_check():
            raise tornado.web.HTTPError(404, "Websocket origin mismatch")

        self._log.info("TermSocket.open: %s", url_component)

        url_component = _cast_unicode(url_component)
        self.term_name = url_component or 'tty'
        self.terminal = self.term_manager.get_terminal(url_component)
        for s in self.terminal.read_buffer:
            self.on_pty_read(s)
        self.terminal.clients.append(self)

        self.send_json_message(["setup", {}])
        self._log.info("TermSocket.open: Opened %s", self.term_name)

    def on_pty_read(self, text):
        """Data read from pty; send to frontend"""
        self.send_json_message(['stdout', text])

    def send_json_message(self, content):
        json_msg = json.dumps(content)
        self.write_message(json_msg)

    def on_message(self, message):
        """Handle incoming websocket message
        
        We send JSON arrays, where the first element is a string indicating
        what kind of message this is. Data associated with the message follows.
        """
        ##logging.info("TermSocket.on_message: %s - (%s) %s", self.term_name, type(message), len(message) if isinstance(message, bytes) else message[:250])
        command = json.loads(message)
        msg_type = command[0]    

        if msg_type == "stdin":
            self.terminal.ptyproc.write(command[1])
        elif msg_type == "set_size":
            self.size = command[1:3]
            self.terminal.resize_to_smallest()

    def on_close(self):
        """Handle websocket closing.
        
        Disconnect from our terminal, and tell the terminal manager we're
        disconnecting.
        """
        self._log.info("Websocket closed")
        if self.terminal:
            self.terminal.clients.remove(self)
            self.terminal.resize_to_smallest()
        self.term_manager.client_disconnected(self)

    def on_pty_died(self):
        """Terminal closed: tell the frontend, and close the socket.
        """
        self.send_json_message(['disconnect', 1])
        self.close()
