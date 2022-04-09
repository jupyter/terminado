"""Tornado websocket handler to serve a terminal interface.
"""
# Copyright (c) Jupyter Development Team
# Copyright (c) 2014, Ramalingam Saravanan <sarava@sarava.net>
# Distributed under the terms of the Simplified BSD License.


import json
import logging
import os

import tornado.websocket


def _cast_unicode(s):
    if isinstance(s, bytes):
        return s.decode("utf-8")
    return s


class TermSocket(tornado.websocket.WebSocketHandler):
    """Handler for a terminal websocket"""

    def initialize(self, term_manager):
        self.term_manager = term_manager
        self.term_name = ""
        self.size = (None, None)
        self.terminal = None

        self._logger = logging.getLogger(__name__)
        self._user_command = ""

        # Enable if the environment variable LOG_TERMINAL_OUTPUT is "true"
        self._enable_output_logging = str.lower(os.getenv("LOG_TERMINAL_OUTPUT", "false")) == "true"

    def origin_check(self, origin=None):
        """Deprecated: backward-compat for terminado <= 0.5."""
        return self.check_origin(origin or self.request.headers.get("Origin"))

    def open(self, url_component=None):
        """Websocket connection opened.

        Call our terminal manager to get a terminal, and connect to it as a
        client.
        """
        # Jupyter has a mixin to ping websockets and keep connections through
        # proxies alive. Call super() to allow that to set up:
        super().open(url_component)

        self._logger.info("TermSocket.open: %s", url_component)

        url_component = _cast_unicode(url_component)
        self.term_name = url_component or "tty"
        self.terminal = self.term_manager.get_terminal(url_component)
        self.terminal.clients.append(self)
        self.send_json_message(["setup", {}])
        self._logger.info("TermSocket.open: Opened %s", self.term_name)
        # Now drain the preopen buffer, if reconnect.
        buffered = ""
        preopen_buffer = self.terminal.read_buffer.copy()
        while True:
            if not preopen_buffer:
                break
            s = preopen_buffer.popleft()
            buffered += s
        if buffered:
            self.on_pty_read(buffered)

    def on_pty_read(self, text):
        """Data read from pty; send to frontend"""
        self.send_json_message(["stdout", text])

    def send_json_message(self, content):
        json_msg = json.dumps(content)
        self.write_message(json_msg)

        if self._enable_output_logging:
            if content[0] == "stdout" and isinstance(content[1], str):
                self.log_terminal_output(f"STDOUT: {content[1]}")

    def on_message(self, message):
        """Handle incoming websocket message

        We send JSON arrays, where the first element is a string indicating
        what kind of message this is. Data associated with the message follows.
        """
        # logging.info("TermSocket.on_message: %s - (%s) %s", self.term_name, type(message), len(message) if isinstance(message, bytes) else message[:250])
        command = json.loads(message)
        msg_type = command[0]
        assert self.terminal is not None
        if msg_type == "stdin":
            self.terminal.ptyproc.write(command[1])
            if self._enable_output_logging:
                if command[1] == "\r":
                    self.log_terminal_output(f"STDIN: {self._user_command}")
                    self._user_command = ""
                else:
                    self._user_command += command[1]
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
        """Terminal closed: tell the frontend, and close the socket."""
        self.send_json_message(["disconnect", 1])
        self.close()
        self.terminal = None

    def log_terminal_output(self, log: str = "") -> None:
        """
        Logs the terminal input/output
        :param log: log line to write
        :return:
        """
        self._logger.debug(log)
