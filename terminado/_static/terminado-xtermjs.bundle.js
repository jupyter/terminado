require=(function(){function r(e,n,t){function o(i,f){if(!n[i]){if(!e[i]){var c="function"==typeof require&&require;if(!f&&c)return c(i,!0);if(u)return u(i,!0);var a=new Error("Cannot find module '"+i+"'");throw a.code="MODULE_NOT_FOUND",a}var p=n[i]={exports:{}};e[i][0].call(p.exports,function(r){var n=e[i][1][r];return o(n||r)},p,p.exports,r,e,n,t)}return n[i].exports}for(var u="function"==typeof require&&require,i=0;i<t.length;i++)o(t[i]);return o}return r})()({1:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, '__esModule', { value: true });

function typeError(tag, expected) {
    throw new TypeError(`unexpected tag 0x${tag.toString(16)} (${expected} expected)`);
}

// positive fixint: 0xxx xxxx
function posFixintTag(i) {
    return i & 0x7f;
}
function isPosFixintTag(tag) {
    return (tag & 0x80) === 0;
}
function readPosFixint(tag) {
    return tag & 0x7f;
}
// negative fixint: 111x xxxx
function negFixintTag(i) {
    return 0xe0 | (i & 0x1f);
}
function isNegFixintTag(tag) {
    return (tag & 0xe0) == 0xe0;
}
function readNegFixint(tag) {
    return tag - 0x100;
}
// fixstr: 101x xxxx
function fixstrTag(length) {
    return 0xa0 | (length & 0x1f);
}
function isFixstrTag(tag) {
    return (tag & 0xe0) == 0xa0;
}
function readFixstr(tag) {
    return tag & 0x1f;
}
// fixarray: 1001 xxxx
function fixarrayTag(length) {
    return 0x90 | (length & 0x0f);
}
function isFixarrayTag(tag) {
    return (tag & 0xf0) == 0x90;
}
function readFixarray(tag) {
    return tag & 0x0f;
}
// fixmap: 1000 xxxx
function fixmapTag(length) {
    return 0x80 | (length & 0x0f);
}
function isFixmapTag(tag) {
    return (tag & 0xf0) == 0x80;
}
function readFixmap(tag) {
    return tag & 0x0f;
}

function createWriteBuffer() {
    let view = new DataView(new ArrayBuffer(64));
    let n = 0;
    function need(x) {
        if (n + x > view.byteLength) {
            const arr = new Uint8Array(Math.max(n + x, view.byteLength + 64));
            arr.set(new Uint8Array(view.buffer.slice(0, n)));
            view = new DataView(arr.buffer);
        }
    }
    return {
        put(v) {
            need(v.byteLength);
            (new Uint8Array(view.buffer)).set(new Uint8Array(v), n);
            n += v.byteLength;
        },
        putI8(v) {
            need(1);
            view.setInt8(n, v);
            ++n;
        },
        putI16(v) {
            need(2);
            view.setInt16(n, v);
            n += 2;
        },
        putI32(v) {
            need(4);
            view.setInt32(n, v);
            n += 4;
        },
        putI64(v) {
            need(8);
            const neg = v < 0;
            if (neg) {
                v = -v;
            }
            let hi = (v / 0x100000000) | 0;
            let lo = (v % 0x100000000) | 0;
            if (neg) {
                // 2s complement
                lo = (~lo + 1) | 0;
                hi = lo === 0 ? (~hi + 1) | 0 : ~hi;
            }
            view.setUint32(n, hi);
            view.setUint32(n + 4, lo);
            n += 8;
        },
        putUi8(v) {
            need(1);
            view.setUint8(n, v);
            ++n;
        },
        putUi16(v) {
            need(2);
            view.setUint16(n, v);
            n += 2;
        },
        putUi32(v) {
            need(4);
            view.setUint32(n, v);
            n += 4;
        },
        putUi64(v) {
            need(8);
            view.setUint32(n, (v / 0x100000000) | 0);
            view.setUint32(n + 4, v % 0x100000000);
            n += 8;
        },
        putF(v) {
            need(8);
            view.setFloat64(n, v);
            n += 8;
        },
        ui8array() {
            return new Uint8Array(view.buffer.slice(0, n));
        },
    };
}
function createReadBuffer(buf) {
    let view = new DataView(ArrayBuffer.isView(buf) ? buf.buffer : buf);
    let n = 0;
    return {
        peek() {
            return view.getUint8(n);
        },
        get(len) {
            n += len;
            return view.buffer.slice(n - len, n);
        },
        getI8() {
            return view.getInt8(n++);
        },
        getI16() {
            n += 2;
            return view.getInt16(n - 2);
        },
        getI32() {
            n += 4;
            return view.getInt32(n - 4);
        },
        getI64() {
            n += 8;
            const hi = view.getInt32(n - 8);
            const lo = view.getUint32(n - 4);
            return hi * 0x100000000 + lo;
        },
        getUi8() {
            return view.getUint8(n++);
        },
        getUi16() {
            n += 2;
            return view.getUint16(n - 2);
        },
        getUi32() {
            n += 4;
            return view.getUint32(n - 4);
        },
        getUi64() {
            n += 8;
            const hi = view.getUint32(n - 8);
            const lo = view.getUint32(n - 4);
            return hi * 0x100000000 + lo;
        },
        getF32() {
            n += 4;
            return view.getFloat32(n - 4);
        },
        getF64() {
            n += 8;
            return view.getFloat64(n - 8);
        },
    };
}
function putBlob(buf, blob, baseTag) {
    const n = blob.byteLength;
    if (n <= 255) {
        buf.putUi8(baseTag);
        buf.putUi8(n);
    }
    else if (n <= 65535) {
        buf.putUi8(baseTag + 1);
        buf.putUi16(n);
    }
    else if (n <= 4294967295) {
        buf.putUi8(baseTag + 2);
        buf.putUi32(n);
    }
    else {
        throw new RangeError("length limit exceeded");
    }
    buf.put(blob);
}
function getBlob(buf) {
    const tag = buf.getUi8();
    let n;
    switch (tag) {
        case 192 /* Nil */:
            n = 0;
            break;
        case 196 /* Bin8 */:
        case 217 /* Str8 */:
            n = buf.getUi8();
            break;
        case 197 /* Bin16 */:
        case 218 /* Str16 */:
            n = buf.getUi16();
            break;
        case 198 /* Bin32 */:
        case 219 /* Str32 */:
            n = buf.getUi32();
            break;
        default:
            if (!isFixstrTag(tag)) {
                typeError(tag, "bytes or string");
            }
            n = readFixstr(tag);
    }
    return buf.get(n);
}
function putArrHeader(buf, n) {
    if (n < 16) {
        buf.putUi8(fixarrayTag(n));
    }
    else {
        putCollectionHeader(buf, 220 /* Array16 */, n);
    }
}
function getArrHeader(buf, expect) {
    const tag = buf.getUi8();
    const n = isFixarrayTag(tag)
        ? readFixarray(tag)
        : getCollectionHeader(buf, tag, 220 /* Array16 */, "array");
    if (expect != null && n !== expect) {
        throw new Error(`invalid array header size ${n}`);
    }
    return n;
}
function putMapHeader(buf, n) {
    if (n < 16) {
        buf.putUi8(fixmapTag(n));
    }
    else {
        putCollectionHeader(buf, 222 /* Map16 */, n);
    }
}
function getMapHeader(buf, expect) {
    const tag = buf.getUi8();
    const n = isFixmapTag(tag)
        ? readFixmap(tag)
        : getCollectionHeader(buf, tag, 222 /* Map16 */, "map");
    if (expect != null && n !== expect) {
        throw new Error(`invalid map header size ${n}`);
    }
    return n;
}
function putCollectionHeader(buf, baseTag, n) {
    if (n <= 65535) {
        buf.putUi8(baseTag);
        buf.putUi16(n);
    }
    else if (n <= 4294967295) {
        buf.putUi8(baseTag + 1);
        buf.putUi32(n);
    }
    else {
        throw new RangeError("length limit exceeded");
    }
}
function getCollectionHeader(buf, tag, baseTag, typename) {
    switch (tag) {
        case 192 /* Nil */:
            return 0;
        case baseTag: // 16 bit
            return buf.getUi16();
        case baseTag + 1: // 32 bit
            return buf.getUi32();
        default:
            typeError(tag, typename);
    }
}

const Any = {
    enc(buf, v) {
        typeOf(v).enc(buf, v);
    },
    dec(buf) {
        return tagType(buf.peek()).dec(buf);
    },
};
const Nil = {
    enc(buf, v) {
        buf.putUi8(192 /* Nil */);
    },
    dec(buf) {
        const tag = buf.getUi8();
        if (tag !== 192 /* Nil */) {
            typeError(tag, "nil");
        }
        return null;
    },
};
const Bool = {
    enc(buf, v) {
        buf.putUi8(v ? 195 /* True */ : 194 /* False */);
    },
    dec(buf) {
        const tag = buf.getUi8();
        switch (tag) {
            case 192 /* Nil */:
            case 194 /* False */:
                return false;
            case 195 /* True */:
                return true;
            default:
                typeError(tag, "bool");
        }
    },
};
const Int = {
    enc(buf, v) {
        if (-128 <= v && v <= 127) {
            if (v >= 0) {
                buf.putUi8(posFixintTag(v));
            }
            else if (v > -32) {
                buf.putUi8(negFixintTag(v));
            }
            else {
                buf.putUi8(208 /* Int8 */);
                buf.putUi8(v);
            }
        }
        else if (-32768 <= v && v <= 32767) {
            buf.putI8(209 /* Int16 */);
            buf.putI16(v);
        }
        else if (-2147483648 <= v && v <= 2147483647) {
            buf.putI8(210 /* Int32 */);
            buf.putI32(v);
        }
        else {
            buf.putI8(211 /* Int64 */);
            buf.putI64(v);
        }
    },
    dec(buf) {
        const tag = buf.getUi8();
        if (isPosFixintTag(tag)) {
            return readPosFixint(tag);
        }
        else if (isNegFixintTag(tag)) {
            return readNegFixint(tag);
        }
        switch (tag) {
            case 192 /* Nil */:
                return 0;
            // signed int types
            case 208 /* Int8 */:
                return buf.getI8();
            case 209 /* Int16 */:
                return buf.getI16();
            case 210 /* Int32 */:
                return buf.getI32();
            case 211 /* Int64 */:
                return buf.getI64();
            // unsigned int types
            case 204 /* Uint8 */:
                return buf.getUi8();
            case 205 /* Uint16 */:
                return buf.getUi16();
            case 206 /* Uint32 */:
                return buf.getUi32();
            case 207 /* Uint64 */:
                return buf.getUi64();
            default:
                typeError(tag, "int");
        }
    },
};
const Uint = {
    enc(buf, v) {
        if (v < 0) {
            throw new Error(`not an uint: ${v}`);
        }
        else if (v <= 127) {
            buf.putUi8(posFixintTag(v));
        }
        else if (v <= 255) {
            buf.putUi8(204 /* Uint8 */);
            buf.putUi8(v);
        }
        else if (v <= 65535) {
            buf.putUi8(205 /* Uint16 */);
            buf.putUi16(v);
        }
        else if (v <= 4294967295) {
            buf.putUi8(206 /* Uint32 */);
            buf.putUi32(v);
        }
        else {
            buf.putUi8(207 /* Uint64 */);
            buf.putUi64(v);
        }
    },
    dec(buf) {
        const v = Int.dec(buf);
        if (v < 0) {
            throw new RangeError("uint underflow");
        }
        return v;
    },
};
const Float = {
    enc(buf, v) {
        buf.putUi8(203 /* Float64 */);
        buf.putF(v);
    },
    dec(buf) {
        const tag = buf.getUi8();
        switch (tag) {
            case 192 /* Nil */:
                return 0;
            case 202 /* Float32 */:
                return buf.getF32();
            case 203 /* Float64 */:
                return buf.getF64();
            default:
                typeError(tag, "float");
        }
    },
};
const Bytes = {
    enc(buf, v) {
        putBlob(buf, v, 196 /* Bin8 */);
    },
    dec: getBlob,
};
const Str = {
    enc(buf, v) {
        const utf8 = toUTF8(v);
        if (utf8.byteLength < 32) {
            buf.putUi8(fixstrTag(utf8.byteLength));
            buf.put(utf8);
        }
        else {
            putBlob(buf, utf8, 217 /* Str8 */);
        }
    },
    dec(buf) {
        return fromUTF8(getBlob(buf));
    },
};
const Time = {
    enc(buf, v) {
        const ms = v.getTime();
        buf.putUi8(199 /* Ext8 */);
        buf.putUi8(12);
        buf.putI8(-1);
        buf.putUi32((ms % 1000) * 1000000);
        buf.putI64(ms / 1000);
    },
    dec(buf) {
        const tag = buf.getUi8();
        switch (tag) {
            case 214 /* FixExt4 */: // 32-bit seconds
                if (buf.getI8() === -1) {
                    return new Date(buf.getUi32() * 1000);
                }
                break;
            case 215 /* FixExt8 */: // 34-bit seconds + 30-bit nanoseconds
                if (buf.getI8() === -1) {
                    const lo = buf.getUi32();
                    const hi = buf.getUi32();
                    // seconds: hi + (lo&0x3)*0x100000000
                    // nanoseconds: lo>>2 == lo/4
                    return new Date((hi + (lo & 0x3) * 0x100000000) * 1000 + lo / 4000000);
                }
                break;
            case 199 /* Ext8 */: // 64-bit seconds + 32-bit nanoseconds
                if (buf.getUi8() === 12 && buf.getI8() === -1) {
                    const ns = buf.getUi32();
                    const s = buf.getI64();
                    return new Date(s * 1000 + ns / 1000000);
                }
                break;
        }
        typeError(tag, "time");
    },
};
const Arr = TypedArr(Any);
const Map = TypedMap(Any, Any);
function TypedArr(valueT) {
    return {
        encHeader: putArrHeader,
        decHeader: getArrHeader,
        enc(buf, v) {
            putArrHeader(buf, v.length);
            v.forEach(x => valueT.enc(buf, x));
        },
        dec(buf) {
            const res = [];
            for (let n = getArrHeader(buf); n > 0; --n) {
                res.push(valueT.dec(buf));
            }
            return res;
        },
    };
}
function TypedMap(keyT, valueT) {
    return {
        encHeader: putMapHeader,
        decHeader: getMapHeader,
        enc(buf, v) {
            const props = Object.keys(v);
            putMapHeader(buf, props.length);
            props.forEach(p => {
                keyT.enc(buf, p);
                valueT.enc(buf, v[p]);
            });
        },
        dec(buf) {
            const res = {};
            for (let n = getMapHeader(buf); n > 0; --n) {
                const k = keyT.dec(buf);
                res[k] = valueT.dec(buf);
            }
            return res;
        },
    };
}
function structEncoder(fields) {
    const ordinals = Object.keys(fields);
    return (buf, v) => {
        putMapHeader(buf, ordinals.length);
        ordinals.forEach(ord => {
            const f = fields[ord];
            Int.enc(buf, Number(ord));
            f[1].enc(buf, v[f[0]]);
        });
    };
}
function structDecoder(fields) {
    return (buf) => {
        const res = {};
        for (let n = getMapHeader(buf); n > 0; --n) {
            const f = fields[Int.dec(buf)];
            if (f) {
                res[f[0]] = f[1].dec(buf);
            }
            else {
                Any.dec(buf);
            }
        }
        return res;
    };
}
function Struct(fields) {
    return {
        enc: structEncoder(fields),
        dec: structDecoder(fields),
    };
}
function unionEncoder(branches) {
    return (buf, v) => {
        putArrHeader(buf, 2);
        const ord = branches.ordinalOf(v);
        Int.enc(buf, ord);
        branches[ord].enc(buf, v);
    };
}
function unionDecoder(branches) {
    return (buf) => {
        getArrHeader(buf, 2);
        const t = branches[Int.dec(buf)];
        if (!t) {
            throw new TypeError("invalid union type");
        }
        return t.dec(buf);
    };
}
function Union(branches) {
    return {
        enc: unionEncoder(branches),
        dec: unionDecoder(branches),
    };
}
function toUTF8(v) {
    const n = v.length;
    const bin = new Uint8Array(4 * n);
    let pos = 0, i = 0, c;
    while (i < n) {
        c = v.charCodeAt(i++);
        if ((c & 0xfc00) === 0xd800) {
            c = (c << 10) + v.charCodeAt(i++) - 0x35fdc00;
        }
        if (c < 0x80) {
            bin[pos++] = c;
        }
        else if (c < 0x800) {
            bin[pos++] = 0xc0 + (c >> 6);
            bin[pos++] = 0x80 + (c & 0x3f);
        }
        else if (c < 0x10000) {
            bin[pos++] = 0xe0 + (c >> 12);
            bin[pos++] = 0x80 + ((c >> 6) & 0x3f);
            bin[pos++] = 0x80 + (c & 0x3f);
        }
        else {
            bin[pos++] = 0xf0 + (c >> 18);
            bin[pos++] = 0x80 + ((c >> 12) & 0x3f);
            bin[pos++] = 0x80 + ((c >> 6) & 0x3f);
            bin[pos++] = 0x80 + (c & 0x3f);
        }
    }
    return bin.buffer.slice(0, pos);
}
function fromUTF8(buf) {
    const bin = new Uint8Array(buf);
    let n, c, codepoints = [];
    for (let i = 0; i < bin.length;) {
        c = bin[i++];
        n = 0;
        switch (c & 0xf0) {
            case 0xf0:
                n = 3;
                break;
            case 0xe0:
                n = 2;
                break;
            case 0xd0:
            case 0xc0:
                n = 1;
                break;
        }
        if (n !== 0) {
            c &= (1 << (6 - n)) - 1;
            for (let k = 0; k < n; ++k) {
                c = (c << 6) + (bin[i++] & 0x3f);
            }
        }
        codepoints.push(c);
    }
    return String.fromCodePoint.apply(null, codepoints);
}
function typeOf(v) {
    switch (typeof v) {
        case "undefined":
            return Nil;
        case "boolean":
            return Bool;
        case "number":
            return !isFinite(v) || Math.floor(v) !== v ? Float
                : v < 0 ? Int
                    : Uint;
        case "string":
            return Str;
        case "object":
            return v === null ? Nil
                : Array.isArray(v) ? Arr
                    : v instanceof Uint8Array || v instanceof ArrayBuffer ? Bytes
                        : v instanceof Date ? Time
                            : Map;
        default:
            throw new TypeError(`unsupported type ${typeof v}`);
    }
}
function tagType(tag) {
    switch (tag) {
        case 192 /* Nil */:
            return Nil;
        case 194 /* False */:
        case 195 /* True */:
            return Bool;
        case 208 /* Int8 */:
        case 209 /* Int16 */:
        case 210 /* Int32 */:
        case 211 /* Int64 */:
            return Int;
        case 204 /* Uint8 */:
        case 205 /* Uint16 */:
        case 206 /* Uint32 */:
        case 207 /* Uint64 */:
            return Uint;
        case 202 /* Float32 */:
        case 203 /* Float64 */:
            return Float;
        case 196 /* Bin8 */:
        case 197 /* Bin16 */:
        case 198 /* Bin32 */:
            return Bytes;
        case 217 /* Str8 */:
        case 218 /* Str16 */:
        case 219 /* Str32 */:
            return Str;
        case 220 /* Array16 */:
        case 221 /* Array32 */:
            return Arr;
        case 222 /* Map16 */:
        case 223 /* Map32 */:
            return Map;
        case 214 /* FixExt4 */:
        case 215 /* FixExt8 */:
        case 199 /* Ext8 */:
            return Time;
        default:
            if (isPosFixintTag(tag) || isNegFixintTag(tag)) {
                return Int;
            }
            if (isFixstrTag(tag)) {
                return Str;
            }
            if (isFixarrayTag(tag)) {
                return Arr;
            }
            if (isFixmapTag(tag)) {
                return Map;
            }
            throw new TypeError(`unsupported tag ${tag}`);
    }
}

function encode(v, typ) {
    const buf = createWriteBuffer();
    (typ || Any).enc(buf, v);
    return buf.ui8array();
}
function decode(buf, typ) {
    return (typ || Any).dec(createReadBuffer(buf));
}

exports.Nil = Nil;
exports.Bool = Bool;
exports.Int = Int;
exports.Uint = Uint;
exports.Float = Float;
exports.Bytes = Bytes;
exports.Str = Str;
exports.TypedArr = TypedArr;
exports.TypedMap = TypedMap;
exports.Time = Time;
exports.Any = Any;
exports.Arr = Arr;
exports.Map = Map;
exports.Struct = Struct;
exports.Union = Union;
exports.structEncoder = structEncoder;
exports.structDecoder = structDecoder;
exports.unionEncoder = unionEncoder;
exports.unionDecoder = unionDecoder;
exports.encode = encode;
exports.decode = decode;


},{}],"/terminado-xtermjs":[function(require,module,exports){
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
},{"messagepack":1}]},{},[]);
