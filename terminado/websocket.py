"""Tornado websocket handler to serve a terminal interface.
"""
# Copyright (c) Jupyter Development Team
# Copyright (c) 2014, Ramalingam Saravanan <sarava@sarava.net>
# Distributed under the terms of the Simplified BSD License.

from __future__ import absolute_import, print_function

# Python3-friendly imports
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

import logging
import importlib

import tornado.web
import tornado.websocket

def _cast_unicode(s):
    if isinstance(s, bytes):
        return s.decode('utf-8')
    return s

class TermSocket(tornado.websocket.WebSocketHandler):
    # map mapping message format identifiers to their implementing classes
    MESSAGE_FORMATS = {
        "JSON": "JSONMessageFormat",
        "LightPayload": "LightPayloadMessageFormat",
        "MessagePack": "MessagePackMessageFormat"
    }

    def get_compression_options(self):
        """Use the WebSocket's permessage-deflate extension."""
        return {}

    """Handler for a terminal websocket"""
    def initialize(self, term_manager, message_format = "JSON"):
        self.term_manager = term_manager
        self.term_name = ""
        self.size = (None, None)
        self.terminal = None
        # load the class implementing the message format
        self.message_format = getattr(importlib.import_module("terminado.formats." + message_format.lower()),
                                      self.MESSAGE_FORMATS[message_format])

        self._logger = logging.getLogger(__name__)

    def origin_check(self, origin=None):
        """Deprecated: backward-compat for terminado <= 0.5."""
        return self.check_origin(origin or self.request.headers.get('Origin'))

    def open(self, url_component=None):
        """Websocket connection opened.
        
        Call our terminal manager to get a terminal, and connect to it as a
        client.
        """
        # Jupyter has a mixin to ping websockets and keep connections through
        # proxies alive. Call super() to allow that to set up:
        super(TermSocket, self).open(url_component)

        self._logger.info("TermSocket.open: %s", url_component)

        url_component = _cast_unicode(url_component)
        self.term_name = url_component or 'tty'
        self.terminal = self.term_manager.get_terminal(url_component)
        for s in self.terminal.read_buffer:
            self.on_pty_read(s)
        self.terminal.clients.append(self)

        self.send_message("setup", {})
        self._logger.info("TermSocket.open: Opened %s", self.term_name)

    def send_message(self, command, message):
        """Sends a typed message packed by the current message format implementation."""

        pack = self.message_format.pack(command, message)

        # make sure binary packs are send as binary
        if hasattr(pack, "decode"):
            self.write_message(pack, binary=True)
        else:
            self.write_message(pack)

    def on_pty_read(self, text):
        """Data read from pty; send to frontend"""
        self.send_message("stdout", text)

    def on_message(self, pack):
        """Handle incoming websocket message
        """
        ##logging.info("TermSocket.on_message: %s - (%s) %s", self.term_name, type(message), len(message) if isinstance(message, bytes) else message[:250])
        message = self.message_format.unpack(pack)

        if message[0] == "switch_format":
            # load the class implementing the message format
            self.message_format = getattr(importlib.import_module("terminado.formats." + message[1].lower()),
                                          self.MESSAGE_FORMATS[message[1]])

            for s in self.terminal.read_buffer:
                self.on_pty_read(s)
        elif message[0] == "stdin":
            self.terminal.ptyproc.write(message[1])
        elif message[0] == "set_size":
            self.size = message[1:3]
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
        self.send_message("disconnect", 1)

        self.close()
        self.terminal = None
