"""Message format implementation writing and reading data as JSON.
   See http://json.org for JSON.
"""

import json
from interface import implements
from .format import MessageFormat

class JSONMessageFormat(implements(MessageFormat)):
    """Message format implementation writing and reading data as JSON.
       See http://json.org for JSON.
    """

    @staticmethod
    def pack(command: str, message):
        """Pack the given command and message for writing to the socket."""
        pack = [command]

        if isinstance(message, list):
            pack = pack + message
        else:
            pack.append(message)

        return json.dumps(pack)

    @staticmethod
    def unpack(data) -> list:
        """Unpack the data read from the socket."""
        return json.loads(data)
