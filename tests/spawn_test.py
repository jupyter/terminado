"""Tests for starting terminals without forking the server."""

# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.

import errno
import os
import signal
import sys

import pytest

if os.name == "nt":
    pytest.skip("Terminals on Windows do not fork", allow_module_level=True)

from terminado import _spawn
from terminado.management import PtyWithClients

requires_spawn = pytest.mark.skipif(
    not _spawn.available(), reason="Without os.posix_spawn(), terminals still fork"
)


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


def test_session_leader_with_controlling_terminal():
    script = (
        "import os; os.close(os.open('/dev/tty', os.O_RDWR));"
        "print(os.getsid(0) == os.getpid(), os.getpgrp() == os.getpid())"
    )
    assert output_of([sys.executable, "-c", script]).split() == ["True", "True"]


def test_ctrl_c_interrupts_the_program():
    terminal = PtyWithClients(["sh", "-c", "echo ready; exec sleep 30"], env=dict(os.environ))
    output = ""
    while "ready" not in output:
        output += terminal.ptyproc.read(65536)
    terminal.ptyproc.write("\x03")
    read_until_eof(terminal)
    terminal.ptyproc.wait()
    assert terminal.ptyproc.signalstatus == signal.SIGINT
    terminal.ptyproc.close()


def test_exit_status():
    terminal = PtyWithClients(["sh", "-c", "exit 3"], env=dict(os.environ))
    assert terminal.ptyproc.wait() == 3
    terminal.ptyproc.close()


def test_window_size():
    assert output_of(["stty", "size"]).split() == ["24", "80"]


def test_sigpipe_is_not_ignored():
    assert "survived" not in output_of(["sh", "-c", "kill -PIPE $$; echo survived"])


def test_file_descriptors_are_not_inherited():
    read_end, write_end = os.pipe()
    os.set_inheritable(write_end, True)
    try:
        script = f"import os\ntry:\n    os.fstat({write_end})\nexcept OSError:\n    print('closed')"
        assert output_of([sys.executable, "-c", script]).split() == ["closed"]
    finally:
        os.close(read_end)
        os.close(write_end)


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
