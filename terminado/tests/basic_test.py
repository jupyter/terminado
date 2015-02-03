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

    @tornado.gen.coroutine
    def ws_connect(self, path):
        """Open a Websocket connection to the localhost"""
        port = self.get_http_port()
        url = 'ws://127.0.0.1:%d%s' % (port, path)
        request = tornado.httpclient.HTTPRequest(url, 
                    headers={'Origin' : 'http://127.0.0.1:%d' % port})
        ws = yield tornado.websocket.websocket_connect(request)
        raise tornado.gen.Return(ws)

    @tornado.gen.coroutine
    def read_json(self, ws):
        """Helper:  read a message, parse as JSON"""
        response = yield ws.read_message()
        raise tornado.gen.Return(json.loads(response))

    @tornado.testing.gen_test
    def test_basic(self):
        for url in self.test_urls:
            ws = yield self.ws_connect(url)
            response = yield self.read_json(ws)             # Setup message
            self.assertEqual(response, ['setup', {}])

            response = yield self.read_json(ws)             # Command prompt
            self.assertEqual(response[0], 'stdout')
            self.assertGreater(len(response[1]), 0)
            ws.close()

    @tornado.testing.gen_test
    def test_named_no_name(self):
        with self.assertRaises(HTTPError) as context:
            ws = yield self.ws_connect('/named/')

        # Not found
        self.assertEqual(context.exception.code, 404)
        self.assertEqual(context.exception.response.code, 404)

if __name__ == '__main__':
    unittest.main()
