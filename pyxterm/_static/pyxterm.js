/**
 * pyxterm: Basic Python socket implementation for term.js
 *          https://github.com/chjj/term.js/
 *
 * Requires term.js, pyxserver.py, pyxterm.py
 *
 * To test, run:
 *
 *    ./pyxserver.py --terminal
 *
 * Distributed under the MIT License, like term.js
 *
 * Modified by: R. Saravanan <sarava@sarava.net> 2014
 * Original Copyright (c) 2012-2013, Christopher Jeffrey (MIT License)
 */

;(function() {

var document = this.document
  , window = this;

var EventEmitter = Terminal.EventEmitter
  , inherits = Terminal.inherits
  , on = Terminal.on
  , off = Terminal.off
  , cancel = Terminal.cancel;

function Pyxterm(socket, remoteParams, options) {
    // Wrapper class for Terminal to interface with WebSock
    var self = this;

    this.socket = socket;
    this.remoteParams = remoteParams;

    if (remoteParams.state_id)
	setAuth(remoteParams.state_id);

    Terminal.call(this, options)

    this.on('data', function(data) {
        self.socket.emit('stdin', data);
    });

    this.on('title', function(title) {
        document.title = title;
    });

    this.emit('title', remoteParams.term_path);
    this.open(document.body);

    self.socket.on('stdout', function(data) {
        self.write(data);
    });

    self.socket.on('disconnect', function(code) {
        self.write("\r\n\r\n[CLOSED]\r\n");
        //self.destroy();
    });

    this.socket.remote_emit("set_size", options.rows, options.cols, window.innerHeight, window.innerWidth);

}

inherits(Pyxterm, Terminal);


/**
 * WebSocket
 */

function WebSock(term_path) {
    var self = this;

    EventEmitter.call(this);

    this.failed = false;
    this.opened = false;
    this.closed = false;

    if (!term_path) {
	var comps = window.location.pathname.split("/").slice(1);
	term_path = comps.length ? comps[0] : "new";
    }
    this.term_path = term_path;

    var protocol = (window.location.protocol.indexOf("https") === 0) ? "wss" : "ws";
    this.ws_url = protocol+":/"+"/"+window.location.host+"/_websocket/"+this.term_path
    if (window.location.search)
	this.ws_url += window.location.search;
    this.ws = new WebSocket(this.ws_url);
    this.ws.binaryType = "arraybuffer";
    this.ws.onopen = bind_method(this, this.onopen);
    this.ws.onmessage = bind_method(this, this.onmessage);
    this.ws.onclose = bind_method(this, this.onclose);
    console.log("WebSock.__init__: ", this._events);

    this.on("abort", function() {
	console.log("WebSock.abort: ");
	self.close();
    });

    this.on("stdin", function(text, type_ahead) {
	// Send stdin text to terminal
	self.remote_emit("stdin", text);
    });

    this.on("kill_term", function(text) {
	self.remote_emit("kill_term");
    });
}

inherits(WebSock, EventEmitter);

WebSock.prototype.close = function() {
  console.log("WebSock.close: ");
  if (this.closed)
    return;

  this.closed = true;
  this.emit("close");
  try {
    this.ws.close();
  } catch(err) {
  }
}

WebSock.prototype.write = function(msg) {
// Write object as JSON (but send ArrayBuffers directly)
    try {
	if (this.ws.readyState > WebSocket.OPEN)
	    throw "Websocket closed";
	this.ws.send( (msg instanceof ArrayBuffer) ? msg : JSON.stringify(msg) );
    } catch(err) {
	if (window.confirm("Error in websocket ("+err+"). Reload page?")) {
	    window.location.reload();
	}
    }
}

WebSock.prototype.remote_emit = function() {
    this.write([].slice.call(arguments));
}

WebSock.prototype.onopen = function(evt) {
  console.log("WebSock.onopen: ");
  this.emit("open");
}

WebSock.prototype.onclose = function(evt) {
  console.log("WebSock.onclose: ");
  if (!this.opened && !this.closed && !this.failed) {
      this.failed = true;
      alert("pyxterm: Failed to open websocket: "+this.ws_url);
  } else {
      //PopAlert("Terminal closed");
  }

  if (!this.closed) {
    this.closed = true;
    this.emit("close");
  }
}

WebSock.prototype.onmessage = function(evt) {
    if (this.closed)
	return;

    if (!this.opened) {
	// Validate
	this.opened = true;
	this.emit("connect");
    }

    var payload = evt.data;
    //console.log("WebSock.onmessage: "+payload);

    try {
	var command;
	var content = null;
	if (payload instanceof ArrayBuffer) {
	    console.log("WebSock.onmessage: ArrayBuffer: "+payload.byteLength);
	    var delim = "\n\n";
	    var offset = abIndexOf(delim, payload);
	    if (offset < 0)
		throw("Delimiter not found in binary message");
	    content = payload.slice(2*(offset+delim.length));
	    var bufView = new Uint16Array(buf);
	    var msg_str = String.fromCharCode.apply(null, bufView.slice(0,offset));
	    command = JSON.parse(msg_str);
	} else {
	    command = JSON.parse(payload);
	}
	var action = command[0];

	var method = "on_" + action;
	if (!(method in this) && !(action in this._events)) {
	    console.log("WebSock.onmessage: Invalid remote method "+action);
	    this.remote_emit("errmsg", "Invalid remote action "+action);
	} else {
	    try {
		if (method in this)
		    this[method].apply(this, command[1]);

		if (action in this._events)
		    this.emit.apply(this, [action].concat(command[1]));
	    } catch(err) {
		console.log("WebSock.onmessage: Error in remote method "+action+" execution:", err, err.stack);
		this.remote_emit("errmsg", "Error in action "+action+": "+err);
	    }
	}
    } catch(err) {
	console.log("WebSock.onmessage", err, err.stack);
	this.remote_emit("errmsg", ""+err);
	this.close();
    }
}

WebSock.prototype.on_eval_js = function(command) {
    // Evaluate Javascript
    var stdout = "";
    var stderr = "";
    try {
	console.log("pyxterm.eval_js:", command);
	var evalout = eval(command);
	stdout = evalout ? evalout+"" : "";
	console.log("pyxterm.eval_js:", stdout);
    } catch (err) {
	stderr = err+"";
	console.log("pyxterm.eval_js:", stderr);
    }

    this.remote_emit("eval_output", stdout, stderr);
}

WebSock.prototype.on_errmsg = function(msg) {
    // Display console error message
    console.log("ERROR ", msg);
}

WebSock.prototype.on_alert = function(msg) {
    // Display browser alert
    console.log("ALERT ", msg);
    alert(msg);
}

WebSock.prototype.on_document = function(html) {
    // Overwrite document HTML
    document.documentElement.innerHTML = html;
}

WebSock.prototype.on_redirect = function(url, state_id) {
    // Redirect to URL
    if (state_id)
	setAuth(state_id);
    window.location = url;
}


/**
 * Helpers
 */

function bind_method(obj, method) {
  return function() {
    return method.apply(obj, arguments);
  }
}

// Cookies - http://www.quirksmode.org/js/cookies.html
function createCookie(name,value,days) {
	if (days) {
		var date = new Date();
		date.setTime(date.getTime()+(days*24*60*60*1000));
		var expires = "; expires="+date.toGMTString();
	}
	else var expires = "";
	document.cookie = name+"="+value+expires+"; path=/";
}

function readCookie(name) {
	var nameEQ = name + "=";
	var ca = document.cookie.split(';');
	for(var i=0;i < ca.length;i++) {
		var c = ca[i];
		while (c.charAt(0)==' ') c = c.substring(1,c.length);
		if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length,c.length);
	}
	return null;
}

function eraseCookie(name) {
	createCookie(name,"",-1);
}

var AUTH_COOKIE = "PYXTERM_AUTH";
var AUTH_DIGITS = 12;      // Hex digits for form authentication

function setAuth(value) {
    return createCookie(AUTH_COOKIE, value);
}

function getQueryAuth() {
    return readCookie(AUTH_COOKIE).substr(0,AUTH_DIGITS);
}

// ArrayBuffer to String conversion (using UTF-16 encoding)
// http://updates.html5rocks.com/2012/06/How-to-convert-ArrayBuffer-to-and-from-String
function ab2str(buf) {
    return String.fromCharCode.apply(null, new Uint16Array(buf));
}

function str2ab(str) {
    var buf = new ArrayBuffer(str.length*2); // 2 bytes for each char
    var bufView = new Uint16Array(buf);
    for (var i=0, strLen=str.length; i<strLen; i++) {
        bufView[i] = str.charCodeAt(i);
    }
    return buf;
}

function abIndexOf(s, buf) {
// Return indexOf string s in Uint16 ArrayBuffer
    var bufView = new Uint16Array(buf);
    var firstCode = s.charCodeAt(0);
    var j = -1;
    var offset = -1;
    while (offset < 0 && j < bufView.length-1) {
	j = bufView.indexOf(firstCode, j+1);
	if (j < 0)
	    break;
	offset = j;
	for (var k=1; k<s.length; k++) {
	    if (bufView[j+k] != s.charCodeAt(k)) {
		offset = -1;
		break;
	    }
	}
    }
    return offset;
}

/**
 * Expose
 */

Pyxterm.getQueryAuth = getQueryAuth;

this.WebSock = WebSock;
this.Pyxterm = Pyxterm;

}).call(function() {
  return this || (typeof window !== 'undefined' ? window : global);
}());
