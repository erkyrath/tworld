
"""
The protocol between tweb and tworld is brutally simple:

- Message length (4 bytes): excludes length/type/connid
- Message type (4 bytes)
- Connection ID (4 bytes)
- Message content (length bytes)

The length and connid are little-endian integers.
The type is four ASCII bytes.
The content is always JSON, UTF-8, and starts and ends with "{}".
"""

import types
import struct
import json

HEADER_LENGTH = 12  # three four-byte fields

msgtype = types.SimpleNamespace(
    say = b'SAY ',
    connect = b'CONN',
    )

def namespace_wrapper(map):
    return types.SimpleNamespace(**map)

def check_buffer(buf, namespace=False):
    """
    Given a mutable bytearray, see if it begins with a complete message.
    If it does, parse it out and return (type, content). The type will be
    a bytes, the content will be a dict. The message chunk is then sliced
    out of the buffer.

    If namespace is true, the content object will wind up as a
    SimpleNamespace instead of a dict. (That is, you will be able to
    do obj.foo instead of obj['foo']. But any keys that are not keyable
    will have to be read using getattr().)

    If the content fails to parse, this throws an exception, but the
    message will still be sliced out of the buffer.
    """
    
    if len(buf) < HEADER_LENGTH:
        return None
    
    (datlen,) = struct.unpack('<1I', buf[0:4])
    msglen = datlen + HEADER_LENGTH
    if len(buf) < msglen:
        return None

    msgtype = bytes(buf[4:8])
    (connid,) = struct.unpack('<1I', buf[8:12])
    msgdat = buf[12:msglen]
    
    buf[0:msglen] = b''

    object_hook = namespace_wrapper if namespace else None

    msgstr = msgdat.decode()  # Decode UTF-8
    msgobj = json.loads(msgstr, object_hook=object_hook)  # Decode JSON
    if (type(msgobj) not in [dict, types.SimpleNamespace]):
        raise ValueError('Message was not an object')
    return (msgtype, connid, msgobj)

def message(typ, connid, obj):
    msgstr = json.dumps(obj)
    msgdat = msgstr.encode()  # Encode UTF-8
    blen = struct.pack('<1I', len(msgdat))
    bconnid = struct.pack('<1I', connid)
    assert len(typ) == 4
    return blen + typ + bconnid + msgdat
