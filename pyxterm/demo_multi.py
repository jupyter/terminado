from __future__ import print_function, absolute_import
import logging
import os.path
import signal
import sys
import threading
import time
import webbrowser

import tornado.web
import tornado_xstatic

from sslcerts import prepare_ssl_options
import pyxshell
import pyxterm

AUTH_TYPES = ("none", "login")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "_static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

class TerminalPageHandler(tornado.web.RequestHandler):
    """Render the /ttyX pages"""
    def get(self, term_name):
        return self.render("termpage.html", static=self.static_url,
                           xstatic=self.application.xstatic_url,
                           ws_url_path="/_websocket/"+term_name)

class NewTerminalHandler(tornado.web.RequestHandler):
    """Redirect to an unused terminal name"""
    def get(self):
        terminal, term_name, cookie = self.application.term_manager.terminal()
        self.redirect("/" + term_name, permanent=False)

class Application(tornado.web.Application):
    def __init__(self, term_manager, **kwargs):
        self.term_manager = term_manager
        handlers = [
                (r"/_websocket/(%s)" % pyxterm.TERM_NAME_RE_PART, pyxterm.TermSocket),
                (r"/new/?", NewTerminalHandler),
                (r"/(tty\d+)/?", TerminalPageHandler),
                (r"/xstatic/(.*)", tornado_xstatic.XStaticFileHandler)
                ]

        self.xstatic_url = tornado_xstatic.url_maker('/xstatic/')
        
        if 'template_path' not in kwargs:
            kwargs['template_path'] = TEMPLATE_DIR
        if 'static_path' not in kwargs:
            kwargs['static_path'] = STATIC_DIR
        super(Application, self).__init__(handlers, **kwargs)


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

    tem_str = options.term_options.strip().replace(" ","")
    term_options = set(tem_str.split(",") if tem_str else [])
    term_settings = {"type": options.term_type, "max_terminals": options.max_terminals,
                     "https": options.https, "logging": options.logging,
                     "options": term_options, "server_url": server_url, "auth_type": options.auth_type}

    app_settings = {"log_function": lambda x:None}

    term_manager = pyxshell.TermManager(shell_command=shell_command, server_url="",
                                        term_settings=term_settings)

    application = Application(term_manager=term_manager, **app_settings)

    ##logging.warning("DocRoot: "+Doc_rootdir);

    IO_loop = tornado.ioloop.IOLoop.instance()

    ssl_options = prepare_ssl_options(options)

    Http_server = tornado.httpserver.HTTPServer(application, ssl_options=ssl_options)
    Http_server.listen(http_port, address=http_host)
    if options.logging:
        Log_filename = "pyxterm.log"
        pyxshell.setup_logging(logging.INFO, Log_filename, logging.INFO)
        logging.error("**************************Logging to %s", Log_filename)
    else:
        pyxshell.setup_logging(logging.WARNING)
        logging.error("**************************Logging to console")

    if options.terminal:
        try:
            webbrowser.open_new_tab(new_url)
        except Exception as excp:
            print("Error in creating terminal; please open URL %s in browser (%s)"
                    % (new_url, excp), file=sys.stderr)

    def stop_server():
        print("\nStopping server", file=sys.stderr)
        if Http_server:
            Http_server.stop()
        def stop_server_aux():
            IO_loop.stop()

        # Need to stop IO_loop only after all other scheduled shutdowns have completed
        IO_loop.add_callback(stop_server_aux)

    def sigterm(signal, frame):
        logging.warning("SIGTERM signal received")
        IO_loop.add_callback(stop_server)
    signal.signal(signal.SIGTERM, sigterm)

    try:
        ioloop_thread = threading.Thread(target=IO_loop.start)
        ioloop_thread.start()
        time.sleep(1)   # Time to start thread
        print("Pyxterm server started", file=sys.stderr)
        print("Open URL %s in browser to connect" % new_url, file=sys.stderr)
        print("Type ^C to stop", file=sys.stderr)
        while Http_server:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)

    finally:
        if term_manager:
            term_manager.shutdown()
    IO_loop.add_callback(stop_server)

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