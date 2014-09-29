import os.path
import threading
import webbrowser

import tornado.ioloop
import tornado.web
# This demo requires tornado_xstatic and XStatic-term.js
import tornado_xstatic

import pyxterm
import pyxshell

STATIC_DIR = os.path.join(os.path.dirname(__file__), "_static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

class TerminalPageHandler(tornado.web.RequestHandler):
    def get(self):
        return self.render("termpage.html", static=self.static_url,
                           xstatic=self.application.settings['xstatic_url'],
                           ws_url_path="/websocket")

def main(argv):
    term_manager = pyxshell.SingleTermManager(shell_command=['bash'])
    handlers = [
                (r"/websocket", pyxterm.TermSocket,
                     {'term_manager': term_manager}),
                (r"/", TerminalPageHandler),
                (r"/xstatic/(.*)", tornado_xstatic.XStaticFileHandler,
                     {'allowed_modules': ['termjs']})
               ]
    app = tornado.web.Application(handlers, static_path=STATIC_DIR,
                      template_path=TEMPLATE_DIR,
                      xstatic_url = tornado_xstatic.url_maker('/xstatic/'))
    app.listen(8765)
    t = threading.Timer(0.5, webbrowser.open, ("http://localhost:8765",))
    t.start()
    loop = tornado.ioloop.IOLoop.instance()
    try:
        loop.start()
    except KeyboardInterrupt:
        print(" Shutting down on SIGINT")
    finally:
        term_manager.shutdown()
        loop.close()

if __name__ == '__main__':
    main([])