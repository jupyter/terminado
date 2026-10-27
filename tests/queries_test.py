# Copyright (c) Jupyter Development Team
# Distributed under the terms of the Simplified BSD License.

import pytest

from terminado.queries import strip_queries

ST = "\x1b\\"

# Sequences that ask the terminal for a reply.
QUERIES = [
    "\x1b[c",  # DA1
    "\x1b[0c",
    "\x1b[>c",  # DA2
    "\x1b[>0c",
    "\x1b[=c",  # DA3
    "\x1bZ",  # DECID
    "\x1b[5n",  # DSR: status
    "\x1b[6n",  # DSR: cursor position
    "\x1b[?6n",  # DECXCPR
    "\x1b[?996n",  # DSR: colour scheme
    "\x1b[?63;1n",  # DSR: checksum
    "\x1b[4$p",  # DECRQM
    "\x1b[?12$p",
    "\x1b[?2026$p",
    "\x1b[1$w",  # DECRQPSR
    "\x1b[1$u",  # DECRQTSR
    "\x1b[1;1;1;1;24;80*y",  # DECRQCRA
    "\x1b[>q",  # XTVERSION
    "\x1b[>0q",
    "\x1b[?4m",  # XTQMODKEYS
    "\x1b[?1;1S",  # XTSMGRAPHICS
    "\x1b[?2;1;0S",
    "\x1b[11t",  # XTWINOPS reports
    "\x1b[13t",
    "\x1b[13;2t",
    "\x1b[14t",
    "\x1b[14;2t",
    "\x1b[16t",
    "\x1b[18t",
    "\x1b[19t",
    "\x1b[20t",
    "\x1b[21t",
    "\x1b[?u",  # kitty keyboard flags
    "\x1bP$qm" + ST,  # DECRQSS
    '\x1bP$q"p\x07',
    "\x1bP+q544e" + ST,  # XTGETTCAP
    "\x1b]4;1;?" + ST,  # OSC 4: indexed colour
    "\x1b]4;1;?;2;?\x07",
    "\x1b]5;0;?" + ST,  # OSC 5: special colour
    "\x1b]10;?" + ST,  # OSC 10 to 19: dynamic colours
    "\x1b]11;?\x07",
    "\x1b]12;?" + ST,
    "\x1b]10;?;?" + ST,
    "\x1b]17;?" + ST,
    "\x1b]19;?" + ST,
    "\x1b]52;c;?" + ST,  # OSC 52: clipboard read
    "\x1b]52;;?\x07",
]

# Sequences that paint, set state, or are replies, and must survive the filter.
KEPT = [
    "\x1b[31m",  # SGR
    "\x1b[0m",
    "\x1b[38;2;10;20;30m",
    "\x1b[2J",  # erase and cursor movement
    "\x1b[K",
    "\x1b[H",
    "\x1b[3;1H",
    "\x1b[2A",
    "\x1b[1C",
    "\x1b[?25l",  # DEC private modes
    "\x1b[?1049h",
    "\x1b[?2004h",
    "\x1b[?1000h",
    "\x1b[?2026h",
    "\x1b[?2026l",
    "\x1b[4h",  # ANSI mode
    "\x1b[>1u",  # kitty keyboard push, pop and set
    "\x1b[<u",
    "\x1b[=1;1u",
    "\x1b[u",  # SCORC
    "\x1b[8;24;80t",  # XTWINOPS commands
    "\x1b[22;0t",
    "\x1b[23;0t",
    "\x1b[1t",
    "\x1b[2t",
    "\x1b[24t",  # DECSLPP
    "\x1b[2 q",  # DECSCUSR
    "\x1b[!p",  # DECSTR
    "\x1b[>4;2m",  # XTMODKEYS
    "\x1b[3S",  # SU
    "\x1b]0;title\x07",  # OSC: title, cwd, hyperlink, shell integration, clipboard write
    "\x1b]7;file:///tmp" + ST,
    "\x1b]8;;https://example.com" + ST,
    "\x1b]133;A\x07",
    "\x1b]52;c;aGVsbG8=\x07",
    "\x1b]4;1;rgb:ff/00/00" + ST,  # colour set
    "\x1b]10;#ffffff\x07",
    "\x1b]11;rgb:0000/0000/0000" + ST,
    "\x1bP0;1q#0;2;0;0;0#0~~@@vv@@~~@@~~$#1!14@" + ST,  # sixel
    "\x1bP1$r0;1;1m" + ST,  # DECRQSS reply
    "\x1bP1+r544e=1b5b32337e" + ST,  # XTGETTCAP reply
    "\x1b[24;1R",  # CPR reply
    "\x1b[?1;2c",  # DA1 reply
    "\x1b[>0;276;0c",  # DA2 reply
    "\x1b[?12;2$y",  # DECRPM reply
    "\x1b[?0u",  # kitty keyboard flags reply
    "\x1b(B",  # charset, keypad modes, save and restore cursor, reverse index, RIS
    "\x1b=",
    "\x1b>",
    "\x1b7",
    "\x1b8",
    "\x1bM",
    "\x1bc",
    "plain text with a bracket [6n and a dollar $p",
]


@pytest.mark.parametrize("query", QUERIES)
def test_query_is_stripped(query):
    assert strip_queries(query) == ""
    assert strip_queries("before" + query + "after") == "beforeafter"


@pytest.mark.parametrize("sequence", KEPT)
def test_other_sequence_is_kept(sequence):
    assert strip_queries(sequence) == sequence


def test_query_split_across_reads_is_stripped_from_joined_text():
    reads = ["prompt \x1b[", "6n\x1b]11", ";?\x1b\\ $ "]
    assert strip_queries("".join(reads)) == "prompt  $ "
