#
# basic_tests.py -- Basic unit tests for Terminado
#

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

#
# The timeout we use to assume no more messages are coming
# from the sever.
#
DONE_TIMEOUT = 0.2

class TestTermClient(object):
    """Test connection to a terminal manager"""
    def __init__(self, websocket):
        self.ws = websocket
        self.pending_read = None

    @tornado.gen.coroutine
    def read_msg(self):

        # Because the Tornado Websocket client has no way to cancel
        # a pending read, we have to keep track of them...
        if self.pending_read is None:
            self.pending_read = self.ws.read_message()

        response = yield self.pending_read
        self.pending_read = None
        raise tornado.gen.Return(json.loads(response))

    @tornado.gen.coroutine
    def read_all_msg(self, timeout=DONE_TIMEOUT):
        """Read messages until read times out"""
        msglist = []
        delta = datetime.timedelta(seconds=timeout)
        while True:
            try:
                mf = self.read_msg()
                msg = yield tornado.gen.with_timeout(delta, mf)
            except tornado.gen.TimeoutError:
                raise tornado.gen.Return(msglist)

            msglist.append(msg)

    def write_msg(self, msg):
        self.ws.write_message(json.dumps(msg))

    @tornado.gen.coroutine
    def read_stdout(self, timeout=DONE_TIMEOUT):
        """Read standard output until timeout read reached,
           return stdout and any non-stdout msgs received."""
        msglist = yield self.read_all_msg(timeout)
        stdout = "".join([msg[1] for msg in msglist if msg[0] == 'stdout'])
        othermsg = [msg for msg in msglist if msg[0] != 'stdout']
        raise tornado.gen.Return((stdout, othermsg))

    def write_stdin(self, data):
        """Write to terminal stdin"""
        self.write_msg(['stdin', data])

    def close(self):
        self.ws.close()

class TermTestCase(tornado.testing.AsyncHTTPTestCase):
    @tornado.gen.coroutine

    # Factory for TestTermClient, because it has to be a Tornado co-routine.
    # See:  https://github.com/tornadoweb/tornado/issues/1161
    def get_term_client(self, path):
        port = self.get_http_port()
        url = 'ws://127.0.0.1:%d%s' % (port, path)
        request = tornado.httpclient.HTTPRequest(url,
                    headers={'Origin' : 'http://127.0.0.1:%d' % port})

        ws = yield tornado.websocket.websocket_connect(request)
        raise tornado.gen.Return(TestTermClient(ws))

class BasicTest(TermTestCase):
    def get_app(self):
        named_tm = NamedTermManager(shell_command=['bash'], ioloop=self.io_loop)
        single_tm = SingleTermManager(shell_command=['bash'], ioloop=self.io_loop)
        unique_tm = UniqueTermManager(shell_command=['bash'], ioloop=self.io_loop)
        return tornado.web.Application([
                    (r"/named/(\w+)", TermSocket, {'term_manager': named_tm}),
                    (r"/single",      TermSocket, {'term_manager': single_tm}),
                    (r"/unique",      TermSocket, {'term_manager': unique_tm})
                ], debug=True)

    test_urls = ('/named/term1', '/single', '/unique')

    @tornado.testing.gen_test
    def test_basic(self):
        for url in self.test_urls:
            tm = yield self.get_term_client(url)
            response = yield tm.read_msg()                    
            self.assertEqual(response, ['setup', {}])

            # Check for initial shell prompt
            response = yield tm.read_msg()
            self.assertEqual(response[0], 'stdout')
            self.assertGreater(len(response[1]), 0)
            tm.close()

    @tornado.testing.gen_test
    def test_named_no_name(self):
        with self.assertRaises(HTTPError) as context:
            tm = yield self.get_term_client('/named/')
            yield tm.read_msg()

        # Not found
        self.assertEqual(context.exception.code, 404)
        self.assertEqual(context.exception.response.code, 404)

    @tornado.testing.gen_test
    def test_basic_command(self):
        for url in self.test_urls:
            tm = yield self.get_term_client('/named/foo')
            yield tm.read_all_msg()
            tm.write_stdin("whoami\r")
            (stdout, other) = yield tm.read_stdout()
            self.assertEqual(stdout[:6], "whoami")
            self.assertEqual(other, [])
            tm.close()

if __name__ == '__main__':
    unittest.main()
