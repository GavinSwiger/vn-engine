"""The Studio assistant's tool layer (F48 ``04-technical.md`` §3, §3.1; ADR-0008 Amendment 5).

Why this package exists: an AI model helps an author by reading the game the way Studio
does and proposing verified edits. Both ways to reach it, the MCP server (``assist-mcp``)
and Studio's Assistant pane, share these pure modules, so the selector, output and edit
rules hold in one place.

- ``reference``: the primer and the generated language reference; the docs topics.
- ``refs``: the engine-built sets every model selector must be a member of (SEC-F48-01),
  argument checks, and the new-file rules (SEC-F48-02).
- ``textout``: the only output forms (SEC-F48-09): numbered-line blocks under a fixed header
  and one-line escaped strings, with every cap of 01 §7.2.
- ``workspace``: where tools read (disk for MCP, the pane's snapshot for Studio) and
  ``CheckService``, a second check runner polled off the Tk thread.
- ``edits``: ``propose_edit`` as a guarded ``scriptedit`` plan, checked as an overlay, and
  SEC-F48-04's code-bearing rule.
- ``tools``: ``TOOL_SPECS`` (engine text, the same for every game) and ``ToolBox``.
- ``diskapply``: the MCP server's only writes, ``apply_edit`` and ``undo_apply`` (SEC-F48-03).
- ``mcp``: ``serve``, the stdio MCP server (``assist-mcp``).

Imports ``engine.core``, ``engine.script``, the standard library, the pure editor modules
named in 04 §3 and ``tools.build.procs``. Never ``tkinter``, pygame, ``runtime``, ``app``,
``meta`` or ``tools.check``; only ``providers/`` imports ``socket``, ``ssl``, ``http`` or
``urllib``. Nothing outside ``engine/tools`` imports this package, except ``__main__``'s
function-level ``assist-mcp`` handler. Kept empty, so importing one module pulls in no other.
"""
