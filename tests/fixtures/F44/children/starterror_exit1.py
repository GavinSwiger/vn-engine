"""Fake preview child: a load error report (``phase "start"``, AC-F44-09 row 1's shape),
then exit 1 with no error screen. Stands in for CHILD on R with load errors until the real
child exists (step 6)."""

import _protocol

_protocol.error("start", head="The script has 2 problems:", items=[
    {"text": "script/chapter2.vns, line 11, column 16: this text has no closing quote.\n"
             "    sayori \"It's {b}nice{/b}.",
     "file": "script/chapter2.vns", "line": 11, "column": 16},
    {"text": "script/main.vns, line 7: there is no label called `club_poen`. "
             "Did you mean `club_poem`?",
     "file": "script/main.vns", "line": 7, "column": None},
])
raise SystemExit(1)
