"""Fake check child: AC-F45-09's bad lines, a plain line, then a valid run."""

import _protocol

M = _protocol.MARKER
_protocol.raw(M + b"{not json\n")
_protocol.raw(M + b'{"v":2,"event":"done","loaded":true,"problems":0,"seconds":0}\n')
_protocol.raw(M + b'{"v":1,"event":"bogus"}\n')
_protocol.raw(M + b'{"v":1,"event":"names","kind":"../x","items":[["a",null,null]]}\n')
_protocol.raw(M + b'{"v":1,"event":"problems","items":[{"severity":"fatal","code":"",'
              b'"source":"load","text":"bad","file":null,"line":null,"column":null}]}\n')
_protocol.raw(M + "日".encode("utf-8") + b"\n")
_protocol.raw(b"an author's print\n")
_protocol.standard_run()
