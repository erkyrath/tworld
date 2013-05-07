
"""
The protocol between tweb and tworld is brutally simple:

- Message length (4 bytes): excludes length/connid
- Connection ID (4 bytes): zero if for/from server, nonzero for/from player
- Message content (length bytes)

The length and connid are little-endian integers.
The content is always JSON, UTF-8, and starts and ends with "{}".
"""

import types
import struct
import json

HEADER_LENGTH = 8  # two four-byte fields

def namespace_wrapper(map):
    """
    Convert a dict to a SimpleNamespace. If you feed in {'key':'val'},
    you'll get out an object such that o.key is 'val'.
    (It's legal to feed in dict keys like 'x.y-z', but the result
    will have to be read using getattr().)
    """
    return types.SimpleNamespace(**map)

def check_buffer(buf, namespace=False):
    """
    Given a mutable bytearray, see if it begins with a complete message.
    If it does, parse it out and return (connid, message, content).
    (As an integer, bytes, decoded dict.) The message chunk is then sliced
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

    (connid,) = struct.unpack('<1I', buf[4:8])
    msgdat = buf[HEADER_LENGTH:msglen]
    
    buf[0:msglen] = b''

    object_hook = namespace_wrapper if namespace else None

    msgstr = msgdat.decode()  # Decode UTF-8
    msgobj = json.loads(msgstr, object_hook=object_hook)  # Decode JSON
    if (type(msgobj) not in [dict, types.SimpleNamespace]):
        raise ValueError('Message was not an object')
    return (connid, msgdat, msgobj)

def message(connid, obj, alreadyjson=False):
    if type(obj) is bytes:
        msgdat = obj
    else:
        if alreadyjson:
            msgstr = obj
        else:
            msgstr = json.dumps(obj)
        msgdat = msgstr.encode()  # Encode UTF-8
    head = struct.pack('<2I', len(msgdat), connid)
    return head + msgdat
