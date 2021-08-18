# basic_tests.py -- Basic unit tests for Terminado

# Copyright (c) Jupyter Development Team
# Copyright (c) 2014, Ramalingam Saravanan <sarava@sarava.net>
# Distributed under the terms of the Simplified BSD License.

from __future__ import absolute_import, print_function

import unittest
from terminado import *
import tornado
import tornado.httpserver
from tornado.httpclient import HTTPError
from tornado.ioloop import IOLoop
import tornado.testing
import datetime
import logging
import json
import os
import re
import signal
import pytest
from sys import platform

# We must set the policy for python >=3.8, see https://www.tornadoweb.org/en/stable/#installation
# Snippet from https://github.com/tornadoweb/tornado/issues/2608#issuecomment-619524992
import sys, asyncio
if sys.version_info[0]==3 and sys.version_info[1] >= 8 and sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#
# The timeout we use to assume no more messages are coming
# from the sever.
#
DONE_TIMEOUT = 1.0
os.environ['ASYNC_TEST_TIMEOUT'] = "20"     # Global test case timeout

MAX_TERMS = 3                               # Testing thresholds

class TestTermClient(object):
    """Test connection to a terminal manager"""
    def __init__(self, websocket):
        self.ws = websocket
        self.pending_read = None

    async def read_msg(self):

        # Because the Tornado Websocket client has no way to cancel
        # a pending read, we have to keep track of them...
        if self.pending_read is None:
            self.pending_read = self.ws.read_message()

        response = await self.pending_read
        self.pending_read = None
        if response:
            response = json.loads(response)
        return response

    async def read_all_msg(self, timeout=DONE_TIMEOUT):
        """Read messages until read times out"""
        msglist = []
        delta = datetime.timedelta(seconds=timeout)
        while True:
            try:
                mf = self.read_msg()
                msg = await tornado.gen.with_timeout(delta, mf)
            except tornado.gen.TimeoutError:
                return msglist

            msglist.append(msg)

    async def write_msg(self, msg):
        await self.ws.write_message(json.dumps(msg))

    async def read_stdout(self, timeout=DONE_TIMEOUT):
        """Read standard output until timeout read reached,
           return stdout and any non-stdout msgs received."""
        msglist = await self.read_all_msg(timeout)
        stdout = "".join([msg[1] for msg in msglist if msg[0] == 'stdout'])
        othermsg = [msg for msg in msglist if msg[0] != 'stdout']
        return (stdout, othermsg)

    async def write_stdin(self, data):
        """Write to terminal stdin"""
        await self.write_msg(['stdin', data])

    async def get_pid(self):
        """Get process ID of terminal shell process"""
        await self.read_stdout()                          # Clear out any pending
        await self.write_stdin("echo $$\r")
        (stdout, extra) = await self.read_stdout()
        if os.name == 'nt':
            print(repr(stdout))
            match = re.search(r'echo \$\$\\x1b\[71X\\x1b\[71C\\r\\n(\d+)', repr(stdout))
            if match is None:
                match = re.search(r'echo \$\$ \\r\\n(\d+)', repr(stdout))
            if match is None:
                match = re.search(
                    r'echo \$\$ \\r\\n\\x1b\[\?25h\\x1b\[\?25l(\d+)',
                    repr(stdout))
            pid = int(match.groups()[0])
        else:
            print('stdout=%r, extra=%r' % (stdout, extra))
            pid = int(stdout.split('\n')[1])
        return pid

    def close(self):
        self.ws.close()

class TermTestCase(tornado.testing.AsyncHTTPTestCase):

    # Factory for TestTermClient, because it has to be async
    # See:  https://github.com/tornadoweb/tornado/issues/1161
    async def get_term_client(self, path):
        port = self.get_http_port()
        url = 'ws://127.0.0.1:%d%s' % (port, path)
        request = tornado.httpclient.HTTPRequest(url,
                    headers={'Origin' : 'http://127.0.0.1:%d' % port})

        ws = await tornado.websocket.websocket_connect(request)
        return TestTermClient(ws)

    async def get_term_clients(self, paths):
        return await asyncio.gather(*(self.get_term_client(path) for path in paths))

    async def get_pids(self, tm_list):
        pids = []
        for tm in tm_list: # Must be sequential, in case terms are shared
            pid = await tm.get_pid()
            pids.append(pid)

        return pids

    def tearDown(self):
        run = IOLoop.current().run_sync
        run(self.named_tm.kill_all)
        run(self.single_tm.kill_all)
        run(self.unique_tm.kill_all)
        super().tearDown()

    def get_app(self):
        self.named_tm = NamedTermManager(
            shell_command=['bash'],
            max_terminals=MAX_TERMS,
        )
        
        self.single_tm = SingleTermManager(shell_command=['bash'])
        
        self.unique_tm = UniqueTermManager(
            shell_command=['bash'],
            max_terminals=MAX_TERMS,
        )

        named_tm = self.named_tm
        
        class NewTerminalHandler(tornado.web.RequestHandler):
            """Create a new named terminal, return redirect"""
            def get(self):
                name, terminal = named_tm.new_named_terminal()
                self.redirect("/named/" + name, permanent=False)

        return tornado.web.Application([
                    (r"/new",         NewTerminalHandler),
                    (r"/named/(\w+)", TermSocket, {'term_manager': self.named_tm}),
                    (r"/single",      TermSocket, {'term_manager': self.single_tm}),
                    (r"/unique",      TermSocket, {'term_manager': self.unique_tm})
                ], debug=True)

    test_urls = ('/named/term1', '/unique') + (('/single',) if os.name != 'nt' else tuple())

class CommonTests(TermTestCase):
    @tornado.testing.gen_test
    async def test_basic(self):
        for url in self.test_urls:
            tm = await self.get_term_client(url)
            response = await tm.read_msg()
            self.assertEqual(response, ['setup', {}])

            # Check for initial shell prompt
            response = await tm.read_msg()
            self.assertEqual(response[0], 'stdout')
            self.assertGreater(len(response[1]), 0)
            tm.close()

    @tornado.testing.gen_test
    async def test_basic_command(self):
        for url in self.test_urls:
            tm = await self.get_term_client(url)
            await tm.read_all_msg()
            await tm.write_stdin("whoami\n")
            (stdout, other) = await tm.read_stdout()
            if os.name == 'nt':
                assert 'whoami' in stdout
            else:
                assert stdout.startswith('who')
            assert other == []
            tm.close()

class NamedTermTests(TermTestCase):
    def test_new(self):
        response = self.fetch("/new", follow_redirects=False)
        self.assertEqual(response.code, 302)
        url = response.headers["Location"]

        # Check that the new terminal was created
        name = url.split('/')[2]
        self.assertIn(name, self.named_tm.terminals)

    @tornado.testing.gen_test
    async def test_namespace(self):
        names = ["/named/1"]*2 + ["/named/2"]*2
        tms = await self.get_term_clients(names)
        pids = await self.get_pids(tms)

        self.assertEqual(pids[0], pids[1])
        self.assertEqual(pids[2], pids[3])
        self.assertNotEqual(pids[0], pids[3])

    @tornado.testing.gen_test
    @pytest.mark.skipif('linux' not in platform, reason='It only works on Linux')
    async def test_max_terminals(self):
        urls = ["/named/%d" % i for i in range(MAX_TERMS+1)]
        tms = await self.get_term_clients(urls[:MAX_TERMS])
        pids = await self.get_pids(tms)

        # MAX_TERMS+1 should fail
        tm = await self.get_term_client(urls[MAX_TERMS])
        msg = await tm.read_msg()
        self.assertEqual(msg, None)             # Connection closed

class SingleTermTests(TermTestCase):
    @tornado.testing.gen_test
    async def test_single_process(self):
        tms = await self.get_term_clients(["/single", "/single"])
        pids = await self.get_pids(tms)
        self.assertEqual(pids[0], pids[1])

class UniqueTermTests(TermTestCase):
    @tornado.testing.gen_test
    async def test_unique_processes(self):
        tms = await self.get_term_clients(["/unique", "/unique"])
        pids = await self.get_pids(tms)
        self.assertNotEqual(pids[0], pids[1])

    @tornado.testing.gen_test
    @pytest.mark.skipif('linux' not in platform, reason='It only works on Linux')
    async def test_max_terminals(self):
        tms = await self.get_term_clients(['/unique'] * MAX_TERMS)
        pids = await self.get_pids(tms)
        self.assertEqual(len(set(pids)), MAX_TERMS)        # All PIDs unique

        # MAX_TERMS+1 should fail
        tm = await self.get_term_client("/unique")
        msg = await tm.read_msg()
        self.assertEqual(msg, None)             # Connection closed

        # Close one
        tms[0].close()
        msg = await tms[0].read_msg()           # Closed
        self.assertEquals(msg, None)

        # Should be able to open back up to MAX_TERMS
        tm = await self.get_term_client("/unique")
        msg = await tm.read_msg()
        self.assertEquals(msg[0], 'setup')

if __name__ == '__main__':
    unittest.main()
