Release notes
=============

0.9
---

- Added support for message formats. The following message formats are supported: JSON, LightPayload (a custom
  message format) and MessagePack. The default message format is JSON, which is fully backwards-compatible. The
  message format can be switched at runtime.
- Added Xterm.js addon supporting all the message formats supported on the server-side.
- Added a command "switch_format" for switching the message format on the fly.

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
