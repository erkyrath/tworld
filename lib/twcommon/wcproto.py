
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

import struct
import json

HEADER_LENGTH = 12  # three four-byte fields

class MsgType:
    say = b'SAY '

def check_buffer(buf):
    """
    Given a mutable bytearray, see if it begins with a complete message.
    If it does, parse it out and return (type, content). The type will be
    a bytes, the content will be a dict. The message chunk is then sliced
    out of the buffer.

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

    msgstr = msgdat.decode()  # Decode UTF-8
    msgobj = json.loads(msgstr)
    return (msgtype, msgobj)
