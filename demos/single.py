"""A single common terminal for all websockets.
"""
import tornado.web

# This demo requires tornado_xstatic and XStatic-term.js
import tornado_xstatic
from common_demo_stuff import STATIC_DIR, TEMPLATE_DIR, run_and_show_browser

from terminado import SingleTermManager, TermSocket


class TerminalPageHandler(tornado.web.RequestHandler):
    def get(self):
        return self.render(
            "termpage.html",
            static=self.static_url,
            xstatic=self.application.settings["xstatic_url"],
            ws_url_path="/websocket",
        )


def main(argv):
    term_manager = SingleTermManager(shell_command=["bash"])
    handlers = [
        (r"/websocket", TermSocket, {"term_manager": term_manager}),
        (r"/", TerminalPageHandler),
        (r"/xstatic/(.*)", tornado_xstatic.XStaticFileHandler, {"allowed_modules": ["termjs"]}),
    ]
    app = tornado.web.Application(
        handlers,
        static_path=STATIC_DIR,
        template_path=TEMPLATE_DIR,
        xstatic_url=tornado_xstatic.url_maker("/xstatic/"),
    )
    app.listen(8765, "localhost")
    run_and_show_browser("http://localhost:8765/", term_manager)


if __name__ == "__main__":
    main([])
