import os.path
import threading
import webbrowser

import tornado.ioloop
import tornado.web
import tornado_xstatic

import pyxterm
import pyxshell

STATIC_DIR = os.path.join(os.path.dirname(__file__), "_static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

class TerminalPageHandler(tornado.web.RequestHandler):
    def get(self):
        return self.render("termpage.html", static=self.static_url,
                           xstatic=self.application.xstatic_url,
                           ws_url_path="/websocket")

class Application(tornado.web.Application):
    def __init__(self, term_manager, **kwargs):
        self.term_manager = term_manager
        handlers = [
                (r"/websocket", pyxterm.TermSocket),
                (r"/", TerminalPageHandler),
                (r"/xstatic/(.*)", tornado_xstatic.XStaticFileHandler,
                     {'allowed_modules': ['termjs']})
                ]
        
        self.xstatic_url = tornado_xstatic.url_maker('/xstatic/')
        
        if 'template_path' not in kwargs:
            kwargs['template_path'] = TEMPLATE_DIR
        if 'static_path' not in kwargs:
            kwargs['static_path'] = STATIC_DIR
        super(Application, self).__init__(handlers, **kwargs)

def main(argv):
    term_manager = pyxshell.TermManager(shell_command=['bash'])
    app = Application(term_manager)
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