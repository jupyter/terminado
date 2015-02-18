"""One shared terminal per URL endpoint

Plus a /new URL which will create a new terminal and redirect to it.
"""
from __future__ import print_function, absolute_import
import logging
import os.path
import sys

import tornado.web
# This demo requires tornado_xstatic and XStatic-term.js
import tornado_xstatic

from terminado import TermSocket, NamedTermManager
from common_demo_stuff import run_and_show_browser, STATIC_DIR, TEMPLATE_DIR

AUTH_TYPES = ("none", "login")

class TerminalPageHandler(tornado.web.RequestHandler):
    """Render the /ttyX pages"""
    def get(self, term_name):
        return self.render("termpage.html", static=self.static_url,
                           xstatic=self.application.settings['xstatic_url'],
                           ws_url_path="/_websocket/"+term_name)

class NewTerminalHandler(tornado.web.RequestHandler):
    """Redirect to an unused terminal name"""
    def get(self):
        name, terminal = self.application.settings['term_manager'].new_named_terminal()
        self.redirect("/" + name, permanent=False)

def main():
    term_manager = NamedTermManager(shell_command=['bash'],
                                     max_terminals=100)

    handlers = [
                (r"/_websocket/(\w+)", TermSocket,
                     {'term_manager': term_manager}),
                (r"/new/?", NewTerminalHandler),
                (r"/(\w+)/?", TerminalPageHandler),
                (r"/xstatic/(.*)", tornado_xstatic.XStaticFileHandler)
               ]
    application = tornado.web.Application(handlers, static_path=STATIC_DIR,
                              template_path=TEMPLATE_DIR,
                              xstatic_url=tornado_xstatic.url_maker('/xstatic/'),
                              term_manager=term_manager)

    application.listen(8700, 'localhost')
    run_and_show_browser("http://localhost:8700/new", term_manager)

if __name__ == "__main__":
    main()