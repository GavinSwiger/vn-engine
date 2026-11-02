"""The editor report protocol: the marker and limits both sides share (F44 ``04`` §3 "Report
line", §6 item 3; ``07`` I-4).

Why this module exists: a game run with ``--report-to-editor`` (``app/editor_link.py``)
writes one ASCII stdout line per event, ``VN-EDITOR-REPORT `` + JSON, and the editor's
preview runner (``tools/editor/preview.py``) reads them. The writer must stay inside the
limits the reader checks, or a real report would be dropped as malformed. ``app`` and
``tools`` may not import each other, so the one definition lives in ``core``. Constants only:
no imports, no side effects.
"""

REPORT_MARKER = b"VN-EDITOR-REPORT "
REPORT_VERSION = 1
REPORT_MAX_BYTES = 1 << 20              # one report line, marker included, newline not (1 MiB)
REPORT_MAX_ITEMS = 60
REPORT_MAX_TAIL = 60
REPORT_TEXT_MAX_CHARS = 10_000
PHASES = ("start", "run")               # before / after the "started" event

# --- F45 Studio's check child (F45 ``04`` §4.3) --------------------------------------------
# ``python -m engine check GAME --report-to-editor`` (``tools/check.py``) writes the events
# ``problems``, ``names``, ``graph`` and then ``done`` in the framing above, and Studio's
# ``CheckRunner`` (``tools/editor/checker.py``) reads them; both keep to these limits. Each
# event is split into lines of at most ``REPORT_MAX_BYTES`` and ``CHECK_EVENT_MAX_ITEMS``
# items (``REPORT_MAX_ITEMS`` stays F44's ``error`` limit).
CHECK_EVENTS = ("problems", "names", "graph", "done")
CHECK_EVENT_MAX_ITEMS = 5_000           # items in one problems/names/graph line
CHECK_MAX_PROBLEMS = 1_000              # problem items sent per run; the rest are counted
CHECK_MAX_NAMES = 20_000                # names sent per kind
CHECK_MAX_LINKS = 50_000                # graph links sent
CHECK_KIND_RE = r"[a-z][a-z_]{0,31}"    # a name kind, or a problem's source word
CHECK_SEVERITIES = ("error", "warning", "info")
CHECK_LINK_KINDS = ("jump", "call", "menu")
CHECK_CODE_MAX_CHARS = 16               # "E43", "W12b", "TODO", "" (config texts)
# The stdin overlay of unsaved text (``--stdin-overlay``; 04 §4.3, §7.3).
OVERLAY_HEADER_MAX = 64 * 1024          # the header line, newline not included
OVERLAY_MAX_FILES = 64
OVERLAY_MAX_BYTES = 64 * 1024 * 1024    # every overlaid file together
OVERLAY_READ_CHUNK = 1 << 20            # the body is read in chunks of this size
# Studio's side (04 §7.2).
CHECK_TIMEOUT_S = 30                    # a check child still running after this is stopped
CHECK_DEBOUNCE_MS = 1_500               # a check runs this long after the last change
CHECK_SLOW_S = 5                        # auto-checks pause while the last one took longer
