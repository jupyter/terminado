from .websocket import TermSocket
from .management import (TermManagerBase, SingleTermManager,
                         UniqueTermManager, NamedTermManager)

import logging
# Prevent a warning about no attached handlers in Python 2
logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = '0.5'
