Using the Tornado UI Module
===========================

Terminado provides a Tornado :ref:`UI Module <tornado:ui-modules>`. Once you
have the websocket handler set up (see :doc:`websocket`), add the module to your
application::

    from terminado import uimodule
    # ...

    app = tornado.web.Application(...
        ui_modules = {'Terminal': uimodule.Terminal},
    )

Now, when you want a terminal in your application, you can put this in the
template::

    {% module Terminal("/websocket", rows=30, cols=90) %}

This will create a div, and include the necessary Javascript code to set up a
terminal in that div and connect it to a websocket on ``ws://<host>/websocket``.

If not specified, rows and cols default to 25 and 80, respectively.

For now, this assumes that term.js is available at ``/xstatic/termjs/term.js``,
and terminado.js at ``/static/terminado.js``. To serve them from different
locations, subclass :class:`terminado.uimodule.Terminal`, overriding
:meth:`~terminado.uimodule.Terminal.javascript_files`.
