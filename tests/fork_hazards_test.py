"""Opening a terminal must not run code that belongs to other threads of the server.

With fork(), the child is a copy of the server with only the calling thread. Before
the shell starts, Python frees what the other threads owned, so their finalizers run
in the copy, which can hang on a lock or change files that the server still uses.
"""

# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.

import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(
    not hasattr(os, "posix_spawn"), reason="Without os.posix_spawn(), terminals still fork"
)


def run_script(script, cwd):
    """Run ``script`` in a new interpreter and return its output."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_lock_held_by_another_thread_does_not_hang(tmp_path):
    script = r"""
    import logging
    import os
    import pty
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from terminado.management import PtyWithClients

    # A stuck child never calls exec, so kill it after a while to end the test.
    forked = []
    original_fork = pty.fork

    def fork():
        pid, fd = original_fork()
        if pid:
            forked.append(pid)
        return pid, fd

    pty.fork = fork

    def watchdog():
        time.sleep(15)
        print("timed out", flush=True)
        for pid in forked:
            os.kill(pid, 9)

    threading.Thread(target=watchdog, daemon=True).start()

    logging.basicConfig(filename="server.log", level=logging.INFO)
    log = logging.getLogger("extension")


    class Session:
        def __del__(self):
            log.info("session closed")


    local = threading.local()


    def handle_request():
        local.session = Session()


    def log_progress():
        while True:
            log.info("working")


    executor = ThreadPoolExecutor()
    executor.submit(handle_request).result()
    threading.Thread(target=log_progress, daemon=True).start()
    time.sleep(1)

    PtyWithClients(["true"], env=dict(os.environ))
    print("started", flush=True)
    os._exit(0)
    """
    assert run_script(script, tmp_path) == "started\n"


def test_objects_of_other_threads_are_not_finalized(tmp_path):
    script = r"""
    import os
    import tempfile
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from terminado.management import PtyWithClients

    local = threading.local()


    def export_row(i):
        if not hasattr(local, "workdir"):
            local.workdir = tempfile.TemporaryDirectory(dir=".")
            local.out = open("export.csv", "w")
        local.out.write(f"row {i}\n")
        return local.workdir.name


    def finish():
        local.out.close()


    executor = ThreadPoolExecutor(max_workers=1)
    for i in range(3):
        workdir = executor.submit(export_row, i).result()

    PtyWithClients(["true"], env=dict(os.environ))
    executor.submit(finish).result()
    print(os.path.exists(workdir))
    with open("export.csv") as f:
        print(f.read().splitlines(), flush=True)
    os._exit(0)
    """
    assert run_script(script, tmp_path) == "True\n['row 0', 'row 1', 'row 2']\n"
