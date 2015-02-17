"""Terminal management for exposing terminals to a web interface using Tornado.
"""
from __future__ import absolute_import, print_function

import sys
if sys.version_info[0] < 3:
    byte_code = ord
else:
    byte_code = lambda x: x
    unicode = str

from collections import deque
import itertools
import logging
import os
import signal

from ptyprocess import PtyProcessUnicode
from tornado import gen
from tornado.ioloop import IOLoop

ENV_PREFIX = "PYXTERM_"         # Environment variable prefix

DEFAULT_TERM_TYPE = "xterm"

class PtyWithClients(object):
    def __init__(self, ptyproc):
        self.ptyproc = ptyproc
        self.clients = []
        # Store the last few things read, so when a new client connects,
        # it can show e.g. the most recent prompt, rather than absolutely
        # nothing.
        self.read_buffer = deque([], maxlen=10)

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
    
    @gen.coroutine
    def terminate(self, force=False):
        '''This forces a child process to terminate. It starts nicely with
        SIGHUP and SIGINT. If "force" is True then moves onto SIGKILL. This
        returns True if the child was terminated. This returns False if the
        child could not be terminated. '''
        
        loop = IOLoop.current()
        sleep = lambda : gen.Task(loop.add_timeout, loop.time() + self.ptyproc.delayafterterminate)

        if not self.ptyproc.isalive():
            raise gen.Return(True)
        try:
            self.kill(signal.SIGHUP)
            yield sleep()
            if not self.ptyproc.isalive():
                raise gen.Return(True)
            self.kill(signal.SIGCONT)
            yield sleep()
            if not self.ptyproc.isalive():
                raise gen.Return(True)
            self.kill(signal.SIGINT)
            yield sleep()
            if not self.ptyproc.isalive():
                raise gen.Return(True)
            self.kill(signal.SIGTERM)
            yield sleep()
            if not self.ptyproc.isalive():
                raise gen.Return(True)
            if force:
                self.kill(signal.SIGKILL)
                yield sleep()
                if not self.ptyproc.isalive():
                    raise gen.Return(True)
                else:
                    raise gen.Return(False)
            raise gen.Return(False)
        except OSError:
            # I think there are kernel timing issues that sometimes cause
            # this to happen. I think isalive() reports True, but the
            # process is dead to the kernel.
            # Make one last attempt to see if the kernel is up to date.
            yield sleep()
            if not self.ptyproc.isalive():
                raise gen.Return(True)
            else:
                raise gen.Return(False)

class TermManagerBase(object):
    """Base class for a terminal manager."""
    def __init__(self, shell_command, server_url="", term_settings={},
                 ioloop=None):
        self.shell_command = shell_command
        self.server_url = server_url
        self.term_settings = term_settings
        self.log = logging.getLogger(__name__)

        self.ptys_by_fd = {}

        if ioloop is not None:
            self.ioloop = ioloop
        else:
            import tornado.ioloop
            self.ioloop = tornado.ioloop.IOLoop.instance()
        
    def make_term_env(self, height=25, width=80, winheight=0, winwidth=0, **kwargs):
        """Build the environment variables for the process in the terminal."""
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
        """Called when the pty has closed.
        """
        # Stop trying to read from that terminal
        fd = ptywclients.ptyproc.fd
        self.log.info("EOF on FD %d; stopping reading", fd)
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
            ptywclients.read_buffer.append(s)
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

    @gen.coroutine
    def shutdown(self):
        yield self.kill_all()

    @gen.coroutine
    def kill_all(self):
        futures = []
        for term in self.ptys_by_fd.values():
            futures.append(term.terminate(force=True))
        # wait for futures to finish
        for f in futures:
            yield f


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
    
    @gen.coroutine
    def kill_all(self):
        yield super(SingleTermManager, self).kill_all()
        self.terminal = None

class MaxTerminalsReached(Exception):
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
        self.log.info("Websocket closed, sending SIGHUP to terminal.")
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
        self.log.info("New terminal with specified name: %s", term_name)
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
        self.log.info("New terminal with automatic name: %s", name)
        term.term_name = name
        self.terminals[name] = term
        self.start_reading(term)
        return name, term

    def kill(self, name, sig=signal.SIGTERM):
        term = self.terminals[name]
        term.kill()   # This should lead to an EOF
    
    @gen.coroutine
    def terminate(self, name, force=False):
        term = self.terminals[name]
        yield term.terminate(force=force)
    
    def on_eof(self, ptywclients):
        super(NamedTermManager, self).on_eof(ptywclients)
        name = ptywclients.term_name
        self.log.info("Terminal %s closed", name)
        self.terminals.pop(name, None)
    
    @gen.coroutine
    def kill_all(self):
        yield super(NamedTermManager, self).kill_all()
        self.terminals = {}
