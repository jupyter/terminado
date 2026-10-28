"""Tests for starting terminals without forking the server."""

# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.

import errno
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

if os.name == "nt":
    pytest.skip("Terminals on Windows do not fork", allow_module_level=True)

from terminado import _spawn
from terminado.management import PtyWithClients

requires_spawn = pytest.mark.skipif(
    not _spawn.available(), reason="_spawn.available() is False, so terminals still fork"
)

# Prints "ready", then sleeps for 30 s or until a signal stops it.
SLEEPER = ["sh", "-c", "echo ready; exec sleep 30"]

# Prints the file descriptors above 2 that are open in the program.
LIST_OPEN_DESCRIPTORS = """\
import os
for fd in range(3, 1024):
    try:
        os.fstat(fd)
    except OSError:
        continue
    print(fd)
"""

# Runs in the helper before HELPER. The helper then sees the file descriptor directories
# of FreeBSD without fdescfs: there is no /proc/self/fd, and /dev/fd lists only 0, 1 and 2.
FREEBSD_WITHOUT_FDESCFS = """\
import os, sys
sys.platform = "freebsd14"
real_isdir, real_listdir = os.path.isdir, os.listdir
def isdir(path):
    return path != "/proc/self/fd" and real_isdir(path)
def listdir(path):
    if path == "/proc/self/fd":
        raise FileNotFoundError(path)
    return ["0", "1", "2"] if path == "/dev/fd" else real_listdir(path)
os.path.isdir, os.listdir = isdir, listdir
"""

# Runs in a new interpreter with file descriptors 0 to 3 closed, so the terminal and the
# error pipe of the first terminal get numbers that the child replaces. Writes the file
# name in the error of the first terminal and the output of a second terminal to
# result.txt.
WITHOUT_STANDARD_DESCRIPTORS = """\
import os
os.closerange(0, 4)
from terminado.management import PtyWithClients
output = ""
try:
    PtyWithClients(["sh"], cwd="missing", env=dict(os.environ))
except FileNotFoundError as error:
    output += error.filename + " "
terminal = PtyWithClients(["sh", "-c", "echo hello"], env=dict(os.environ))
try:
    while True:
        output += terminal.ptyproc.read(65536)
except EOFError:
    pass
with open("result.txt", "w") as f:
    f.write(output)
"""

# Opens a terminal without `env` on the fork path, and prints the output of the terminal.
# The test runs this script in a new interpreter, because a child of the fork that fails
# before `exec` continues to run the code that opened the terminal. In the test process,
# the child would run the other tests.
FORK_WITHOUT_ENV = """\
from terminado import _spawn
from terminado.management import PtyWithClients
_spawn.available = lambda: False
terminal = PtyWithClients(["sh", "-c", "echo $GREETING"])
output = ""
try:
    while True:
        output += terminal.ptyproc.read(65536)
except EOFError:
    pass
print(output)
"""

# This script runs in a new session. Like a Jupyter server, the script handles SIGINT
# itself. It sends SIGINT to its own process group right after posix_spawn() starts the
# helper, as Ctrl-C in the terminal of the server does. Then it writes the output of the
# terminal to result.txt.
CTRL_C_IN_THE_SERVER = """\
import os, signal
from terminado import _spawn
from terminado.management import PtyWithClients
signal.signal(signal.SIGINT, lambda *args: None)
# Run the check in available() now, so that the check does not get the SIGINT.
assert _spawn.available()
real_posix_spawn = os.posix_spawn
def posix_spawn(*args, **kwargs):
    pid = real_posix_spawn(*args, **kwargs)
    os.killpg(os.getpgrp(), signal.SIGINT)
    return pid
os.posix_spawn = posix_spawn
terminal = PtyWithClients(["sh", "-c", "echo started"], env=dict(os.environ))
output = ""
try:
    while True:
        output += terminal.ptyproc.read(65536)
except EOFError:
    pass
with open("result.txt", "w") as f:
    f.write(output)
"""


def read_until_eof(terminal):
    """Return everything that the terminal prints until its program exits."""
    chunks = []
    while True:
        try:
            chunks.append(terminal.ptyproc.read(65536))
        except EOFError:
            return "".join(chunks)


def output_of(argv, **kwargs):
    """Run `argv` in a new terminal and return everything that the terminal printed."""
    kwargs.setdefault("env", dict(os.environ))
    terminal = PtyWithClients(argv, **kwargs)
    output = read_until_eof(terminal)
    terminal.ptyproc.close()
    return output


def open_descriptors():
    """Return the file descriptors above 2 that are open in a program in a new terminal.

    While the terminal starts, this process has an inheritable file descriptor open.
    """
    read_end, write_end = os.pipe()
    os.set_inheritable(write_end, True)
    try:
        return output_of([sys.executable, "-c", LIST_OPEN_DESCRIPTORS]).split()
    finally:
        os.close(read_end)
        os.close(write_end)


def stop_with_ctrl_c(terminal):
    """Press Ctrl-C when the program in the terminal is ready, and return its signal."""
    output = ""
    while "ready" not in output:
        output += terminal.ptyproc.read(65536)
    terminal.ptyproc.write("\x03")
    read_until_eof(terminal)
    terminal.ptyproc.wait()
    status = terminal.ptyproc.signalstatus
    terminal.ptyproc.close()
    return status


def survives(signal_name):
    """Return True if a shell in a new terminal survives a signal that it sends to itself."""
    # The default action of SIGXFSZ writes a core file, so turn core files off.
    script = f"ulimit -c 0; kill -{signal_name} $$; echo survived"
    return "survived" in output_of(["sh", "-c", script])


def has_exited(pid):
    """Return True if the process `pid` is gone within 10 s.

    A process is gone when it has exited and its parent has waited for it.
    """
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.01)
    return False


@requires_spawn
def test_does_not_fork(monkeypatch):
    def fail():
        msg = "the server forked"
        raise AssertionError(msg)

    monkeypatch.setattr(os, "fork", fail)
    monkeypatch.setattr(os, "forkpty", fail)
    assert "hello" in output_of(["sh", "-c", "echo hello"])


def test_cwd(tmp_path):
    output = output_of(["sh", "-c", "pwd -P"], cwd=str(tmp_path))
    assert output.split() == [os.path.realpath(tmp_path)]


def test_env():
    output = output_of(["sh", "-c", "echo $GREETING"], env={**os.environ, "GREETING": "hello"})
    assert output.split() == ["hello"]


@pytest.mark.parametrize("lc_ctype", [None, "C"])
def test_c_locale_in_env_reaches_the_shell_unchanged(lc_ctype):
    # When env selects the C locale, CPython sets LC_CTYPE in its own environment
    # (PEP 538), but the shell must get the value from env.
    env = {"PATH": os.environ["PATH"]}
    if lc_ctype is not None:
        env["LC_CTYPE"] = lc_ctype
    output = output_of(["sh", "-c", 'echo "${LC_CTYPE-unset}"'], env=env)
    assert output.split() == [lc_ctype or "unset"]


def test_pyvenv_launcher_in_env_reaches_the_shell_unchanged():
    # Since Python 3.11, CPython removes __PYVENV_LAUNCHER__ from its own environment when
    # it starts.
    env = {**os.environ, "__PYVENV_LAUNCHER__": sys.executable}
    output = output_of(["sh", "-c", 'echo "${__PYVENV_LAUNCHER__-unset}"'], env=env)
    assert output.strip() == sys.executable


def test_session_leader_with_controlling_terminal():
    script = (
        "import os; os.close(os.open('/dev/tty', os.O_RDWR));"
        "print(os.getsid(0) == os.getpid(), os.getpgrp() == os.getpid())"
    )
    assert output_of([sys.executable, "-c", script]).split() == ["True", "True"]


def test_ctrl_c_interrupts_the_program():
    terminal = PtyWithClients(SLEEPER, env=dict(os.environ))
    assert stop_with_ctrl_c(terminal) == signal.SIGINT


@requires_spawn
def test_blocked_signals_are_not_inherited():
    # The shell must not inherit the signal mask of the thread that opens the terminal.
    terminals = []

    def open_terminal():
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        terminals.append(PtyWithClients(SLEEPER, env=dict(os.environ)))

    thread = threading.Thread(target=open_terminal)
    thread.start()
    thread.join()
    assert stop_with_ctrl_c(terminals[0]) == signal.SIGINT


@requires_spawn
def test_ctrl_c_in_the_server_does_not_stop_the_helper(tmp_path):
    argv = [sys.executable, "-c", CTRL_C_IN_THE_SERVER]
    subprocess.run(argv, cwd=tmp_path, timeout=60, check=True, start_new_session=True)  # noqa: S603
    assert (tmp_path / "result.txt").read_text().split() == ["started"]


def test_exit_status():
    terminal = PtyWithClients(["sh", "-c", "exit 3"], env=dict(os.environ))
    assert terminal.ptyproc.wait() == 3
    terminal.ptyproc.close()


def test_window_size():
    assert output_of(["stty", "size"]).split() == ["24", "80"]


@pytest.mark.parametrize("name", ["PIPE", "XFSZ"])
def test_signal_is_not_ignored(name):
    assert not survives(name)


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
@pytest.mark.parametrize("name", ["PIPE", "XFSZ"])
def test_signal_is_not_ignored_after_fork(monkeypatch, name):
    monkeypatch.setattr(_spawn, "available", lambda: False)
    assert not survives(name)


def test_file_descriptors_are_not_inherited():
    assert open_descriptors() == []


@requires_spawn
def test_static_dev_fd_is_not_trusted(monkeypatch):
    monkeypatch.setattr(_spawn, "HELPER", FREEBSD_WITHOUT_FDESCFS + _spawn.HELPER)
    assert open_descriptors() == []


@requires_spawn
def test_server_without_standard_file_descriptors(tmp_path):
    argv = [sys.executable, "-c", WITHOUT_STANDARD_DESCRIPTORS]
    subprocess.run(argv, cwd=tmp_path, timeout=60, check=True)  # noqa: S603
    assert (tmp_path / "result.txt").read_text().split() == ["missing", "hello"]


def test_missing_command():
    with pytest.raises(FileNotFoundError):
        PtyWithClients(["terminado-no-such-command"])


def test_invalid_executable(tmp_path):
    program = tmp_path / "not-a-program"
    program.write_text("not a program")
    program.chmod(0o755)
    with pytest.raises(OSError, match="Exec format error") as error:
        PtyWithClients([str(program)], env=dict(os.environ))
    assert error.value.errno == errno.ENOEXEC


@requires_spawn
@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("raise RuntimeError('broken')", "code 1 before .*: RuntimeError: broken$"),
        ("import os; os.kill(os.getpid(), 9)", "code -9 before"),
    ],
)
def test_helper_that_exits_before_exec(monkeypatch, code, message):
    # For example, the interpreter does not start, or a signal ends the helper.
    monkeypatch.setattr(_spawn, "HELPER", f"{code}\n{_spawn.HELPER}")
    with pytest.raises(OSError, match=message):
        PtyWithClients(["sh", "-c", "echo started"], env=dict(os.environ))


@requires_spawn
@pytest.mark.parametrize(
    ("env", "message"),
    [({"A=B": "1"}, "illegal environment variable name"), ({"A": "1\0"}, "embedded null byte")],
)
def test_invalid_env_raises_in_the_caller(env, message):
    # On the fork path, the child of the fork gets this error and runs the rest of the tests.
    with pytest.raises(ValueError, match=message):
        PtyWithClients(["sh"], env=env)


@requires_spawn
def test_missing_cwd(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError) as error:
        PtyWithClients(["sh"], cwd=str(missing))
    assert error.value.filename == str(missing)


@requires_spawn
def test_waiting_for_the_helper_has_a_timeout(monkeypatch, tmp_path):
    # This wrapper runs Python as a child, so it keeps the error pipe open while the
    # command runs. A helper that waits in chdir() for a stalled network mount does the
    # same.
    python = tmp_path / "python"
    python.write_text(f'#!/bin/sh\n{shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(_spawn, "EXEC_TIMEOUT", 1)
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        PtyWithClients(["sleep", "5"], env=dict(os.environ))
    assert time.monotonic() - start < 4


@requires_spawn
@pytest.mark.parametrize("call", ["os.pipe", "selectors.DefaultSelector"])
def test_failed_open_leaves_no_terminal_and_no_helper(monkeypatch, call):
    # For example, the server has too many open files when it opens the error pipe, or when
    # it waits for the helper.
    terminals, helpers = [], []
    real_openpty, real_posix_spawn = os.openpty, os.posix_spawn

    def openpty():
        terminals.append(real_openpty())
        return terminals[-1]

    def posix_spawn(*args, **kwargs):
        helpers.append(real_posix_spawn(*args, **kwargs))
        return helpers[-1]

    def fail(*args):
        raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))

    monkeypatch.setattr(os, "openpty", openpty)
    monkeypatch.setattr(os, "posix_spawn", posix_spawn)
    monkeypatch.setattr(call, fail)
    with pytest.raises(OSError, match=os.strerror(errno.EMFILE)):
        PtyWithClients(SLEEPER, env=dict(os.environ))
    for fd in terminals[0]:
        with pytest.raises(OSError, match="Bad file descriptor"):
            os.fstat(fd)
    assert all(map(has_exited, helpers))


@requires_spawn
def test_env_without_a_variable_that_python_needs(monkeypatch, tmp_path):
    # This wrapper needs a variable from the environment of the server to start Python. In
    # the same way, an interpreter can need LD_LIBRARY_PATH to find its shared libpython.
    # The environment of the terminal does not have the variable.
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\nexec "$TERMINADO_PYTHON" "$@"\n')
    python.chmod(0o755)
    monkeypatch.setenv("TERMINADO_PYTHON", sys.executable)
    monkeypatch.setattr(sys, "executable", str(python))
    env = {key: value for key, value in os.environ.items() if key != "TERMINADO_PYTHON"}
    assert output_of(["sh", "-c", "echo hello"], env=env).split() == ["hello"]


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
def test_falls_back_to_fork(monkeypatch):
    monkeypatch.setattr(_spawn, "available", lambda: False)
    assert "hello" in output_of(["sh", "-c", "echo hello"])


def test_fork_without_env_inherits_the_environment():
    argv = [sys.executable, "-c", FORK_WITHOUT_ENV]
    env = {**os.environ, "GREETING": "hello"}
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603
    assert result.stdout.split() == ["hello"]


@requires_spawn
@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
@pytest.mark.parametrize("script", ["exit 1", "exit 0", "exec sleep 30"])
def test_falls_back_to_fork_when_the_helper_does_not_start(monkeypatch, tmp_path, script):
    # For example, a relocated interpreter that needs PYTHONHOME does not start with -I. A
    # program that is not Python, for example an application that Nuitka compiled, can exit
    # with 0 or not exit at all.
    python = tmp_path / "python"
    python.write_text(f"#!/bin/sh\n{script}\n")
    python.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(_spawn, "EXEC_TIMEOUT", 1)
    assert "hello" in output_of(["sh", "-c", "echo hello"])
