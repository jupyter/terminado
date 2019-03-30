/**
 * Swaps keys and values in the given object.
 * Non-string values will be converted to string in order to be used as key.
 *
 * @param {Object} object
 *  The keys and values to swap.
 * @return {Object}
 *  A new object with keys and values swapped.
 */
function swap(object){
  // the new object
  var swappedObject = {};
  // loop all keys
  for (var key in object) {
    // get the value to be used as key, converting it to string, if needed
    var value = typeof object[key] == "string" ? object[key] : object[key].toString();
    // add the swapped key/value pair
    swappedObject[value] = key;
  }
  // return the new object
  return swappedObject;
}

// define the message formats
var formats = {
  JSON: {
    /**
     * Packs the given type and data as JSON-serialised string.
     *
     * @param {String} type
     *  A tornado message type.
     * @param {String|Array} message
     *  The message to pack.
     * @return {String}
     *  The JSON-serialised pack.
     */
    pack: function pack(type, message) {
      // init the pack with the type
      var pack = [type];

      // check if the message is an array
      if (message instanceof Array) {
        // add the message's elements to the pack
        pack = pack.concat(message);
      } else {
        // add the message to the pack
        pack.push(message);
      }

      // return the JSON-stringyfied pack
      return JSON.stringify(pack);
    },

    /**
     * Unpacks the given JSON-serialised string.
     *
     * @param {String} data
     *  A JSON-serialised string.
     * @return {Array}
     *  A type and the message (parts).
     */
    unpack: function unpack(data) {
      // return the unpacked type and message (parts)
      return JSON.parse(data);
    }
  },

  LightPayload: {
    // forward map mapping terminado types to LightPayload types
    TYPES: {
      stdin: "I",
      stdout: "O",
      set_size: "S",
      setup: "C",
      disconnect: "D",
      switch_format: "F"
    },
    // reverse map mapping LightPayload types to terminado types
    RTYPES: swap(this.TYPES),

    /**
     * Packs the given type and data as LightPayload-serialised string.
     *
     * @param {String} type
     *  A tornado message type.
     * @param {String|Array} message
     *  The message to pack.
     * @return {String}
     *  The LightPayload-serialised pack
     */
    pack: function pack(type, message) {
      // return the LightPayload-serialised string
      return this.TYPES[type] + "|" + (message instanceof Array ? message.join(",") : message);
    },

    /**
     * Unpacks the given LightPayload-serialised string.
     *
     * @param {String} data
     *  A LightPayload-serialised string.
     * @return {Array}
     *  A type and the message (parts).
     */
    unpack: function unpack(data) {
      // return the unpacked type and message
      return [this.RTYPES[data[0]], data.substring(2)];
    }
  },

  // forward map mapping terminado types to MessagePack types
  MessagePack: {
    TYPES: {
      stdin: 1,
      stdout: 2,
      set_size: 3,
      setup: 4,
      disconnect: 5,
      switch_format: 6
    },
    // reverse map mapping MessagePack types to terminado types
    RTYPES: swap(this.TYPES),

    /**
     * Packs the given type and data as MessagePack-serialised binary data.
     *
     * @param {String} type
     *  A tornado message type.
     * @param {String|Array} message
     *  The message to pack.
     * @return {ByteArray}
     *  The MessagePack-serialised pack.
     */
    pack: function pack(type, message) {
      // init the pack with the type mapped to the corresponding MessagePack type
      var pack = [this.TYPES[type]];

      // check if the message is an array
      if (message instanceof Array) {
        // add the message's elements to the pack
        pack = pack.concat(message);
      } else {
        // add the message to the pack
        pack.push(message);
      }

      // return the MessagePack-serialised pack
      return require("messagepack").encode(pack);
    },

    /**
     * Unpacks the given MessagePack-serialised binary data.
     *
     * @param {Blob} data
     *  A LightPayload-serialised string.
     * @return {Array}
     *  A type and the message (parts).
     */
    unpack: function unpack(data) {
      // a blob can only be read async, return a promise
      return new Promise(function(resolve, reject) {
        // create a file reader
        var fileReader = new FileReader();
        // when the blob is read
        fileReader.onload = function(event) {
          // unpack the MessagePack-serialised binary data
          var message = require("messagepack").decode(event.target.result);
          // map the MessagePack type to the corresponding terminado type
          message[0] = swap(formats.MessagePack.TYPES)[message[0].toString()];
          // resolve the promise
          resolve(message);
        };
        // on error reject the promise
        fileReader.onerror = reject;
        // on abort reject the promise
        fileReader.onabort = reject;
        // read the blob
        fileReader.readAsArrayBuffer(data);
      });
    }
  }
};

// define the terminado addon
var terminado = {
  // define the default message format
  DEFAULT_MESSAGE_FORMAT: "JSON",

  apply: function apply(terminalConstructor, messageFormat) {
    // default to the default message format, if no message format is given
    messageFormat = messageFormat || this.DEFAULT_MESSAGE_FORMAT;

    // closure cache the message format
    terminalConstructor.prototype.terminadoAttach = (function(messageFormat) {
      return function (socket, bidirectional, buffered) {
        return terminado.terminadoAttach(this, socket, bidirectional, buffered, messageFormat);
      };
    })(messageFormat);

    terminalConstructor.prototype.terminadoDetach = function (socket) {
      return terminado.terminadoDetach(this, socket);
    };
  },

  terminadoAttach: function terminadoAttach(term, socket, bidirectional, buffered, messageFormat) {
    // tell terminado which message format to use from now on
    socket.send(formats.JSON.pack("switch_format", messageFormat));

    var addonTerminal = term;
    bidirectional = (typeof bidirectional === 'undefined') ? true : bidirectional;
    addonTerminal.__socket = socket;
    addonTerminal.__flushBuffer = function () {
      addonTerminal.write(addonTerminal.__attachSocketBuffer);
      addonTerminal.__attachSocketBuffer = null;
    };
    addonTerminal.__pushToBuffer = function (data) {
      if (addonTerminal.__attachSocketBuffer) {
        addonTerminal.__attachSocketBuffer += data;
      }
      else {
        addonTerminal.__attachSocketBuffer = data;
        setTimeout(addonTerminal.__flushBuffer, 10);
      }
    };
    addonTerminal.__getMessage = function (ev) {
      function processMessage(message) {
        if (message[0] === 'stdout') {
          if (buffered) {
            addonTerminal.__pushToBuffer(message[1]);
          }
          else {
            addonTerminal.write(message[1]);
          }
        }
      }

      // unpack the data
      var data = formats[messageFormat].unpack(ev.data);
      // check if data is still unpacking
      if (data instanceof Promise) {
        // wait for the data to be unpacked and process it once unpacked
        data.then(processMessage);
      } else {
        // process the data
        processMessage(data);
      }          
    };
    addonTerminal.__sendData = function (data) {
      // pack and send the data
      socket.send(formats[messageFormat].pack("stdin", data));
    };
    addonTerminal.__setSize = function (size) {
      // pack and set the "set_size" data
      socket.send(formats[messageFormat].pack("set_size", [size.rows, size.cols]));
    };
    socket.addEventListener('message', addonTerminal.__getMessage);
    if (bidirectional) {
      addonTerminal.on('data', addonTerminal.__sendData);
    }
    addonTerminal.on('resize', addonTerminal.__setSize);
    socket.addEventListener('close', function () { return terminado.terminadoDetach(addonTerminal, socket); });
    socket.addEventListener('error', function () { return terminado.terminadoDetach(addonTerminal, socket); });
  },

  terminadoDetach: function terminadoDetach(term, socket) {
    var addonTerminal = term;
    addonTerminal.off('data', addonTerminal.__sendData);
    socket = (typeof socket === 'undefined') ? addonTerminal.__socket : socket;
    if (socket) {
      socket.removeEventListener('message', addonTerminal.__getMessage);
    }
    delete addonTerminal.__socket;
  }
};

// export the terminando addon
module.exports = terminado;