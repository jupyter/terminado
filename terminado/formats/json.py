from interface import implements
from .format import MessageFormat
import json

class JSONMessageFormat(implements(MessageFormat)):
    """Message format implementation writing and reading data as JSON.
       See http://json.org for JSON.
    """
    
    @staticmethod
    def pack(type: str, message):
        pack = [type]
        
        if isinstance(message, list):
            pack = pack + message
        else:
            pack.append(message)
            
        return json.dumps(pack)
        
    @staticmethod
    def unpack(data) -> list:
        return json.loads(data)