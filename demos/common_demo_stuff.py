import webbrowser
from pathlib import Path

import tornado.ioloop

import terminado

HERE = Path(terminado.__file__).parent
STATIC_DIR = HERE / "_static"
TEMPLATE_DIR = HERE / "templates"


def run_and_show_browser(url, term_manager):
    loop = tornado.ioloop.IOLoop.instance()
    loop.add_callback(webbrowser.open, url)
    try:
        loop.start()
    except KeyboardInterrupt:
        print(" Shutting down on SIGINT")  # noqa: T201
    finally:
        term_manager.shutdown()
        loop.close()
