"""Start a command in a new session, with the terminal as its controlling terminal.

terminado._spawn starts the helper with os.posix_spawn(), as
`python -I -S -X utf8 -c CODE cwd command [arg ...]`. CODE is the text of this file, and
cwd is empty when the command starts in the directory of the server. File descriptors 0, 1
and 2 are the terminal, 3 is the write end of the error pipe, and 4 is the read end of the
environment pipe. With -X utf8, cwd and the arguments keep their bytes in every locale.
Without -X utf8, Python 3.14 and older can change or reject some of these bytes in a legacy
multibyte locale, for example ja_JP.eucJP.

Right before `exec`, the helper writes a NUL byte to the error pipe. When an OSError stops
the helper, the helper writes `errno:filename` and exits. EOF with no data means that the
helper exited for another reason, for example because a signal ended it.

The helper runs with the environment of the server, because _spawn.available() checked the
interpreter with this environment. With the environment of the command, the helper could
miss a variable that the interpreter needs (LD_LIBRARY_PATH), start differently even with
-I (PYTHONEXECUTABLE), or change LC_CTYPE before `exec` (PEP 538). The environment of the
command goes through the environment pipe, because other users can read the arguments of a
process.
"""

# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.

# Every import adds to the time that a terminal takes to open, so the helper imports only
# the modules that it needs.
import fcntl
import os
import signal
import sys
import termios

ERROR_PIPE = 3
ENVIRONMENT_PIPE = 4


def main() -> None:
    """Set up the terminal and start the command, or write the error to the error pipe."""
    cwd, command, *args = sys.argv[1:]
    try:
        # The environment pipe has a key, a NUL byte, a value and a NUL byte for each
        # variable. split() gives an empty field after the last NUL byte, and zip() drops
        # this field.
        data = b""
        while chunk := os.read(ENVIRONMENT_PIPE, 65536):
            data += chunk
        fields = data.split(b"\0")
        env = dict(zip(fields[::2], fields[1::2], strict=False))

        # Make the terminal the controlling terminal of a new session, as pty.fork() does.
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        if cwd:
            os.chdir(cwd)

        # Until setsid(), the helper is in the process group of the server, and Ctrl-C in
        # the terminal of the server sends SIGINT to this group. So _spawn starts the helper
        # with SIGINT blocked. posix_spawn(setsid=True) would make this unnecessary, but the
        # builds of Python that uv installs do not support it. SIG_IGN discards a pending
        # SIGINT.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        # `exec` keeps ignored signals ignored, and Python ignores SIGPIPE and SIGXFSZ.
        for name in ("SIGINT", "SIGPIPE", "SIGXFSZ"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), signal.SIG_DFL)
        signal.pthread_sigmask(signal.SIG_SETMASK, ())

        # Close every file descriptor above the error pipe, including the environment pipe.
        # The helper finds the open file descriptors in /proc/self/fd, or in /dev/fd on
        # macOS, because os.closerange() can take more than 100 ms: it calls close() for
        # every number up to the limit when close_range() is not available. On the BSDs,
        # /dev/fd can be a static directory.
        try:
            fds = os.listdir("/dev/fd" if sys.platform == "darwin" else "/proc/self/fd")
        except OSError:
            max_fd = os.sysconf("SC_OPEN_MAX")
            os.closerange(ERROR_PIPE + 1, max_fd if 0 < max_fd < 1048576 else 1048576)
        else:
            for fd in map(int, fds):
                if fd > ERROR_PIPE:
                    # The list includes the file descriptor of the directory, and
                    # os.listdir() has already closed it.
                    try:
                        os.close(fd)
                    except OSError:
                        pass

        # Because of FD_CLOEXEC, `exec` closes the error pipe. The server then reads the NUL
        # byte and EOF.
        fcntl.fcntl(ERROR_PIPE, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
        os.write(ERROR_PIPE, b"\0")
        os.execve(command, [command, *args], env)
    except OSError as e:
        os.write(ERROR_PIPE, b"%d:" % (e.errno or 0) + os.fsencode(e.filename or ""))
        os._exit(127)


if __name__ == "__main__":
    main()
