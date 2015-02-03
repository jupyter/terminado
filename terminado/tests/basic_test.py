#
# basic_tests.py -- Basic unit tests for Terminado
#

from __future__ import absolute_import, print_function

import unittest
from terminado import *
import tornado
import tornado.httpserver
from tornado.httpclient import HTTPError
import tornado.testing
import logging
import json

class TestTermManager(object):
    """Test connection to a terminal manager"""
    def __init__(self, path, test_case):
        """Open a Websocket connection to the localhost"""
        port = test_case.get_http_port()
        url = 'ws://127.0.0.1:%d%s' % (port, path)
        request = tornado.httpclient.HTTPRequest(url, 
                    headers={'Origin' : 'http://127.0.0.1:%d' % port})
        self.ws_future = tornado.websocket.websocket_connect(request)
        self.stdout = ""

    @tornado.gen.coroutine
    def read_msg(self):
        ws = yield self.ws_future
        response = yield ws.read_message()
        msg = json.loads(response)

        # If stdout output, save it
        if msg[0] == 'stdout':
            self.stdout += msg[1]
        raise tornado.gen.Return(msg)

    @tornado.gen.coroutine
    def write_msg(self, msg):
        ws = yield self.ws_future
        ws.write_message(json.dumps(msg))

    @tornado.gen.coroutine
    def write_stdin(self, data):
        """Write to terminal's stdin"""
        self.write_msg(['stdin', data])

    @tornado.gen.coroutine
    def close(self):
        ws = yield self.ws_future
        ws.close()


class BasicTest(tornado.testing.AsyncHTTPTestCase):
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
            tm = TestTermManager(url, self)
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
            tm = TestTermManager('/named/', self)
            yield tm.read_msg()

        # Not found
        self.assertEqual(context.exception.code, 404)
        self.assertEqual(context.exception.response.code, 404)

if __name__ == '__main__':
    unittest.main()
