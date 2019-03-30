import interface
from interface import Interface

class MessageFormat(Interface):
    """Interface for message formats."""
    
    @staticmethod
    def pack(type: str, message):
        """Pack the given type and message for writing to the socket."""
        pass
        
    @staticmethod
    def unpack(data) -> list:
        """Unpack the data read from the socket."""
        pass