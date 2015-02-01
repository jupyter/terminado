#
# basic_tests.py -- Basic unit tests for Terminado
#

from __future__ import absolute_import, print_function

import unittest
from terminado import SingleTermManager, TermSocket
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
                        {'term_manager': SingleTermManager(shell_command=['bash'], ioloop=self.io_loop)}),
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

    @tornado.testing.gen_test
    def test_basic(self):
        ws = yield self.ws_connect("/websocket/term1")
        response = yield ws.read_message()              # Setup message
        j = json.loads(response)
        self.assertEqual(j, ['setup', {}])

        response = yield ws.read_message()              # Command prompt
        j = json.loads(response)
        self.assertEqual(j[0], 'stdout')
        ws.close()

if __name__ == '__main__':
    unittest.main()
