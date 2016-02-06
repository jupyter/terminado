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
    def initialize(self, term_manager, keep_alive_time=0):
        """
        keep_alive_time - if there is no activity for x seconds specified in keep_alive_time,
                          a websocket ping message will be sent. Default is 0. Set it to 0 to
                          disable sending the ping message. This feature is used to keep proxies 
                          such as nginx from automatically closing the connection when there is 
                          no activity.
        """
        self.term_manager = term_manager
        self.term_name = ""
        self.size = (None, None)
        self.terminal = None

        self._logger = logging.getLogger(__name__)

        #send a ping if there is no activity for more than this many of seconds
        self.keep_alive_time = keep_alive_time 
        self.last_activity_time = 0
    
    def __timer(self):
        if self.ws_connection is not None:
            io_loop = self.ws_connection.stream.io_loop
            t = io_loop.time()
            if t - self.last_activity_time > self.keep_alive_time:
                self.ping(b"ping")
                #logging.debug('websocket ping')
                self.last_activity_time = t
            io_loop.add_timeout(max(0.2*self.keep_alive_time, 0.25), self.__timer) 
                
    def __update_last_activity_time(self):
        if self.ws_connection is not None:
            io_loop = self.ws_connection.stream.io_loop
            t = io_loop.time()
            self.last_activity_time = t
            
    def origin_check(self, origin=None):
        """Deprecated: backward-compat for terminado <= 0.5."""
        return self.check_origin(origin or self.request.headers.get('Origin'))

    def open(self, url_component=None):
        """Websocket connection opened.
        
        Call our terminal manager to get a terminal, and connect to it as a
        client.
        """

        self._logger.info("TermSocket.open: %s", url_component)

        url_component = _cast_unicode(url_component)
        self.term_name = url_component or 'tty'
        self.terminal = self.term_manager.get_terminal(url_component)
        for s in self.terminal.read_buffer:
            self.on_pty_read(s)
        self.terminal.clients.append(self)

        self.send_json_message(["setup", {}])
        
        if self.keep_alive_time>0:
            self.__update_last_activity_time()
            io_loop = self.ws_connection.stream.io_loop            
            io_loop.add_timeout(max(0.2*self.keep_alive_time, 0.25), self.__timer)        
            
        self._logger.info("TermSocket.open: Opened %s", self.term_name)
    
    def on_pty_read(self, text):
        """Data read from pty; send to frontend"""
        self.send_json_message(['stdout', text])
      

    def send_json_message(self, content):
        json_msg = json.dumps(content)
        self.write_message(json_msg)
        if self.keep_alive_time>0:
            self.__update_last_activity_time()
        
    def on_message(self, message):
        """Handle incoming websocket message
        
        We send JSON arrays, where the first element is a string indicating
        what kind of message this is. Data associated with the message follows.
        """
        ##logging.info("TermSocket.on_message: %s - (%s) %s", self.term_name, type(message), len(message) if isinstance(message, bytes) else message[:250])
        if self.keep_alive_time>0:
            self.__update_last_activity_time()
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
        self._logger.info("Websocket closed")
        if self.terminal:
            self.terminal.clients.remove(self)
            self.terminal.resize_to_smallest()
        self.term_manager.client_disconnected(self)

    def on_pty_died(self):
        """Terminal closed: tell the frontend, and close the socket.
        """
        self.send_json_message(['disconnect', 1])
        self.close()
