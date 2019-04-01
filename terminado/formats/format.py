"""Interface for classes wanting to implement a message format."""

from interface import Interface

class MessageFormat(Interface):
    """Interface for message formats."""

    @staticmethod
    def pack(command: str, message):
        """Pack the given command and message for writing to the socket."""
        pass

    @staticmethod
    def unpack(data) -> list:
        """Unpack the data read from the socket."""
        pass
