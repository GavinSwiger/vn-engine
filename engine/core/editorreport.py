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
CHECK_EVENTS = ("problems", "names", "graph", "reach", "done")
CHECK_EVENT_MAX_ITEMS = 5_000           # items in one problems/names/graph line
CHECK_MAX_PROBLEMS = 1_000              # problem items sent per run; the rest are counted
CHECK_MAX_NAMES = 20_000                # names sent per kind
CHECK_MAX_LINKS = 50_000                # graph links sent
CHECK_KIND_RE = r"[a-z][a-z_]{0,31}"    # a name kind, or a problem's source word
CHECK_SEVERITIES = ("error", "warning", "info")
CHECK_LINK_KINDS = ("jump", "call", "menu")
# ``reach`` rows (``script/reach.py``): [scene, kind, text, file|null, line|null] per row.
CHECK_REACH_KINDS = ("way", "set", "blocked")
CHECK_MAX_REACH = 20_000                # reach rows sent
CHECK_CODE_MAX_CHARS = 16               # "E43", "W12b", "TODO", "" (config texts)
# The stdin overlay of unsaved text (``--stdin-overlay``; 04 §4.3, §7.3).
OVERLAY_HEADER_MAX = 64 * 1024          # the header line, newline not included
OVERLAY_MAX_FILES = 64
OVERLAY_MAX_BYTES = 64 * 1024 * 1024    # every overlaid file together
OVERLAY_READ_CHUNK = 1 << 20            # the body is read in chunks of this size
OVERLAY_MAX_NEW = 8                     # entries marked "new": true (F48 04 §7.3)
# Studio's side (04 §7.2).
CHECK_TIMEOUT_S = 30                    # a check child still running after this is stopped
CHECK_DEBOUNCE_MS = 1_500               # a check runs this long after the last change
CHECK_SLOW_S = 5                        # auto-checks pause while the last one took longer

# --- F47 Studio's helper child (F47 ``04`` §7.3) -------------------------------------------
# ``python -B -m engine helper GAME`` (``tools/helper.py``) is one long-lived child: Studio's
# ``HelperRunner`` (``tools/editor/helperrunner.py``) writes one request per stdin line,
# ``{"v": 1, "op", "serial", ...}`` (a ``still`` with ``"overlay": true`` is followed by
# ``checker.encode_overlay``'s bytes for ``config.toml``), and the child answers each in the
# framing above: ``ready`` once, then ``png``, ``played``, ``stopped`` or ``failed``.
HELPER_OPS = ("still", "thumb", "play", "stop")
HELPER_EVENTS = ("ready", "png", "played", "stopped", "failed")
HELPER_STILL_KINDS = ("textbox", "title")
HELPER_REQUEST_MAX = 4_096              # one request line, newline not included
HELPER_STILL_MAX_WIDTH = 640            # stills are 16:9, at most 640 px wide
HELPER_THUMB_MAX = 384                  # a thumbnail's longer side (96 px at up to 400 %)
HELPER_REPLY_TIMEOUT_S = 10             # no answer after this: Studio restarts the child

# --- F42 the build child (F42 ``04`` §2, §7.1, §7.3) ---------------------------------------
# ``python -E -B -m engine build GAME --out X [--zip] [--replace] --report-to-editor``
# (``tools/build/command.py``) relays its check grandchild's ``problems`` and ``done`` lines
# unchanged and writes these events in the framing above; Studio's ``BuildRunner``
# (``tools/editor/buildrunner.py``) reads them. Every name in them is relative to *Save to*
# or the game folder, never a full path.
#   build_step   {i, m, key, files, bytes, staging}   at each step's start
#   build_done   {folder, exe, files, bytes, zip, zip_bytes, warnings, left_out,
#                 left_out_total, long_paths, long_path_example, keys}
#                (F48 ``keys``: [[ref, line], …], at most 100 key-shaped places, never the
#                text; an older Studio ignores it, a missing one is none)
#   build_failed {code, values, details}
BUILD_EVENTS = ("build_step", "build_done", "build_failed")
BUILD_MAX_LEFT_OUT = 1_000              # [ref, reason] rows sent; the rest are counted
BUILD_MAX_KEYS = 100                    # F48: build_done.keys [ref, line] rows (keyscan)
BUILD_MAX_DETAILS = 200                 # build_failed detail lines (the packer's last 200)
BUILD_MAX_VALUES = 16                   # build_failed values (key → string or int)
BUILD_NAME_MAX_CHARS = 1_024            # a folder, zip, exe or staging name; a value

# --- F39 hot reload (F39 ``SPEC.md`` §5.2) -------------------------------------------------
# Studio asks a running preview for its place and hands it to a fresh preview child. Studio →
# the child's stdin (a pipe): one ASCII JSON line per message, ``{"v":1,"msg":"reload"}`` or
# ``{"v":1,"msg":"held","errors":N}``; a resumed child's first stdin line is
# ``{"v":1,"msg":"resume","bytes":B,"states":K,"lost":bool}`` (exactly those keys; ``K`` is 0
# exactly when ``B`` is 0), followed directly by exactly ``B`` bytes. The child answers
# ``reload`` with the report line ``{"v":1,"event":"state","bytes":B,"states":K,
# "window":[x,y]|null}`` (exactly those keys), followed directly by exactly ``B`` bytes: ``K``
# F11 state lines, newest first, each ending in ``\n``. Studio checks the header and relays
# the body unchanged; it never parses a state. The game side is ``app/hot_reload.py``, the
# Studio side ``tools/editor/preview.py`` and ``tools/editor/hotreload.py``.
RELOAD_MESSAGES = ("reload", "held", "resume")
STATE_EVENT = "state"
RELOAD_MESSAGE = b'{"v":1,"msg":"reload"}\n'
RELOAD_MESSAGE_MAX = 4_096              # one stdin line, newline not included
RELOAD_STATES_MAX = 20                  # the checkpoint and up to 19 rollback steps
RELOAD_FRAME_MAX = 32 * 1_048_576       # one state or resume body (32 MiB)
RELOAD_STATE_LINE_MAX = 25_165_824      # one state line and its "\n" (24 MiB, F11's cap)
RELOAD_WAIT_S = 5.0                     # how long either side waits for the other's body
RELOAD_WINDOW_MAX = 100_000             # |x|, |y| of a window position
RELOAD_HELD_MAX = 1_000_000_000         # a ``held`` count above this is a bad line

# --- F40 the developer console (F40 ``04`` §7.5, ``05`` SEC-F40-06/-07/-09) ----------------
# Studio → a running preview's stdin, on F39's channel and line rules (ASCII, at most
# ``RELOAD_MESSAGE_MAX`` bytes, ``v`` 1, exact keys, no duplicate keys):
#   ``{"v":1,"msg":"console","do":"open"|"values"}``
#   ``{"v":1,"msg":"console","do":"jump","label":L}``      (a ``str``, an exact label key)
#   ``{"v":1,"msg":"console","do":"set","name":N,"value":T}``  (``T`` goes only to F44's
#   ``parse_literal``: Studio sends values and scene names, never code)
# The game answers with one report line ``{"v":1,"event":"console","do":D,"ok":bool,
# "text":str}``; a ``values`` answer adds ``"story":bool,"values":[[name,text],…],
# "left_out":int``. Every string is redacted and escaped; the whole line fits
# ``REPORT_MAX_BYTES`` (trailing ``values`` are dropped and counted in ``left_out``).
# The game side is ``app/hot_reload.py`` (parse) and ``tools/console/answer.py``; Studio's is
# ``tools/editor/consoleclient.py`` and ``tools/editor/preview.py`` (decode).
CONSOLE_MESSAGE = "console"
CONSOLE_EVENT = "console"
CONSOLE_DO = ("open", "jump", "set", "values")
CONSOLE_NAME_MAX = 255                  # a ``set`` name (and a ``values`` name)
CONSOLE_LABEL_MAX = 1_024               # a ``jump`` label
CONSOLE_TEXT_MAX = 2_000                # an answer's ``text``
CONSOLE_VALUE_TEXT_MAX = 200            # one ``values`` value text
CONSOLE_VALUES_MAX = 1_000              # names in one ``values`` answer; the rest are counted
CONSOLE_SHOWN_MAX = 200                 # Studio shows at most this much of any event text
CONSOLE_ANSWER_S = 2.0                  # Studio: no answer after this is "didn't answer"

# --- Line reports: what the running game is doing (proposals 2.4 and 6.x foundation) -------
# A dev run with ``--report-to-editor`` (``app/editor_link.py``, ``EditorLink.update``) also
# writes, in the framing above:
#   ``{"v":1,"event":"ending","id":NAME,"title":TITLE}``  each time an ``ending`` line runs
#   ``{"v":1,"event":"at","file":REF,"line":N,"scene":LABEL}``  the line the story is on,
#       when it changes, at most ``AT_PER_S`` a second (the newest place wins)
# Exactly those keys; every string redacted and at most ``GAME_EVENT_TEXT_MAX`` characters.
# Studio's side is ``tools/editor/preview.py`` (decode, ``PreviewRunner.game_events``) and
# ``tools/editor/runwiring.py`` (``on_game_event``).
ENDING_EVENT = "ending"
AT_EVENT = "at"
GAME_EVENTS = (ENDING_EVENT, AT_EVENT)
AT_PER_S = 10
GAME_EVENT_TEXT_MAX = 1_024             # an ending's id or title, a file ref, a scene name
GAME_EVENTS_KEPT = 200                  # Studio keeps at most this many between two polls
