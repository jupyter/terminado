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

from sslcerts import prepare_ssl_options
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

def setup_logging(log_level=logging.ERROR, filename="", file_level=None):
    file_level = file_level or log_level
    logger = logging.getLogger()
    logger.setLevel(min(log_level, file_level))

    formatter = logging.Formatter("%(levelname).1s%(asctime)s %(module).8s.%(lineno).04d %(message)s",
                                  "%y%m%d/%H:%M")

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(log_level)
            handler.setFormatter(formatter)
    else:
        # Console handler
        chandler = logging.StreamHandler()
        chandler.setLevel(log_level)
        chandler.setFormatter(formatter)
        logger.addHandler(chandler)

    if filename:
        # File handler
        fhandler = logging.FileHandler(filename)
        fhandler.setLevel(file_level)
        fhandler.setFormatter(formatter)
        logger.addHandler(fhandler)

def run_server(options, args):

    http_port = options.port
    http_host = options.host
    external_host = options.external_host or http_host
    external_port = options.external_port or http_port
    if options.https:
        server_url = "https://"+external_host+("" if external_port == 443 else ":%d" % external_port)
    else:
        server_url = "http://"+external_host+("" if external_port == 80 else ":%d" % external_port)
    new_url = server_url + "/new"

    if args:
        if options.auth_type == "login":
            sys.exit("--auth_type=login cannot be combined with specified shell command")
        shell_command = args[:]
    elif options.auth_type == "login":
        if os.geteuid():
            sys.exit("Error: Must run server as root for --auth_type=login")
        if not options.https and external_host != "localhost":
            sys.exit("Error: At this time --auth_type=login is permitted only with https or localhost (for security reasons)")
        shell_command = ["login"]
    else:
        shell_command = ["bash"]

    term_manager = NamedTermManager(shell_command=shell_command,
                                             max_terminals=options.max_terminals)

    handlers = [
                (r"/_websocket/(tty\d+)", TermSocket,
                     {'term_manager': term_manager}),
                (r"/new/?", NewTerminalHandler),
                (r"/(tty\d+)/?", TerminalPageHandler),
                (r"/xstatic/(.*)", tornado_xstatic.XStaticFileHandler)
               ]
    application = tornado.web.Application(handlers, static_path=STATIC_DIR,
                              template_path=TEMPLATE_DIR,
                              xstatic_url=tornado_xstatic.url_maker('/xstatic/'),
                              term_manager=term_manager)

    ssl_options = prepare_ssl_options(options)

    Http_server = tornado.httpserver.HTTPServer(application, ssl_options=ssl_options)
    Http_server.listen(http_port, address=http_host)
    if options.logging:
        Log_filename = "pyxterm.log"
        setup_logging(logging.INFO, Log_filename, logging.INFO)
        logging.error("**************************Logging to %s", Log_filename)
    else:
        setup_logging(logging.WARNING)
        logging.error("**************************Logging to console")

    run_and_show_browser(new_url, term_manager)

def main():
    from optparse import OptionParser
    usage = "usage: %prog [<shell_command>]"
    parser = OptionParser(usage=usage)
    parser.add_option("", "--host", dest="host", default="localhost",
                      help="Host (default: localhost)")
    parser.add_option("", "--port", dest="port", default=8700, type="int",
                      help="Port to listen on (default: 8700)")
    parser.add_option("", "--external_host", dest="external_host", default="",
                      help="External host (default: same as host)")
    parser.add_option("", "--external_port", dest="external_port", default=0, type="int",
                      help="External port (default: same as port)")
    parser.add_option("", "--https", dest="https", default=False, action="store_true",
                      help="Enable https")
    parser.add_option("", "--auth_type", dest="auth_type", default="none",
                      help="Authentication type: %s (default: ssh)" % "/".join(AUTH_TYPES))
    parser.add_option("", "--client_cert", dest="client_cert", default="",
                      help="Path to client CA cert (or '.')")
    parser.add_option("", "--term_type", dest="term_type", default="xterm",
                      help="Terminal type (default: xterm)")
    parser.add_option("", "--term_options", dest="term_options", default="",
                      help="Terminal options (comma-separated, no spaces)")
    parser.add_option("", "--max_terminals", dest="max_terminals", default=100, type="int",
                      help="Maximum number of terminals")
    parser.add_option("-t", "--terminal", dest="terminal", default=False, action="store_true",
                      help="Open new terminal window at start")
    parser.add_option("-l", "--logging", dest="logging", default=False, action="store_true",
                      help="Enable logging")

    (options, args) = parser.parse_args()

    if options.auth_type not in AUTH_TYPES:
        sys.exit("--auth_type must be one of %s" % (AUTH_TYPES,))

    tornado.options.options.logging = "none"    # Disable tornado logging
    tornado.options.parse_command_line([])      # Parse "dummy" command line

    run_server(options, args)

if __name__ == "__main__":
    main()