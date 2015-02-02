#
# basic_tests.py -- Basic unit tests for Terminado
#

from __future__ import absolute_import, print_function

import unittest
from terminado import NamedTermManager, TermSocket
import tornado
import tornado.httpserver
import tornado.httpclient
import tornado.testing
import logging
import json

class BasicTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([
                    (r"/websocket/(\w+)", TermSocket,
                        {'term_manager': NamedTermManager(shell_command=['bash'], ioloop=self.io_loop)}),
                ], debug=True)

    @tornado.gen.coroutine
    def ws_connect(self, path):
        """Open a Webscocket connection to the localhost"""
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
        ws = yield self.ws_connect("/websocket/term1")
        response = yield self.read_json(ws)             # Setup message
        self.assertEqual(response, ['setup', {}])

        response = yield self.read_json(ws)             # Command prompt
        self.assertEqual(response[0], 'stdout')
        ws.close()

if __name__ == '__main__':
    unittest.main()
