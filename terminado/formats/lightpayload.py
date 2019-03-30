from interface import implements
from .format import MessageFormat

class LightPayloadMessageFormat(implements(MessageFormat)):
    """Message format implementation writing and reading data as custom string-serialized format.
       LightPayload has a smaller message size than JSON or even MessagePack, because it is optimised for the data send
       and received by tornado rather than being a generic data format. Packing and unpacking uses string operations
       mostly, making it fast and small.
    """
    
    # forward map mapping terminado types to LightPayload types
    TYPES = {
        "stdin": "I",        # (I)nput
        "stdout": "O",       # (O)utput
        "set_size": "S",     # set (S)ize
        "setup": "C",        # (C)onnect
        "disconnect": "D",   # (D)isconnect
        "switch_format": "F" # switch (F)ormat
    }
    
    # reverse map mapping LightPayload types to terminado types
    RTYPES = {value:key for key,value in TYPES.items()}
    
    @staticmethod
    def pack(type: str, message):
        # map the terminado type to the corresponding LightPayload type
        type = LightPayloadMessageFormat.TYPES[type]
        
        pack = type + "|"
        
        if isinstance(message, list):
            pack += ",".join(message)
        else:
            pack += message or ""
            
        return pack
        
    @staticmethod
    def unpack(data) -> list:
        # map the LightPayload type to the corresponding terminado type
        type = LightPayloadMessageFormat.RTYPES[data[0]]
        
        message = data[2:]
        
        # the message is always a string, except for "set_size" for which it is a stringyfied list of (two) ints
        if type == "set_size":
            message = [int(x) for x in message.split(',')]
            message = [type] + message
        else:
            message = [type, message]
            
        return message