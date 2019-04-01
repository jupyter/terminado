"""Message format implementation writing and reading data as MessagePack.
   See https://msgpack.org for MessagePack.
   It's like JSON. but fast and small.
"""

import msgpack
from interface import implements
from .format import MessageFormat

class MessagePackMessageFormat(implements(MessageFormat)):
    """Message format implementation writing and reading data as MessagePack.
       See https://msgpack.org for MessagePack.
       It's like JSON. but fast and small.
    """

    # forward map mapping terminado types to LightPayload types
    TYPES = {
        "stdin": 1,
        "stdout": 2,
        "set_size": 3,
        "setup": 4,
        "disconnect": 5,
        "switch_format": 6
    }

    # reverse map mapping LightPayload types to terminado types
    RTYPES = {str(value):key for key, value in TYPES.items()}

    @staticmethod
    def pack(command: str, message):
        """Pack the given command and message for writing to the socket."""
        # map the terminado type to the corresponding MessagePack type
        command = MessagePackMessageFormat.TYPES[command]

        pack = [command]

        if isinstance(message, list):
            pack = pack + message
        else:
            pack.append(message)

        # use an UTF-8 encoded string instead of bytes
        return msgpack.dumps(pack, use_bin_type=False)

    @staticmethod
    def unpack(data) -> list:
        """Unpack the data read from the socket."""
        pack = msgpack.loads(data, raw=False)

        # map the MessagePack type to the corresponding terminado type
        command = MessagePackMessageFormat.RTYPES[str(pack[0])]
        pack[0] = command

        return pack
