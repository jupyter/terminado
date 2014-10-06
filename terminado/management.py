"""Terminal management for exposing terminals to a web interface using Tornado.
"""
from __future__ import absolute_import, print_function, with_statement


import sys
if sys.version_info[0] < 3:
    byte_code = ord
else:
    byte_code = lambda x: x
    unicode = str

import itertools
import logging
import os
import signal
import subprocess
import termios

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

    def resize_to_smallest(self):
        """Set the terminal size to that of the smallest client dimensions.
        
        A terminal not using the full space available is much nicer than a
        terminal trying to use more than the available space, so we keep it 
        sized to the smallest client.
        """
        minrows = mincols = 10001
        for client in self.clients:
            rows, cols = client.size
            if rows is not None and rows < minrows:
                minrows = rows
            if cols is not None and cols < mincols:
                mincols = cols

        if minrows == 10001 or mincols == 10001:
            return
        
        rows, cols = self.ptyproc.getwinsize()
        if (rows, cols) != (minrows, mincols):
            self.ptyproc.setwinsize(minrows, mincols)

    def kill(self, sig=signal.SIGTERM):
        self.ptyproc.kill(sig)
        self.ptyproc.fileobj.close()

        for client in self.clients:
            client.on_pty_died()
        self.clients = []

class TermManagerBase(object):
    """Base class for a terminal manager."""
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
        """Make a new terminal, return a :class:`PtyWithClients` instance."""
        options = self.term_settings.copy()
        options['shell_command'] = self.shell_command
        options.update(kwargs)
        argv = options['shell_command']
        env = self.make_term_env(**options)
        pty = PtyProcessUnicode.spawn(argv, env=env, cwd=options.get('cwd', None))
        return PtyWithClients(pty)

    def start_reading(self, ptywclients):
        """Connect a terminal to the tornado event loop to read data from it."""
        fd = ptywclients.ptyproc.fd
        self.ptys_by_fd[fd] = ptywclients
        self.ioloop.add_handler(fd, self.pty_read, self.ioloop.READ)

    def on_eof(self, ptywclients):
        # Stop trying to read from that terminal
        fd = ptywclients.ptyproc.fd
        del self.ptys_by_fd[fd]
        self.ioloop.remove_handler(fd)
        os.close(fd)
        
        # This should reap the child process
        ptywclients.ptyproc.isalive()

    def pty_read(self, fd, events=None):
        """Called by the event loop when there is pty data ready to read."""
        ptywclients = self.ptys_by_fd[fd]
        try:
            s = ptywclients.ptyproc.read(65536)
            for client in ptywclients.clients:
                client.on_pty_read(s)
        except EOFError:
            self.on_eof(ptywclients)
            for client in ptywclients.clients:
                client.on_pty_died()

    def get_terminal(self, url_component=None):
        """Override in a subclass to give a terminal to a new websocket connection
        
        The :class:`TermSocket` handler works with zero or one URL components
        (capturing groups in the URL spec regex). If it receives one, it is
        passed as the ``url_component`` parameter; otherwise, this is None.
        """
        raise NotImplementedError

    def client_disconnected(self, websocket):
        """Override this to e.g. kill terminals on client disconnection.
        """
        pass

    def shutdown(self):
        self.kill_all()

    def kill_all(self):
        for term in self.ptys_by_fd.values():
            term.kill()


class SingleTermManager(TermManagerBase):
    """All connections to the websocket share a common terminal."""
    def __init__(self, **kwargs):
        super(SingleTermManager, self).__init__(**kwargs)
        self.terminal = None

    def get_terminal(self, url_component=None):
        if self.terminal is None:
            self.terminal = self.new_terminal()
            self.start_reading(self.terminal)
        return self.terminal

    def kill_all(self):
        super(SingleTermManager, self).kill_all()
        self.terminal = None

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

    def get_terminal(self, url_component=None):
        term = self.new_terminal()
        self.start_reading(term)
        return term

    def client_disconnected(self, websocket):
        """Send terminal SIGHUP when client disconnects."""
        websocket.terminal.kill(signal.SIGHUP)
    

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
        term.term_name = term_name
        self.terminals[term_name] = term
        self.start_reading(term)
        return term

    name_template = "%d"

    def _next_available_name(self):
        for n in itertools.count(start=1):
            name = self.name_template % n
            if name not in self.terminals:
                return name

    def new_named_terminal(self):
        name = self._next_available_name()
        term = self.new_terminal()
        self.terminals[name] = term
        self.start_reading(term)
        return name, term

    def kill(self, name, sig=signal.SIGTERM):
        term = self.terminals[name]
        term.kill()   # This should lead to an EOF

    def on_eof(self, ptywclients):
        super(NamedTermManager, self).on_eof(ptywclients)
        name = ptywclients.term_name
        self.terminals.pop(name, None)

    def kill_all(self):
        super(NamedTermManager, self).kill_all()
        self.terminals = {}
