#!/usr/bin/env python

"""pyxterm.py: Python websocket terminal server for term.js, using pxterm.py as the backend

Requires term.js, pyxterm.js pyxshell.py

To test, run:

  ./pyxterm.py --terminal

to start the server an open a terminal. For help, type

  ./pyxterm.py -h

Default URL to a create a new terminal is http://localhost:8700/new

To create a named terminal, open http://localhost:8700/terminal_name

BSD License

"""

#
#  BSD License
#
#  Copyright (c) 2014, Ramalingam Saravanan <sarava@sarava.net>
#  All rights reserved.
#  
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#  
#  1. Redistributions of source code must retain the above copyright notice, this
#     list of conditions and the following disclaimer. 
#  2. Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution. 
#  
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
#  ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
#  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
#  ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
#  (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
#  ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import absolute_import, print_function, with_statement


# Python3-friendly imports
try:
    from urllib.parse import urlparse, parse_qs, urlencode
except ImportError:
    from urlparse import urlparse, parse_qs
    from urllib import urlencode

import base64
import cgi
import collections
import logging
import os
import ssl
import sys
import threading
import time
import uuid

try:
    import ujson as json
except ImportError:
    import json

import pyxshell

import tornado.auth
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

File_dir = os.path.dirname(__file__)
if File_dir == ".":
    File_dir = os.getcwd()    # Need this for daemonizing to work?
Doc_rootdir = os.path.join(File_dir, "_static")

BANNER_HTML = '<center><h2>pyxterm</h2></center>'

STATIC_PATH = "_static"
STATIC_PREFIX = "/"+STATIC_PATH+"/"

MAX_COOKIE_STATES = 300
COOKIE_NAME = "PYXTERM_AUTH"
COOKIE_TIMEOUT = 86400

AUTH_DIGITS = 12    # Form authentication code hex-digits
                    # Note: Less than half of the 32 hex-digit state id should be used for form authentication

AUTH_TYPES = ("none", "ssh", "login", "google")

def cgi_escape(s):
    return cgi.escape(s) if s else ""

def get_query_auth(state_id):
    return state_id[:AUTH_DIGITS]

def get_first_arg(query_data, argname, default=""):
    return query_data.get(argname, [default])[0]

class ErrorMessage(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return str(self.value)

server_cert_gen_cmds = [
    'openssl req -x509 -nodes -days %(expdays)d -newkey rsa:%(keysize)d -batch -subj /O=pyxterm/CN=%(hostname)s -keyout %(keyfile)s -out %(certfile)s',
    'openssl x509 -noout -fingerprint -in %(certfile)s',
    ]
server_cert_gen_cmds_long = [
    'openssl genrsa -out %(hostname)s.key %(keysize)d',
    'openssl req -new -key %(hostname)s.key -out %(hostname)s.csr -batch -subj "/O=pyxterm/CN=%(hostname)s"',
    'openssl x509 -req -days %(expdays)d -in %(hostname)s.csr -signkey %(hostname)s.key -out %(hostname)s.crt',
    'openssl x509 -noout -fingerprint -in %(hostname)s.crt',
    ]

client_cert_gen_cmds = [
    'openssl genrsa -out %(clientprefix)s.key %(keysize)d',
    'openssl req -new -key %(clientprefix)s.key -out %(clientprefix)s.csr -batch -subj "/O=pyxterm/CN=%(clientname)s"',
    'openssl x509 -req -days %(expdays)d -in %(clientprefix)s.csr -CA %(certfile)s -CAkey %(keyfile)s -set_serial 01 -out %(clientprefix)s.crt',
    "openssl pkcs12 -export -in %(clientprefix)s.crt -inkey %(clientprefix)s.key -out %(clientprefix)s.p12 -passout pass:%(clientpassword)s"
    ]

def ssl_cert_gen(certfile, keyfile="", hostname="localhost", cwd=None, new=False, clientname=""):
    """Return fingerprint of self-signed server certficate, creating a new one, if need be"""
    params = {"certfile": certfile, "keyfile": keyfile or certfile,
              "hostname": hostname, "keysize": 1024, "expdays": 1024,
              "clientname": clientname, "clientprefix":"%s-%s" % (hostname, clientname),
              "clientpassword": "password",}
    cmd_list = server_cert_gen_cmds if new else server_cert_gen_cmds[-1:]
    for cmd in cmd_list:
        cmd_args = pyxshell.shlex_split_str(cmd % params)
        std_out, std_err = pyxshell.command_output(cmd_args, cwd=cwd, timeout=15)
        if std_err:
            logging.warning("pyxterm: SSL keygen %s %s", std_out, std_err)
    fingerprint = std_out
    if new and clientname:
        for cmd in client_cert_gen_cmds:
            cmd_args = pyxshell.shlex_split_str(cmd % params)
            std_out, std_err = pyxshell.command_output(cmd_args, cwd=cwd, timeout=15)
            if std_err:
                logging.warning("pyxterm: SSL client keygen %s %s", std_out, std_err)
    return fingerprint


class TermSocket(tornado.websocket.WebSocketHandler):
    _all_term_sockets = {}
    _all_term_paths = collections.defaultdict(set)
    _term_counter = [0]
    _term_states = OrderedDict()
    _term_connect_cookies = OrderedDict()

    @classmethod
    def get_connect_cookie(cls):
        while len(cls._term_connect_cookies) > 100:
            cls._term_connect_cookies.popitem(last=False)
        new_cookie = uuid.uuid4().hex[:12]
        cls._term_connect_cookies[new_cookie] = {}  # connect_data (from form submission)
        return new_cookie

    @classmethod
    def check_connect_cookie(cls, cookie):
        return cls._term_connect_cookies.pop(cookie, None)            

    @classmethod
    def update_connect_cookie(cls, cookie, connect_data):
        if cookie not in cls._term_connect_cookies:
            return False
        cls._term_connect_cookies[cookie] = connect_data
        return True

    @classmethod
    def get_state(cls, state_id):
        if state_id not in cls._term_states:
            return None
        state_value = cls._term_states[state_id]
        return state_value

    @classmethod
    def get_request_state(cls, request):
        if COOKIE_NAME not in request.cookies:
            return None
        cookie_value = request.cookies[COOKIE_NAME].value
        state_value = cls.get_state(cookie_value)
        if state_value:
            return state_value
        # Note: webcast auth will always be dropped
        cls.drop_state(cookie_value)
        return None

    @classmethod
    def drop_state(cls, state_id):
        cls._term_states.pop(state_id, None)

    @classmethod
    def add_state(cls, user="", email=""):
        state_id = uuid.uuid4().hex
        authstate = {"state_id": state_id,
                     "user": user,
                     "email": email,
                     "time": time.time()}
        if len(cls._term_states) >= MAX_COOKIE_STATES:
            cls._term_states.popitem(last=False)
        cls._term_states[state_id] = authstate
        return authstate

    def __init__(self, *args, **kwargs):
        self.term_request = args[1]
        self.check_client_cert()
        logging.info("TermSocket.__init__: %s", self.term_request.uri)

        self.term_query = self.term_request.query
        self.term_reqpath = "/".join(self.term_request.path.split("/")[2:])  # Strip out /_websocket from path
        if self.term_reqpath.endswith("/"):
            self.term_reqpath = self.term_reqpath[:-1]

        super(TermSocket, self).__init__(*args, **kwargs)

        self.term_authstate = None
        self.term_path = ""
        self.term_cookie = ""
        self.term_client_id = None

    def check_client_cert(self):
        try:
            self.client_cert = self.term_request.get_ssl_certificate()
        except Exception:
            self.client_cert = ""

        self.common_name = ""
        if self.client_cert:
            try:
                subject = dict([x[0] for x in self.client_cert["subject"]])
                self.common_name = subject.get("commonName")
            except Exception as excp:
                logging.warning("pyxterm: client_cert ERROR %s", excp)
        if self.client_cert:
            logging.warning("pyxterm: client_cert=%s, name=%s", self.client_cert, self.common_name)

    def origin_check(self):
        if "Origin" in self.term_request.headers:
            origin = self.term_request.headers.get("Origin")
        else:
            origin = self.term_request.headers.get("Sec-Websocket-Origin", None)

        if not origin:
            return False

        host = self.term_request.headers.get("Host").lower()
        ws_host = urlparse(origin).netloc.lower()
        if host == ws_host:
            return True
        else:
            logging.error("pyxterm.origin_check: ERROR %s != %s", host, ws_host)
            return False

    def term_authenticate(self):
        authstate = self.get_request_state(self.request)
        if authstate:
            return authstate
        if Term_settings["auth_type"] == "google":
            # State must be added by Google auth
            return None
        return self.add_state()

    def open(self):
        if not self.origin_check():
            raise tornado.web.HTTPError(404, "Websocket origin mismatch")

        logging.info("TermSocket.open:")
        query_data = {}
        if self.term_query:
            try:
                query_data = parse_qs(self.term_query)
            except Exception:
                pass

        connect_auth = get_first_arg(query_data, "cauth")
        connect_data = self.check_connect_cookie(connect_auth)
        if connect_data is None:
            # Invalid connect cookie
            connect_auth = None

        authstate = self.term_authenticate()
        if not authstate:
            if Term_settings["auth_type"] == "google":
                gauth_url = "/_gauth/%s?cauth=%s" % (self.term_reqpath, self.get_connect_cookie())
                self.term_remote_call("document", BANNER_HTML+'<p><h3><a href="%s">Click here</a> to initiate Google authentication </h3>' % gauth_url)
            else:
                logging.error("TermSocket.open: ERROR authentication failed")
            self.close()
            return

        self.term_authstate = authstate

        query_auth = get_first_arg(query_data, "qauth")
        if not connect_auth and (not query_auth or query_auth != get_query_auth(self.term_authstate["state_id"])):
            # Invalid query auth; clear any form data
            query_data = {}

        if not query_data:
            # Confirm request, if no form data
            if self.term_reqpath:
                ##logging.info("TermSocket.open: Confirm request %s", self.term_reqpath)
                confirm_url = "/%s/?cauth=%s" % (self.term_reqpath, self.get_connect_cookie())
                self.term_remote_call("document", BANNER_HTML+'<p><h3>Click to open terminal <a href="%s">%s</a></h3>' % (confirm_url, "/"+self.term_reqpath))
                self.close()
                return
            else:
                # Forget path
                path_comps = []
        else:
            path_comps = self.term_reqpath.split("/")

        path_name = path_comps[0] if path_comps else "new"

        if pyxshell.TERM_NAME_RE.match(path_name):
            term_name = None if path_name == "new" else path_name
            # Require access for ssh/login auth types (because there is no user authentication)
            access_code = "" if Term_settings["auth_type"] in ("none", "google") else self.term_authstate["state_id"]
            self.term_path, self.term_cookie, alert_msg = Term_manager.terminal(term_name=term_name, access_code=access_code)
        else:
            alert_msg = "Invalid terminal name '%s'; follow identifier rules" % path_name

        if alert_msg:
            logging.error(alert_msg)
            self.term_remote_call("alert", alert_msg)
            self.close()
            return

        if path_name == "new" or not query_auth:
            redirect_url = "/%s/?qauth=%s" % (self.term_path, get_query_auth(self.term_authstate["state_id"]))
            self.term_remote_call("redirect", redirect_url, self.term_authstate["state_id"])
            self.close()
            return

        self.add_termsocket()

        self.term_remote_call("setup", {"state_id": self.term_authstate["state_id"],
                                        "client_id": self.term_client_id,
                                        "term_path": self.term_path})
        logging.info("TermSocket.open: Opened %s", self.term_path)

    @classmethod
    def get_path_termsockets(cls, path):
        return cls._all_term_paths.get(path, set())

    @classmethod
    def get_termsocket(cls, client_id):
        return cls._all_term_sockets.get(client_id)            

    def add_termsocket(self):
        self._term_counter[0] += 1
        self.term_client_id = str(self._term_counter[0])

        self._all_term_sockets[self.term_client_id] = self     
        self._all_term_paths[self.term_path].add(self.term_client_id)
        return self.term_client_id

    def on_close(self):
        logging.info("TermSocket.on_close: Closing %s", self.term_path)
        self._all_term_sockets.pop(self.term_client_id, None)
        if self.term_path in self._all_term_paths:
            self._all_term_paths[self.term_path].discard(self.term_client_id)

    @classmethod
    def term_remote_callback(cls, term_path, client_id, method, *args):
        client_ids = [client_id] if client_id else cls.get_path_termsockets(term_path)
        try:
            json_msg = json.dumps([method, args])
            ##logging.info("term_remote_callback: %s, %s, %s", args, json.loads(json.dumps(args[0])) if args else "NONE", json_msg)
            for client_id in client_ids:
                termsocket = cls.get_termsocket(client_id)
                if termsocket:
                    termsocket.term_write(json_msg)
        except Exception as excp:
            logging.error("term_remote_callback: ERROR %s", excp)

    def term_remote_call(self, method, *args, **kwargs):
        """
        kwargs: content=None, content_type="", content_encoding=""
        """
        logging.error("term_remote_call: %s", method)
        try:
            if not kwargs:
                # Text message
                json_msg = json.dumps([method, args])
                self.term_write(json_msg)
            else:
                # Binary message with UTF-16 JSON prefix
                content = kwargs.get("content")
                assert isinstance(content, bytes), "Content must be of bytes type"
                
                json_prefix = json.dumps([method, args, {"content_type": kwargs.get("content_type",""),
                                                             "content_encoding": kwargs.get("content_encoding",""),
                                                             "content_length": len(content)} ]) + "\n\n"
                content_prefix = json_prefix.encode("utf-16")
                self.term_write(content_prefix+content, binary=True)
        except Exception as excp:
            logging.error("term_remote_call: ERROR %s", excp)

    def term_write(self, data, binary=False):
        try:
            self.write_message(data, binary=binary)
        except Exception as excp:
            logging.error("term_write: ERROR %s", excp)
            closed_excp = getattr(tornado.websocket, "WebSocketClosedError", None)
            if not closed_excp or not isinstance(excp, closed_excp):
                import traceback
                logging.info("Error in websocket: %s\n%s", excp, traceback.format_exc())
            try:
                # Close websocket on write error
                self.close()
            except Exception:
                pass

    def on_message(self, message):
        ##logging.info("TermSocket.on_message: %s - (%s) %s", self.term_path, type(message), len(message) if isinstance(message, bytes) else message[:250])
        if not self.term_path:
            return

        if isinstance(message, bytes):
            # Binary message with UTF-16 JSON prefix
            enc_delim = "\n\n".encode("utf-16")
            offset = message.find(enc_delim)
            if offset < 0:
                raise Exception("Delimiter not found in binary message")
            command = json.loads(message[:offset]).decode("utf-16")
            content = message[offset+len(enc_delim):]
        else:
            command = json.loads(message if isinstance(message,str) else message.encode("UTF-8", "replace"))
            content = None
            
        kill_term = False
        try:
            send_cmd = True
            if command[0] == "kill_term":
                kill_term = True
            elif command[0] == "errmsg":
                logging.error("Terminal %s: %s", self.term_path, command[1])
                send_cmd = False

            if send_cmd:
                matchpaths = [self.term_path]

                for matchpath in matchpaths:
                    if command[0] == "stdin":
                        text = command[1].replace("\r\n","\n").replace("\r","\n")
                        Term_manager.term_write(matchpath, text)
                    else:
                        Term_manager.remote_term_call(matchpath, *command)
                    if kill_term:
                        kill_remote(matchpath, from_user)

        except Exception as excp:
            logging.error("TermSocket.on_message: ERROR %s", excp)
            self.term_remote_call("errmsg", str(excp))
            return

def kill_remote(term_path, user):
    for client_id in TermSocket.get_path_termsockets(term_path):
        tsocket = TermSocket.get_termsocket(client_id)
        if tsocket:
            tsocket.term_remote_call("document", BANNER_HTML+'<p>CLOSED TERMINAL<p><a href="/">Home</a>')
            tsocket.on_close()
            tsocket.close()
    try:
        Term_manager.kill_term(term_path)
    except Exception:
        pass

class GoogleOAuth2LoginHandler(tornado.web.RequestHandler, tornado.auth.GoogleOAuth2Mixin):
    @tornado.gen.coroutine
    def get(self):
        if self._OAUTH_SETTINGS_KEY not in self.settings or not self.settings[self._OAUTH_SETTINGS_KEY]["key"]:
            self.setup_msg("Google Authentication has not yet been set up for this server.")
            return
        ##logging.error("GoogleOAuth2LoginHandler: req=%s", self.request.uri)
        auth_uri = Term_settings["server_url"]+"/_gauth"
        if not self.get_argument('code', False):
            term_cauth = self.get_argument("term_cauth", "")
            term_path = "/".join(self.request.path.split("/")[2:]) # Strip out /_gauth from path
            if term_path == "_info":
                self.setup_msg("Google Authentication Setup Instructions")
                return

            state_param = ",".join([term_path, term_cauth])
            yield self.authorize_redirect(
                redirect_uri=auth_uri,
                client_id=self.settings['google_oauth']['key'],
                scope=['profile', 'email'],
                response_type='code',
                extra_params={'approval_prompt': 'auto', 'state': state_param})
        else:
            try:
                state_value = self.get_argument('state', "")
                user = yield self.get_authenticated_user(
                    redirect_uri=auth_uri,
                    code=self.get_argument('code'))
                
                comps = user['id_token'].split('.')
                if len(comps) != 3:
                    raise ErrorMessage('Wrong number of comps in Google id token: %s' % (user,)) 

                b64string = comps[1].encode('ascii') 
                padded = b64string + '=' * (4 - len(b64string) % 4) 
                user_info = json.loads(base64.urlsafe_b64decode(padded))

                vals = state_value.split(",")
                if len(vals) != 2: 
                    raise ErrorMessage('Invalid state values: %s' % state_value)
                term_path, term_cauth = vals

                term_email = user_info.get("email", "").lower()
                if not term_email or not user_info.get("email_verified", False):
                    raise ErrorMessage("GoogleOAuth2LoginHandler: No valid email in user info")
                if term_path == "_test":
                    self.write(BANNER_HTML+'<p>Google authentication test succeeded for '+term_email)
                    self.finish()
                    return

                if Term_settings["auth_emails"] and term_email not in Term_settings["auth_emails"]:
                    self.write(BANNER_HTML+'<p>Account <em>%s</em> not authorized for access.<p><a href="https://accounts.google.com/AccountChooser?hl=en">Click here</a> to sign in with a different Google account' % term_email)
                    self.finish()
                    return

                email_name, email_domain = term_email.split("@")
                term_user = email_name.replace(".","")

                authstate = None
                state_id = self.get_cookie(COOKIE_NAME)
                if state_id:
                    authstate = TermSocket.get_state(state_id)
                    if authstate and (authstate.get("email","") != term_email or authstate.get("user","") != term_user):
                        TermSocket.drop_state(state_id)
                        authstate = None
                if not authstate:
                    authstate = TermSocket.add_state(user=term_user, email=term_email)
                    self.set_cookie(COOKIE_NAME, authstate["state_id"])

                query = {}
                if term_cauth:
                    query["cauth"] = term_cauth
                url = "/"+term_path
                if query:
                    url += "?"+urlencode(query)
                logging.info("GoogleOAuth2LoginHandler: email=%s, url=%s, %s", term_email, url, user_info)
                self.redirect(url)
            except Exception as excp:
                logging.error("Error in Google Authentication: "+str(excp))
                self.write(BANNER_HTML+'<p>Error in Google Authentication: '+(str(excp) if isinstance(excp, ErrorMessage) else ""))
                self.finish()

    def setup_msg(self, header):
        msg = """<pre><em>%s</em>
<p>
If you are the administrator, please create the file
<b>~/.pyxterm.json</b> for the user account running <b>pyxterm</b>.
The file should contain the following Google OAuth info:<br>
    <b>{"google_oauth": {"key": "...", "secret": "..."},
        "auth_emails": ["user1@gmail.com", "user2@gmail.com"] }}</b>

Ensure that your web application has the following URI settings:

 <em>Authorized Javascript origins:</em> <b>%s</b>

 <em>Authorized Redirect URI:</em> <b>%s/_gauth</b>

If you have not set up the pyxterm web app for Google authentication, here is how to do it:
    * Go to the Google Dev Console at <a href="https://console.developers.google.com" target="_blank">https://console.developers.google.com</a>
    * Select a project, or create a new one.
    * In the sidebar on the left, select <em>APIs & Auth</em>.
    * In the sidebar on the left, select <em>Consent Screen</em> to customize the Product name etc.
    * In the sidebar on the left, select <em>Credentials</em>.
    * In the OAuth section of the page, select <em>Create New Client ID</em>.
    * Edit settings to set the Authorized URIs to the values shown above.
    * Copy the web application "Client ID key" and "Client secret" to the settings file
    * Restart the server
</pre>
"""
        self.write(msg % (header, Term_settings["server_url"], Term_settings["server_url"]))
        self.finish()
        return

def run_server(options, args):
    global IO_loop, Http_server, Term_settings, Term_manager
    import signal

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
        if options.auth_type in ("login", "ssh"):
            sys.exit("--auth_type=login/ssh cannot be combined with specified shell command")
        shell_command = args[:]
    elif options.auth_type == "login":
        if os.geteuid():
            sys.exit("Error: Must run server as root for --auth_type=login")
        if not options.https and external_host != "localhost":
            sys.exit("Error: At this time --auth_type=login is permitted only with https or localhost (for security reasons)")
        shell_command = ["login"]
    elif options.auth_type == "ssh":
        if not pyxshell.match_program_name("sshd"):
            sys.exit("Error: sshd must be running for --auth_type=ssh")
        shell_command = ["ssh"]
    else:
        shell_command = ["bash"]

    tem_str = options.term_options.strip().replace(" ","")
    term_options = set(tem_str.split(",") if tem_str else [])
    Term_settings = {"type": options.term_type, "max_terminals": options.max_terminals,
                     "https": options.https, "logging": options.logging,
                     "options": term_options, "server_url": server_url, "auth_type": options.auth_type}

    pyx_settings_file = os.path.join(os.path.expanduser("~"), ".pyxterm.json")
    pyx_settings = {}
    if os.path.isfile(pyx_settings_file):
        try:
            with open(pyx_settings_file) as f:
                pyx_settings = json.loads(f.read().strip())
                print("***** Read settings from", pyx_settings_file, file=sys.stderr)
        except Exception as excp:
            sys.exit("Error in reading settings file %s: %s" % (pyx_settings_file, excp))

    app_settings = {"log_function": lambda x:None}

    if options.auth_type == "google":
        if "google_oauth" not in pyx_settings:
            sys.exit("'google_oauth' client ID and secret should be provided in settings file %s" % pyx_settings_file)
        app_settings["google_oauth"] = pyx_settings["google_oauth"]

        if "auth_emails" not in pyx_settings:
            sys.exit("'auth_emails' list should be provided in settings file %s" % pyx_settings_file)
        auth_emails = [x.strip().lower() for x in pyx_settings["auth_emails"]]
        Term_settings["auth_emails"] = set(auth_emails)
        print("Authorized email addresses: %s" % (",".join(auth_emails) if auth_emails else "ALL"))

    Term_manager = pyxshell.TermManager(TermSocket.term_remote_callback, shell_command=shell_command, server_url="", term_settings=Term_settings)

    handlers = [(r"/_gauth.*", GoogleOAuth2LoginHandler),   # Does not work with trailing slash!
                (r"/_websocket/.*", TermSocket),
                (STATIC_PREFIX+r"(.*)", tornado.web.StaticFileHandler, {"path": Doc_rootdir}),
                (r"/().*", tornado.web.StaticFileHandler, {"path": Doc_rootdir, "default_filename": "index.html"}),
                ]

    application = tornado.web.Application(handlers, **app_settings)

    ##logging.warning("DocRoot: "+Doc_rootdir);

    IO_loop = tornado.ioloop.IOLoop.instance()

    ssl_options = None
    if options.https or options.client_cert:
        if options.client_cert:
            certfile = options.client_cert
            cert_dir = os.path.dirname(certfile) or os.getcwd()
            if certfile.endswith(".crt"):
                keyfile = certfile[:-4] + ".key"
            else:
                keyfile = ""
        else:
            cert_dir = "."
            server_name = "localhost"
            certfile = os.path.join(cert_dir, server_name+".pem")
            keyfile = ""

        new = not os.path.exists(certfile) and (not keyfile or not os.path.exists(keyfile))
        print("Generating" if new else "Using", "SSL cert", certfile, file=sys.stderr)
        fingerprint = ssl_cert_gen(certfile, keyfile, server_name, cwd=cert_dir, new=new, clientname="term-local" if options.client_cert else "")
        if not fingerprint:
            print("pyxterm: Failed to generate server SSL certificate", file=sys.stderr)
            sys.exit(1)
        print(fingerprint, file=sys.stderr)

        ssl_options = {"certfile": certfile}
        if keyfile:
            ssl_options["keyfile"] = keyfile

        if options.client_cert:
            if options.client_cert == ".":
                ssl_options["ca_certs"] = certfile
            elif not os.path.exists(options.client_cert):
                print("Client cert file %s not found" % options.client_cert, file=sys.stderr)
                sys.exit(1)
            else:
                ssl_options["ca_certs"] = options.client_cert
            ssl_options["cert_reqs"] = ssl.CERT_REQUIRED

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
            pyxshell.open_browser(new_url)
        except Exception as excp:
            print("Error in creating terminal; please open URL %s in browser (%s)" % (new_url, excp), file=sys.stderr)

    def stop_server():
        global Http_server
        print("\nStopping server", file=sys.stderr)
        if Http_server:
            Http_server.stop()
            Http_server = None
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
        if Term_manager:
            Term_manager.shutdown()
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
    parser.add_option("", "--auth_type", dest="auth_type", default="ssh",
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
