#!/usr/bin/env python

""" pyxshell.py: pseudo-tty shell wrapper for terminals

Derived from the public-domain Ajaxterm code, v0.11 (2008-11-13).
  https://github.com/antonylesuisse/qweb
  http://antony.lesuisse.org/software/ajaxterm/
and susequently modified for GraphTerm as lineterm.py, v0.57.0 (2014-07-18)
  https://github.com/mitotic/graphterm

The contents of this file remain in the public-domain.

To test, run:

  ./pyxshell.py

Type exactly two Control-D's to exit the shell

"""

from __future__ import absolute_import, print_function, with_statement


import sys
if sys.version_info[0] < 3:
    byte_code = ord
else:
    byte_code = lambda x: x
    unicode = str

import codecs
import errno
import fcntl
import itertools
import logging
import os
import pty
import signal
import struct
import subprocess
import time
import termios
import tty

from ptyprocess import PtyProcessUnicode

import random
try:
    random = random.SystemRandom()
except NotImplementedError:
    import random


ENV_PREFIX = "PYXTERM_"         # Environment variable prefix
NO_COPY_ENV = set([])         # Do not copy these environment variables

DEFAULT_TERM_TYPE = "xterm"

IDLE_TIMEOUT = 300            # Idle timeout in seconds
UPDATE_INTERVAL = 0.05        # Fullscreen update time interval
CHUNK_BYTES = 4096            # Chunk size for receiving data in stdin

# Helper functions
def make_term_cookie():
    return "%016d" % random.randrange(10**15, 10**16)

def set_tty_speed(fd, baudrate=termios.B230400):
    tem_settings = termios.tcgetattr(fd)
    tem_settings[4:6] = (baudrate, baudrate)
    termios.tcsetattr(fd, termios.TCSADRAIN, tem_settings)

def set_tty_echo(fd, enabled):
    tem_settings = termios.tcgetattr(fd)
    if enabled:
        tem_settings[3] |= termios.ECHO
    else:
        tem_settings[3] &= ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSADRAIN, tem_settings)

def match_program_name(name):
    """ Return full path to command name, if running. else null string"""
    std_out = subprocess.check_output(["ps", "aux"], timeout=1, universal_newlines=True)
    for line in std_out.split('\n'):
        comps = line.split(None, 10)
        if not comps or not comps[-1].strip():
            continue
        cmd_comps = comps[-1].split()
        if cmd_comps[0].endswith("/"+name):
            return cmd_comps[0]
    return ""

class PtyWithClients(object):
    def __init__(self, ptyproc):
        self.ptyproc = ptyproc
        self.clients = []

class TermManagerBase(object):
    def __init__(self, shell_command, server_url="", term_settings={},
                 ioloop=None):
        self.shell_command = shell_command
        self.server_url = server_url
        self.term_settings = term_settings

        self.ptys_by_fd = {}

        if ioloop is not None:
            self.ioloop = ioloop
        else:
            import tornado.ioloop
            self.ioloop = tornado.ioloop.IOLoop.instance()
        
    def make_term_env(self, height=25, width=80, winheight=0, winwidth=0, **kwargs):
        env = os.environ.copy()
        env["TERM"] = self.term_settings.get("type",DEFAULT_TERM_TYPE)
        dimensions = "%dx%d" % (width, height)
        if winwidth and winheight:
            dimensions += ";%dx%d" % (winwidth, winheight)
        env[ENV_PREFIX+"DIMENSIONS"] = dimensions
        env["COLUMNS"] = str(width)
        env["LINES"] = str(height)

        if self.server_url:
            env[ENV_PREFIX+"URL"] = self.server_url

        return env

    def new_terminal(self, **kwargs):
        options = self.term_settings.copy()
        options['shell_command'] = self.shell_command
        options.update(kwargs)
        argv = options['shell_command']
        env = self.make_term_env(**options)
        pty = PtyProcessUnicode.spawn(argv, env=env, cwd=options.get('cwd', None))
        return PtyWithClients(pty)

    def start_reading(self, ptywclients):
        fd = ptywclients.ptyproc.fd
        self.ptys_by_fd[fd] = ptywclients
        self.ioloop.add_handler(fd, self.pty_read, self.ioloop.READ)

    def pty_read(self, fd, events=None):
        ptywclients = self.ptys_by_fd[fd]
        try:
            s = ptywclients.ptyproc.read(65536)
            for client in ptywclients.clients:
                client.on_pty_read(s)

        except EOFError:
            del self.ptys_by_fd[fd]
            self.ioloop.remove_handler(fd)
            for client in ptywclients.clients:
                client.on_pty_died()

    def get_terminal(self, url_component=None):
        raise NotImplementedError

    def shutdown(self):
        self.kill_all()

    def kill_all(self):
        raise NotImplementedError


class SingleTermManager(TermManagerBase):
    def __init__(self, **kwargs):
        super(SingleTermManager, self).__init__(**kwargs)
        self.terminal = None

    def get_terminal(self, url_component=None):
        if self.terminal is None:
            self.terminal = self.new_terminal()
            self.start_reading(self.terminal)
        return self.terminal

    def kill_all(self):
        if self.terminal is not None:
            self.terminal.ptyproc.kill(signal.SIGTERM)

def MaxTerminalsReached(Exception):
    def __init__(self, max_terminals):
        self.max_terminals = max_terminals
    
    def __str__(self):
        return "Cannot create more than %d terminals" % self.max_terminals

class UniqueTermManager(TermManagerBase):
    """Give each websocket a unique terminal to use."""
    def __init__(self, max_terminals=None, **kwargs):
        super(UniqueTermManager, self).__init__(**kwargs)
        self.max_terminals = max_terminals
        self.terminals = []

    def get_terminal(self, url_component=None):
        term = self.new_terminal()
        self.start_reading(term)
        self.terminals.append(term)
        return term

    def kill_all(self):
        for term in self.terminals:
            term.ptyproc.kill(signal.SIGTERM)
    

class NamedTermManager(TermManagerBase):
    """Share terminals between websockets connected to the same endpoint.
    """
    def __init__(self, max_terminals=None, **kwargs):
        super(NamedTermManager, self).__init__(**kwargs)
        self.max_terminals = max_terminals
        self.terminals = {}

    def get_terminal(self, term_name):
        assert term_name is not None
        
        if term_name in self.terminals:
            return self.terminals[term_name]
        
        if self.max_terminals and len(self.terminals) >= self.max_terminals:
            raise MaxTerminalsReached(self.max_terminals)

        # Create new terminal
        logging.info("New terminal %s: %s", term_name)
        term = self.new_terminal()
        self.terminals[term_name] = term
        self.start_reading(term)
        return term

    def _next_available_name(self):
        for n in itertools.count(start=1):
            name = "tty%d" % n
            if name not in self.terminals:
                return name

    def new_named_terminal(self):
        name = self._next_available_name()
        term = self.new_terminal()
        self.terminals[name] = term
        self.start_reading(term)
        return name, term

    def kill_all(self):
        for term in self.terminals.values():
            term.ptyproc.kill(signal.SIGTERM)

if __name__ == "__main__":
    ## Code to test Terminal on regular terminal
    ## Re-size terminal to 80x25 before testing

    from optparse import OptionParser
    usage = "usage: %prog [<shell_command>]"
    parser = OptionParser(usage=usage)
    parser.add_option("-l", "--logging",
                  action="store_true", dest="logging", default=False,
                  help="Enable logging")

    (options, args) = parser.parse_args()

    shell_cmd = args[:] if args else ["bash"]

    # Determine terminal width, height
    height, width = struct.unpack("hh", fcntl.ioctl(pty.STDOUT_FILENO, termios.TIOCGWINSZ, "1234"))
    if not width or not height:
        try:
            height, width = [int(os.getenv(var)) for var in ("LINES", "COLUMNS")]
        except Exception:
            height, width = 25, 80

    Prompt = "> "
    Log_file = "pyxshell.log" if options.logging else ""
    def client_callback(term_name, response_id, command, *args):
        if command == "stdout":
            output = args[0]
            sys.stdout.write(output)
            sys.stdout.flush()

    Term_manager = TermManager(client_callback, shell_cmd, log_file=Log_file, log_level=logging.INFO)
    terminal, Term_name, term_cookie = Term_manager.terminal(height=height, width=width)

    print("**Type Control-D Control-D to exit**", file=sys.stderr)

    test_str = b'\xe2\x94\x80 \xe2\x94\x82 \xe2\x94\x8c \xe2\x94\x98 \xe2\x94\x90 \xe2\x94\x94 \xe2\x94\x9c \xe2\x94\xa4 \xe2\x94\xac \xe2\x94\xb4 \xe2\x94\xbc \xe2\x95\x90 \xe2\x95\x91 \xe2\x95\x94 \xe2\x95\x9d \xe2\x95\x97 \xe2\x95\x9a \xe2\x95\xa0 \xe2\x95\xa3 \xe2\x95\xa6 \xe2\x95\xa9 \xe2\x95\xac'.decode("utf-8")

    Term_attr = termios.tcgetattr(pty.STDIN_FILENO)
    try:
        tty.setraw(pty.STDIN_FILENO)
        expectEOF = False
        terminal.pty_write("echo '%s'\n" % test_str)
        while True:
            ##data = raw_input(Prompt)
            ##Term_manager.write(data+"\n")
            data = os.read(pty.STDIN_FILENO, 1024)
            if byte_code(data[0]) == 4:
                if expectEOF: raise EOFError
                expectEOF = True
            else:
                expectEOF = False
            if not data:
                raise EOFError
            str_data = data.decode("utf-8") if isinstance(data, bytes) else data
            terminal.pty_write(str_data)
    except EOFError:
        Term_manager.shutdown()
    finally:
        # Restore terminal attributes
        termios.tcsetattr(pty.STDIN_FILENO, termios.TCSANOW, Term_attr)
