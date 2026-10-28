"""Tests for starting terminals without forking the server."""

# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.

import errno
import os
import signal
import subprocess
import sys
import threading

import pytest

if os.name == "nt":
    pytest.skip("Terminals on Windows do not fork", allow_module_level=True)

from terminado import _spawn
from terminado.management import PtyWithClients

requires_spawn = pytest.mark.skipif(
    not _spawn.available(), reason="Without os.posix_spawn(), terminals still fork"
)

# Prints "ready", then waits until a signal stops it.
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


@requires_spawn
def test_does_not_fork(monkeypatch):
    def fail():
        msg = "the server forked"
        raise AssertionError(msg)

    monkeypatch.setattr(os, "fork", fail)
    monkeypatch.setattr(os, "forkpty", fail)
    assert "hello" in output_of(["sh", "-c", "echo hello"])


def test_cwd_and_env(tmp_path):
    output = output_of(
        ["sh", "-c", "pwd -P; echo $GREETING"],
        env={**os.environ, "GREETING": "hello"},
        cwd=str(tmp_path),
    )
    assert output.split() == [os.path.realpath(tmp_path), "hello"]


@pytest.mark.parametrize("lc_ctype", [None, "C"])
def test_c_locale_in_env_reaches_the_shell_unchanged(lc_ctype):
    # When env selects the C locale, CPython sets LC_CTYPE in its own environment
    # (PEP 538), but the shell must get the value from env.
    env = {"PATH": os.environ["PATH"]}
    if lc_ctype is not None:
        env["LC_CTYPE"] = lc_ctype
    output = output_of(["sh", "-c", 'echo "${LC_CTYPE-unset}"'], env=env)
    assert output.split() == [lc_ctype or "unset"]


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


def test_exit_status():
    terminal = PtyWithClients(["sh", "-c", "exit 3"], env=dict(os.environ))
    assert terminal.ptyproc.wait() == 3
    terminal.ptyproc.close()


def test_window_size():
    assert output_of(["stty", "size"]).split() == ["24", "80"]


def test_sigpipe_is_not_ignored():
    assert "survived" not in output_of(["sh", "-c", "kill -PIPE $$; echo survived"])


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
def test_missing_cwd(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError) as error:
        PtyWithClients(["sh"], cwd=str(missing))
    assert error.value.filename == str(missing)


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
def test_falls_back_to_fork(monkeypatch):
    monkeypatch.setattr(_spawn, "available", lambda: False)
    assert "hello" in output_of(["sh", "-c", "echo hello"])


@requires_spawn
@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
def test_falls_back_to_fork_when_the_helper_does_not_start(monkeypatch, tmp_path):
    # For example, a relocated interpreter that needs PYTHONHOME does not start with -I.
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\nexit 1\n")
    python.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))
    assert "hello" in output_of(["sh", "-c", "echo hello"])
