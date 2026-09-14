"""Terminal query sequences.

A query asks the terminal to send a reply, for example the cursor position
or the device attributes. It paints nothing, so it carries no value in output
that is replayed to a client, and replaying it makes the terminal answer a
second time into a pty where no program is waiting for the reply.
"""

# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.
from __future__ import annotations

import re

# String terminator of DCS and OSC sequences: ST, or BEL as xterm allows.
_ST = r"(?:\x07|\x1b\\)"

_QUERIES = [
    # DA1, DA2, DA3: primary, secondary and tertiary device attributes
    r"\x1b\[[>=]?0?c",
    # DECID: identify terminal
    r"\x1bZ",
    # DSR and DECXCPR: device status and cursor position reports
    r"\x1b\[\??[\d;]*n",
    # DECRQM: request ANSI or DEC private mode
    r"\x1b\[\??[\d;]*\$p",
    # DECRQPSR and DECRQTSR: request presentation and terminal state reports
    r"\x1b\[\d*\$[wu]",
    # DECRQCRA: request checksum of a rectangular area
    r"\x1b\[[\d;]*\*y",
    # XTVERSION: report terminal name and version
    r"\x1b\[>\d*q",
    # XTQMODKEYS: query key modifier options
    r"\x1b\[\?\d*m",
    # XTSMGRAPHICS: graphics attributes, the terminal replies to every action
    r"\x1b\[\?[\d;]*S",
    # XTWINOPS reports: window state, position, sizes, icon label and title
    r"\x1b\[(?:11|13|14|15|16|18|19|20|21)(?:;\d*)*t",
    # kitty keyboard protocol: query the current flags
    r"\x1b\[\?u",
    # DECRQSS: request status string
    r"\x1bP\$q[^\x07\x1b]*" + _ST,
    # XTGETTCAP: request termcap or terminfo capabilities
    r"\x1bP\+q[^\x07\x1b]*" + _ST,
    # OSC 4 and 5: query indexed and special colours, one "index;?" pair or more
    r"\x1b\][45](?:;\d+;\?)+" + _ST,
    # OSC 10 to 19: query the dynamic colours, one "?" or more
    r"\x1b\]1\d(?:;\?)+" + _ST,
    # OSC 52: read the clipboard
    r"\x1b\]52;[^;\x07\x1b]*;\?" + _ST,
]

QUERY_RE = re.compile("|".join(_QUERIES))


def strip_queries(text: str) -> str:
    """Remove the sequences that ask the terminal to send a reply."""
    return QUERY_RE.sub("", text)
