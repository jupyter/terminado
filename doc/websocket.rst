Using the TermSocket handler
============================

:class:`terminado.TermSocket` is the main API in Terminado. It is a subclass of
:class:`tornado.web.WebSocketHandler`, used to communicate between a
pseudoterminal and term.js. You add it to your web application as a handler like
any other::

    app = tornado.web.Application([
            # ... other handlers ...
            (r"/websocket", terminado.TermSocket,
                {'term_manager': terminado.SingleTermManager(shell_command=['bash'])}),
        ], **kwargs)

Now, a page in your application can connect to ``ws://<host>/websocket``. Using
:file:`terminado/_static/terminado.js`, you can do this using:

.. code-block:: javascript

   make_terminal(target_html_element, {rows:25, cols:80}, "ws://<host>/websocket");

.. warning::

   :class:`~terminado.TermSocket` does not authenticate the connection at all,
   and using it with a program like ``bash`` means that anyone who can connect
   to it can run commands on your server. It is up to you to integrate the
   handler with whatever authentication system your application uses. For
   instance, in IPython, we subclass it like this::

       class TermSocket(terminado.TermSocket, IPythonHandler):
           def get(self, *args, **kwargs):
               if not self.get_current_user():
                   raise web.HTTPError(403)
               return super(TermSocket, self).get(*args, **kwargs)

Terminal managers
-----------------

The terminal manager control the behaviour when you connect and disconnect
websockets. Terminado offers three options:

.. module:: terminado

.. autoclass:: SingleTermManager

.. autoclass:: UniqueTermManager

.. autoclass:: NamedTermManager

You can also define your own behaviours, by subclassing any of these, or the
base class. The important methods are described here:

.. autoclass:: TermManagerBase

   .. automethod:: get_terminal

   .. automethod:: new_terminal

   .. automethod:: start_reading

   .. automethod:: client_disconnected

This may still be subject to change as we work out the best API.

In the example above, the terminal manager was only attached to the websocket
handler. If you want to access it from other handlers, for instance to list
running terminals, attach the instance to your application, for instance in the
settings dictionary.
