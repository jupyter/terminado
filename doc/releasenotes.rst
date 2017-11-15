Release notes
=============

0.7
---

- :meth:`terminado.TermSocket.open` now calls the ``open()`` method on the
  parent class using ``super()``. This allows a mixin class; for instance, to
  periodically send ping messages to keep a connection open.
- When a websocket client disconnects from a terminal managed by
  :class:`~.UniqueTermManager`, the ``SIGHUP`` signal is sent to the process
  group, not just the main process.
- Fixed :meth:`terminado.NamedTermManager.kill` to use the signal number passed
  to it.
- Switched to Flit packaging.
- README and requirements for demos.
