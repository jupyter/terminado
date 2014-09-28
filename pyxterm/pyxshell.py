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

import errno
import fcntl
import itertools
import logging
import os
import pty
import re
import select
import signal
import struct
import subprocess
import traceback
import threading
import time
import termios
import tty

import random
try:
    random = random.SystemRandom()
except NotImplementedError:
    import random


ENV_PREFIX = "PYXTERM_"         # Environment variable prefix
NO_COPY_ENV = set([])         # Do not copy these environment variables

EXEC_DIR = ""                 # If specified, this subdirectory will be prepended to the PATH
File_dir = os.path.dirname(__file__)
Exec_path = os.path.join(File_dir, EXEC_DIR) if EXEC_DIR else ""

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

def setup_logging(log_level=logging.ERROR, filename="", file_level=None):
    file_level = file_level or log_level
    logger = logging.getLogger()
    logger.setLevel(min(log_level, file_level))

    formatter = logging.Formatter("%(levelname).1s%(asctime)s %(module).8s.%(lineno).04d %(message)s",
                                  "%y%m%d/%H:%M")

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(log_level)
            handler.setFormatter(formatter)
    else:
        # Console handler
        chandler = logging.StreamHandler()
        chandler.setLevel(log_level)
        chandler.setFormatter(formatter)
        logger.addHandler(chandler)

    if filename:
        # File handler
        fhandler = logging.FileHandler(filename)
        fhandler.setLevel(file_level)
        fhandler.setFormatter(formatter)
        logger.addHandler(fhandler)


class WithEvents(object):
    event_names = []
    def __init__(self):
        self._event_callbacks = {name:set() for name in self.event_names}

    def register(self, event, callback):
        self._event_callbacks[event].add(callback)

    def register_multi(self, events_callbacks):
        for event, callback in events_callbacks:
            self.register(event, callback)

    def unregister(self, event, callback):
        self._event_callbacks[event].discard(callback)

    def unregister_multi(self, events_callbacks):
        for event, callback in events_callbacks:
            self.unregister(event, callback)

    def unregister_all(self, event):
        self._event_callbacks[event].clear()

    def trigger(self, event, *args):
        err = None
        for callback in self._event_callbacks[event]:
            try:
                callback(*args)
            except Exception as e:
                err = e

        if err is not None:
            raise err

class Terminal(WithEvents):
    event_names = ['read', 'died']

    def __init__(self, fd, pid, manager, height=25, width=80, winheight=0, winwidth=0,
                 cookie=0, access_code="", log=False):
        super(Terminal, self).__init__()
        self.fd = fd
        self.pid = pid
        self.manager = manager
        self.width = width
        self.height = height
        self.winwidth = winwidth
        self.winheight = winheight
        self.cookie = cookie
        self.access_code = access_code
        self.term_encoding = manager.term_settings.get("encoding", "utf-8")
        self.log = log

        self.current_dir = ""
        self.update_buf = ""

        self.init()
        self.reset()
        self.rpc_set_size(height, width, winheight, winwidth)

        self.output_time = time.time()

    def init(self):
        pass

    def reset(self):
        pass

    def resize_buffer(self, height, width, winheight=0, winwidth=0, force=False):
        reset_flag = force or (self.width != width or self.height != height)
        self.winwidth = winwidth
        self.winheight = winheight
        if reset_flag:
            self.width = width
            self.height = height
            self.reset()

    def rpc_set_size(self, height, width, winheight=0, winwidth=0):
        # python bug http://python.org/sf/1112949 on amd64
        self.resize_buffer(height, width, winheight=winheight, winwidth=winwidth)
        # Hack for buggy TIOCSWINSZ handling: treat large unsigned positive int32 values as negative (same bits)
        winsz = termios.TIOCSWINSZ if termios.TIOCSWINSZ < 0 else struct.unpack('i',struct.pack('I',termios.TIOCSWINSZ))[0]
        fcntl.ioctl(self.fd, winsz, struct.pack("HHHH",height,width,0,0))

    def remote_call(self, method, *args, **kwargs):
        bound_method = getattr(self, "rpc_"+method, None)
        if not bound_method:
            raise Exception("Invalid remote method "+method)
        logging.info("Remote term call %s", method)
        return bound_method(*args, **kwargs)

    def clear(self):
        self.update_buf = ""

    def pty_write(self, data):
        assert isinstance(data, unicode), "Must write unicode data"
        raw_data = data.encode(self.term_encoding)
        nbytes = len(raw_data)
        offset = 0
        while offset < nbytes:
            # Need to break data up into chunks; otherwise it hangs the pty
            count = min(CHUNK_BYTES, nbytes-offset)
            retry = 50
            while count > 0:
                try:
                    sent = os.write(self.fd, raw_data[offset:offset+count])
                    if not sent:
                        raise Exception("Failed to write to terminal")
                    offset += sent
                    count -= sent
                except OSError as excp:
                    if excp.errno != errno.EAGAIN:
                        raise excp
                    retry -= 1
                    if retry > 0:
                        time.sleep(0.01)
                    else:
                        raise excp

    def read_ready(self, fd, events):
        assert fd == self.fd
        data = os.read(self.fd, 65536)
        text = data.decode(self.term_encoding)
        self.trigger('read', text)

    def kill(self):
        try:
            os.close(self.fd)
            os.kill(self.pid, signal.SIGTERM)
        except (IOError, OSError):
            pass

        self.trigger('died')

class InvalidAccessCode(Exception):
    def __str__(self):
        return "Invalid terminal access code"

def MaxTerminalsReached(Exception):
    def __init__(self, max_terminals):
        self.max_terminals = max_terminals
    
    def __str__(self):
        return "Cannot create more than %d terminals" % self.max_terminals

class TermManager(object):
    def __init__(self, shell_command=[], ssh_host="", server_url="",
                 ioloop=None, term_settings={},
                 log_file="", log_level=logging.ERROR):
        """ Manages multiple terminals (create, communicate, destroy)
        """
        ##signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        self.shell_command = shell_command
        self.ssh_host = ssh_host
        self.server_url = server_url
        self.term_settings = term_settings
        if ioloop is not None:
            self.ioloop = ioloop
        else:
            import tornado.ioloop
            self.ioloop = tornado.ioloop.IOLoop.instance()
        self.log_file = log_file

        self.term_options = term_settings.get("options", {})

        if log_file:
            setup_logging(logging.WARNING, log_file, logging.INFO)
            print("Logging to file", log_file, file=sys.stderr)
    
        self.terminals = {}
        self.lock = threading.RLock()
        self.alive = 1
        self.check_kill_idle = False
        self.name_count = 0

    def terminal(self, term_name=None, height=25, width=80, winheight=0, winwidth=0, parent="",
                 access_code="", shell_command=[], callbacks=[], ssh_host=""):
        """Return (tty_name, cookie, alert_msg) for existing or newly created pty"""
        shell_command = shell_command or self.shell_command
        ssh_host = ssh_host or self.ssh_host
        with self.lock:
            if term_name:
                term = self.terminals.get(term_name)
                if term:
                    # Existing terminal; resize and return it
                    if term.access_code and term.access_code != access_code:
                        raise InvalidAccessCode
                    term.rpc_set_size(height, width, winheight, winwidth)
                    term.register_multi(callbacks)
                    return (term, term_name, term.cookie)

            else:
                # New default terminal name
                term_name = self._next_available_name()

            # Create new terminal
            max_terminals = self.term_settings.get("max_terminals",0)
            if max_terminals and len(self.terminals) >= max_terminals:
                raise MaxTerminalsReached(max_terminals)
            cookie = make_term_cookie()
            logging.info("New terminal %s: %s", term_name, shell_command)

            term_dir = ""
            if parent:
                parent_term = self.terminals.get(parent)
                if parent_term:
                    term_dir = parent_term.current_dir or ""

            pid, fd = pty.fork()
            if pid == 0:
                ##logging.info("Forked pid=0 %s: %s", term_name, shell_command)
                env = dict(self.term_env(term_name, cookie, height, width, winheight, winwidth))
                env["COLUMNS"] = str(width)
                env["LINES"] = str(height)
                self._exec_new_terminal(shell_command, working_dir=term_dir,
                                        add_to_env=env, ssh_host=ssh_host)
            else:
                logging.info("Forked pid=%d %s", pid, term_name)
                fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd,fcntl.F_GETFL)|os.O_NONBLOCK)
                term = Terminal(fd, pid, self, height=height, width=width,
                                winheight=winheight, winwidth=winwidth,
                                cookie=cookie, access_code=access_code,
                                log=bool(self.log_file))

                self.terminals[term_name] = term
                term.register_multi(callbacks)
                term.register('died', lambda : self.ioloop.remove_handler(term.fd))
                self.ioloop.add_handler(term.fd, term.read_ready, self.ioloop.READ)
                return term, term_name, cookie

    def _next_available_name(self):
        for n in itertools.count(start=1):
            name = "tty%d" % n
            if name not in self.terminals:
                return name

    def _exec_new_terminal(self, shell_command, working_dir="~",
                           add_to_env=None, ssh_host=None):
        """This is run in the child process after forking.
        
        It ends by calling :func:`os.execvpe` to launch the desired process.
        """
        if len(shell_command) == 1 and not os.path.isabs(shell_command[0]):
            # Relative path shell command with no arguments
            if shell_command[0] in ("bash", "csh", "ksh", "sh", "tcsh", "zsh"):
                # Standard shell
                cmd = shell_command[:]

            elif shell_command[0] == "login":
                # Login access
                time.sleep(0.3)      # Needed for PTY output to appear
                if os.getuid() != 0:
                    logging.error("Must be root to run login")
                    os._exit(1)
                if os.path.exists("/bin/login"):
                    cmd = ['/bin/login']
                elif os.path.exists("/usr/bin/login"):
                    cmd = ['/usr/bin/login']
                else:
                    logging.error("/bin/login or /usr/bin/login not found")
                    os._exit(1)

            elif shell_command[0] == "ssh":
                # SSH access
                time.sleep(0.3)      # Needed for PTY output to appear
                sys.stderr.write("SSH Authentication\n")
                hostname = ssh_host or "localhost"
                if hostname != "localhost":
                    sys.stdout.write("Hostname: %s\n" % hostname)
                sys.stdout.write("Username: ")
                username = sys.stdin.readline().strip()
                if re.match('^[0-9A-Za-z-_. ]+$', username):
                    cmd = ['ssh']
                    cmd += ['-oPreferredAuthentications=keyboard-interactive,password']
                    cmd += ['-oNoHostAuthenticationForLocalhost=yes']
                    cmd += ['-oLogLevel=FATAL']
                    cmd += ['-F/dev/null', '-l', username, ssh_host]
                else:
                    logging.error("Invalid username %s", username)
                    os._exit(1)

            else:
                # Non-standard program; run via shell
                cmd = ['/bin/sh', '-c', shell_command[0]]

        elif shell_command and os.path.isabs(shell_command[0]):
            # Absolute path shell command
            cmd = shell_command[:]

        else:
            logging.error("Invalid shell command: %s", shell_command)
            os._exit(1)

        env = {}
        for var in os.environ.keys():
            if var not in NO_COPY_ENV:
                val = os.getenv(var)
                env[var] = val
                if var == "PATH" and Exec_path and Exec_path not in env[var]:
                    # Prepend app bin directory to path
                    env[var] = Exec_path + ":" + env[var]
        if add_to_env is not None:
            env.update(add_to_env)

        try:
            os.chdir(working_dir)
        except Exception:
            os.chdir(os.path.expanduser("~"))

        ##logging.info("Exec %s: %s", cmd, env)

        # Close all open fd (except stdin, stdout, stderr)
        try:
            fdl = [int(i) for i in os.listdir('/proc/self/fd')]
        except OSError:
            fdl = range(256)
        for i in [i for i in fdl if i>2]:
            try:
                os.close(i)
            except OSError:
                pass

        # Exec shell
        os.execvpe(cmd[0], cmd, env)

    def term_env(self, term_name, cookie, height, width, winheight, winwidth, export=False):
        env = []
        env.append( ("TERM", self.term_settings.get("type",DEFAULT_TERM_TYPE)) )
        env.append( (ENV_PREFIX+"COOKIE", str(cookie)) )
        dimensions = "%dx%d" % (width, height)
        if winwidth and winheight:
            dimensions += ";%dx%d" % (winwidth, winheight)
        env.append( (ENV_PREFIX+"DIMENSIONS", dimensions) )

        if self.server_url:
            env.append( (ENV_PREFIX+"URL", self.server_url) )

        env.append( (ENV_PREFIX+"DIR", File_dir) )

        return env

    def term_names(self):
        with self.lock:
            return list(self.terminals.keys())

    def running(self):
        with self.lock:
            return self.alive

    def shutdown(self):
        with self.lock:
            if not self.alive:
                return
            self.alive = 0
            self.kill_all()

    def kill_all(self):
        with self.lock:
            for term in self.terminals.values():
                term.kill()

    def kill_idle(self):
        # Kill all "idle" terminals
        with self.lock:
            cur_time = time.time()
            for term_name in self.term_names():
                term = self.terminals.get(term_name)
                if term:
                    if (cur_time-term.output_time) > IDLE_TIMEOUT:
                        logging.warning("kill_idle: %s", term_name)
                        term.kill()
                        try:
                            del self.terminals[term_name]
                        except Exception:
                            pass

    def loop(self):
        """ Multi-terminal I/O loop"""
        while self.running():
            try:
                fd_dict = dict((term.fd, name) for name, term in self.terminals.items())
                if not fd_dict:
                    time.sleep(0.02)
                    continue
                inputs, outputs, errors = select.select(fd_dict.keys(), [], [], 0.02)
                for fd in inputs:
                    try:
                        self.term_read(fd_dict[fd])
                    except Exception as excp:
                        traceback.print_exc()
                        term_name = fd_dict[fd]
                        logging.warning("TermManager.loop: INTERNAL READ ERROR (%s) %s", term_name, excp)
                        self.kill_term(term_name)
                cur_time = time.time()
                for term_name in fd_dict.values():
                    term = self.terminals.get(term_name)
                    if term:
                        if term.needs_updating(cur_time):
                            try:
                                self.term_update(term_name)
                            except Exception as excp:
                                traceback.print_exc()
                                logging.warning("TermManager.loop: INTERNAL UPDATE ERROR (%s) %s", term_name, excp)
                                self.kill_term(term_name)
                if self.check_kill_idle:
                    self.check_kill_idle = False
                    self.kill_idle()

                if len(inputs):
                    time.sleep(0.002)
            except Exception as excp:
                traceback.print_exc()
                logging.warning("TermManager.loop: ERROR %s", excp)
                break
        self.kill_all()

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
