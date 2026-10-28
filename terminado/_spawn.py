"""Start a process in a new pseudo-terminal without forking this process.

fork() makes a child process with only one thread: the thread that called fork(). The
child also has a copy of all the memory of this process, including the thread-local
objects of the other threads. Before the child calls `exec`, Python frees these objects, so
their finalizers run in the child. Python also calls the functions registered with
os.register_at_fork(). These finalizers and functions come from extensions and libraries.
They can wait forever for a lock, because the thread that held the lock does not exist in
the child.

Instead of fork(), spawn() uses os.posix_spawn() to start a small helper interpreter. The
helper sets up the terminal and then calls `exec`, so no code from this process runs in the
child.
"""

# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.
from __future__ import annotations

import os
import shutil
import struct
import sys
from collections.abc import Mapping, Sequence
from typing import Any

if sys.platform != "win32":
    import fcntl
    import termios

# spawn() starts the helper as `python -I -S -c HELPER cwd command [arg ...]`.
# File descriptors 0, 1 and 2 are the terminal, and file descriptor 3 is the write end
# of the error pipe. The helper closes only the file descriptors that it finds in
# /proc/self/fd or /dev/fd, because os.closerange() can be slow. When Python cannot use
# close_range(), os.closerange() calls close() for every number up to the limit, and
# this takes more than 100 ms when the limit is high.
HELPER = """\
import fcntl, os, signal, sys, termios
cwd, command, *args = sys.argv[1:]
try:
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    if cwd:
        os.chdir(cwd)
    for name in ("SIGPIPE", "SIGXFSZ"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_DFL)
    try:
        fds = os.listdir("/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd")
    except OSError:
        max_fd = os.sysconf("SC_OPEN_MAX")
        os.closerange(4, max_fd if 0 < max_fd < 1048576 else 1048576)
    else:
        for fd in map(int, fds):
            if fd > 3:
                try:
                    os.close(fd)
                except OSError:
                    pass
    fcntl.fcntl(3, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
    os.execv(command, [command, *args])
except OSError as e:
    os.write(3, ("%d:%s" % (e.errno or 0, e.filename or "")).encode("utf-8", "surrogateescape"))
    os._exit(127)
"""


def available() -> bool:
    """Return True if spawn() can start a terminal without forking this process."""
    return (
        os.name == "posix"
        and hasattr(os, "posix_spawn")
        and not getattr(sys, "frozen", False)
        and bool(sys.executable)
        and os.access(sys.executable, os.X_OK)
    )


def _above_targets(fd: int) -> int:
    """Return `fd` if it is above 3. Otherwise, move `fd` above 3 and return the new number.

    In the child, posix_spawn() replaces file descriptors 0 to 3.
    """
    if fd > 3:
        return fd
    copy = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 4)
    os.close(fd)
    return copy


def spawn(
    cls: Any,
    argv: Sequence[str],
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    dimensions: tuple[int, int] = (24, 80),
) -> Any:
    """Start `argv` in a new pseudo-terminal and return a `cls` instance for the new process.

    Use this function instead of cls.spawn(), where `cls` is ptyprocess.PtyProcess or a
    subclass of it. The result is the same as with pty.fork(): the child is the leader of
    a new session, and the terminal is the controlling terminal of the child. If the child
    fails before `exec`, for example because the directory `cwd` does not exist, this
    function raises OSError.
    """
    if not isinstance(argv, (list, tuple)):
        msg = f"Expected a list or tuple for argv, got {argv!r}"
        raise TypeError(msg)
    command = shutil.which(argv[0])
    if command is None:
        msg = f"The command was not found or was not executable: {argv[0]}."
        raise FileNotFoundError(msg)

    master, slave = os.openpty()
    slave = _above_targets(slave)
    error_read, error_write = os.pipe()
    error_write = _above_targets(error_write)
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", *dimensions, 0, 0))
        pid = os.posix_spawn(
            sys.executable,
            [sys.executable, "-I", "-S", "-c", HELPER, cwd or "", command, *argv[1:]],
            os.environ if env is None else env,
            file_actions=[
                (os.POSIX_SPAWN_DUP2, slave, 0),
                (os.POSIX_SPAWN_DUP2, slave, 1),
                (os.POSIX_SPAWN_DUP2, slave, 2),
                (os.POSIX_SPAWN_DUP2, error_write, 3),
            ],
            setsigmask=(),
        )
    except BaseException:
        os.close(master)
        os.close(error_read)
        raise
    finally:
        os.close(slave)
        os.close(error_write)

    # The read returns no data when `exec` succeeds, because `exec` closes the write end
    # of the pipe. When the helper fails, the read returns the error that the helper wrote.
    try:
        error = os.read(error_read, 4096)
    finally:
        os.close(error_read)
    if error:
        os.close(master)
        os.waitpid(pid, 0)
        code, _, filename = error.decode("utf-8", "surrogateescape").partition(":")
        raise OSError(int(code), os.strerror(int(code)), filename or None)

    inst = cls(pid, master)
    inst.argv = [command, *argv[1:]]
    if env is not None:
        inst.env = env
    if cwd is not None:
        inst.launch_dir = cwd
    return inst
