"""Terminals served to xterm.js using Tornado websockets"""

# Copyright (c) Jupyter Development Team
# Copyright (c) 2014, Ramalingam Saravanan <sarava@sarava.net>
# Distributed under the terms of the Simplified BSD License.

import logging

from .management import (
    NamedTermManager,
    SingleTermManager,
    TermManagerBase,
    UniqueTermManager,
)
from .websocket import TermSocket

# Prevent a warning about no attached handlers in Python 2
logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = "0.13.3"
