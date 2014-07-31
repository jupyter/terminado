## pyxterm: Pure python websocket terminal server for term.js

Uses ``term.js`` from <https://github.com/chjj/term.js>

Requires the tornado web server from <http://www.tornadoweb.org>

*Note:* To be consistent with ``term.js``, this package should have been
named either ``term.py`` or ``tty.py``, but those names are already in
use. Hence the name ``pyxterm``.


### Main files

* ``pyxterm.py``: Terminal server

* ``pyxshell.py``: Backend pseudo-tty shell manager

* ``_static/pyxterm.js``: Javascript wrappers for ``term.js``

* ``_static/index.html``: Example terminal template

### Testing

To try it out, run:

    ./pyxterm.py --auth_type=none --terminal

to start the server with no authentication and open a ``bash`` shell terminal.

The default URL to a create a new terminal is
``http://localhost:8700/new``. To create a named terminal, open
``http://localhost:8700/terminal_name``

Other authentication/shell options are

* ``./pyxterm.py --auth_type=ssh`` for SSH login to localhost (default)

* ``sudo ./pyxterm.py --auth_type=login`` for standard Unix-style login

* ``./pyxterm.py --auth_type=google`` for Google authentication

* ``./pyxterm.py --auth_type=none /bin/shell_program `` to run a different "shell" program

* ``./pyxterm.py --auth_type=none ipython `` to run ipython as the "shell"

* ``./pyxterm.py --auth_type=none /usr/bin/env python /path/app.py `` to use a python script as the "shell"


For more help information, type

    ./pyxterm.py -h

### Google authentication

To set up the ``pyxterm`` for Google authentication:

 * Go to the Google Dev Console at <https://console.developers.google.com>

 * Select a project, or create a new one.

 * In the sidebar on the left, select *APIs & Auth*.

 * In the sidebar on the left, select *Consent Screen* to customize the Product name etc.

 * In the sidebar on the left, select *Credentials*.

 * In the OAuth section of the page, select *Create New Client ID*.

 * Edit settings for the Authorized URIs, substituting ``localhost:8700`` if need be

    Authorized Javascript origins: ``http://localhost:8700``

    Authorized Redirect URI: ``http://localhost:8700/_gauth``

 * Copy the web application "Client ID key" and "Client secret" to the settings file (see below)

Start the server with the command:

    ./pyxterm.py --auth_type=google

and use the URLs ``http://localhost:8700/_gauth/_info`` and
``http://localhost:8700/_gauth/_test`` to display setup
information and test Google authentication.

### Settings file

Settings may be provided in JSON format in the file
``.pyxterm.json`` in the home directory. If present, it contains
information of the form:

    {"google_oauth": {"key": "0123456789-code.apps.googleusercontent.com",
                      "secret": "ABCDEFABCDEF"},
     "auth_emails": ["user1@gmail.com", "user2@gmail.com"] }

``auth_emails`` is the list of gmail accounts authorized to access the
server. An empty list implies all accounts are authorized.

### History and goals

The goal is to provide a simple Python terminal server for ``term.js`` using websockets, akin to ``tty.js``.

``pyxterm`` contains code simplified and factored out of more complex ``GraphTerm`` code
(<https://github.com/mitotic/graphterm>), which itself used some old code from
``AjaxTerm``


Licenses: MIT, BSD

Version: 0.10 (alpha)
