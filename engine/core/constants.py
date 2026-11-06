"""Every numeric limit and fixed name used by the engine, in one place.

Why this module exists: limits are part of the author- and security-facing contract
(PR-F01-09, SEC-F01-04/05/07/21/23), so they must be easy to find, review, and test. It is
also the only file in ``engine/`` where the canvas literals 1280 and 720 may appear
(TR-F01-05, Q4): everything else refers to ``CANVAS_SIZE``.

Pure data; no imports from the engine, no side effects.
"""

import re
from types import MappingProxyType

# --- Canvas and window ------------------------------------------------------------------
CANVAS_SIZE = (1280, 720)            # canvas units (ADR-0001)
DEFAULT_WINDOW_SIZE = CANVAS_SIZE    # [window] width/height defaults
MIN_WINDOW_SIZE = (640, 360)

# --- Units (1 MB = 1 MiB everywhere, PR-F01-09) ------------------------------------------
KIB = 1024
MB = 1_048_576

# --- Logging -----------------------------------------------------------------------------
LOG_CAP_BYTES = 10 * MB
LOG_LIFECYCLE_RESERVE = 64 * KIB
LOG_KEEP_ARCHIVED = 4
LOG_KEEP_PID_LOGS = 4
LOG_TAIL_LINES = 50
EARLY_LOG_MAX_RECORDS = 1000
EARLY_LOG_MAX_BYTES = 256 * KIB

# --- File reads --------------------------------------------------------------------------
CONFIG_FILENAME = "config.toml"
CONFIG_MAX_BYTES = 1 * MB
ASSET_MAX_BYTES = 256 * MB

# --- Echo and message limits (SEC-F01-05, 07 (c), 09, 21) --------------------------------
ECHO_MAX_CHARS = 120
VALUE_ECHO_MAX_CHARS = 40
ERROR_MESSAGE_MAX_CHARS = 4000
CLIPBOARD_MAX_BYTES = 64 * KIB

# --- Asset references (PR-F01-55, SEC-F01-04, SEC-F01-08) --------------------------------
REF_MAX_CHARS = 1024
SEGMENT_MAX_CHARS = 255
LOCATE_MAX_LINE_CHARS = 4096

# --- Images (SEC-F01-06) -----------------------------------------------------------------
IMAGE_MAX_SIDE = 16_384
IMAGE_MAX_PIXELS = 64_000_000

# --- Asset file kinds (lower-case suffix of the last segment) ----------------------------
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
FONT_SUFFIXES = (".ttf", ".otf")

# --- Textbox (F05 §13, PR-F05-04, 07) ----------------------------------------------------
TEXTBOX_CPS_RANGE = (0, 1000)        # [textbox] cps; 0 shows text instantly
DEFAULT_TEXTBOX_CPS = 40
TEXT_SIZE_RANGE = (20, 48)           # [theme.textbox] text_size, name_tab.text_size
DEFAULT_TEXT_SIZE = 28
TEXTBOX_WIDTH_RANGE = (640, CANVAS_SIZE[0])   # [theme.textbox] width (F05 03-ui)

# --- Menus (F10 §13, 04 §8 item 3) -------------------------------------------------------
WORD_MAX_CHARS = 200                 # [words] <key>
MESSAGE_WORD_MAX_CHARS = 1000        # [words] confirm_main_menu, confirm_quit
MENU_ENTRIES_MAX = 16                # [title] entries, [quick_menu] entries
MENU_ENTRY_NAME_MAX_CHARS = 20       # one name in those lists, ^[a-z_]{1,20}$

# --- Asset cache bounds (SEC-F01-05) -----------------------------------------------------
PLACEHOLDER_CACHE_ENTRIES = 64
MISSING_REF_CACHE_ENTRIES = 4096
ASSET_PROBLEM_LOG_LIMIT = 1000
ENTRY_OVERHEAD = 256
FONT_OBJECT_COST = 256 * KIB

# --- Timing ------------------------------------------------------------------------------
MAX_FRAME_DT = 0.1
RESIZE_SETTLE_S = 0.2
BENCH_WARMUP_S = 5.0
LIMITER_SPIN_S = 0.0005              # the frame limiter spins for the last 0.5 ms (§7.9)
RECENT_FRAMES = 120                  # frames kept for the dev overlay (RecentFrames)

# --- ADR-0005 bench pass rule ------------------------------------------------------------
LONG_FRAME_FACTOR = 1.5              # a long frame's interval is > 1.5 frame periods
BENCH_WORK_P99_MAX_MS = 16.0
BENCH_LONG_FRAMES_MAX_PCT = 0.5

# --- Game folder layout (PR-F01-04) ------------------------------------------------------
GAME_SUBFOLDERS = ("script", "images", "audio", "fonts", "gui")
LOGS_DIRNAME = "logs"
RESERVED_DIRNAMES = ("characters",)
# Folders under the game root that later features write to (F11 saves, F12 persistent
# data, F16 settings). The script folder must never overlap them or logs/ (F02 SEC-F02-11,
# I-9; F16 Conflict 2).
SAVE_DIRNAMES = ("saves", "persistent", "settings")
# Every folder under the game root the engine writes to (F31 SEC-F31-03): one source for
# SEC-F02-11's overlap check (``loader.WRITE_ROOT_NAMES`` is this object) and for
# ``check_ref``'s write-root rule, so no asset ref names one.
WRITE_ROOT_DIRNAMES = (LOGS_DIRNAME, *SAVE_DIRNAMES, *RESERVED_DIRNAMES)

# --- Meta files (F31 04 §2.2, §6; SEC-F31-01, -04, -08) ----------------------------------
# The folder is ``RESERVED_DIRNAMES[0]`` itself (no second literal); originals live in
# ``files/``. Text caps are code points, byte caps bytes; the session caps are per launch.
META_DIRNAME = RESERVED_DIRNAMES[0]
META_ORIGINALS_DIR = "files"
META_NAMES_MAX = 32                  # distinct names in one game (E314)
META_TEXT_MAX_CHARS = 16_000         # a `file write` text (E311)
META_TEXT_MAX_BYTES = 64 * KIB
META_ORIGINAL_MAX_BYTES = 4 * MB     # a `files/<name>` original (E313, W198)
META_READ_MAX_BYTES = 16 * KIB       # a `file read` (W200 `large`)
META_READ_MAX_CHARS = 2_000          # a read note after cleaning
META_CHANGES_MAX = 256               # writes and deletes per session (W199)
META_IN_FLIGHT_MAX = 8               # writer jobs not yet finished (W198 `busy`)
META_W198_MAX = 20                   # W198 lines per session (then DEBUG)
META_SHOWN = f"<game>/{META_DIRNAME}/"   # the only path form a warning names

# --- Script words (F02 SR-F02-38; F04 §17 item 2) -----------------------------------------
# Defined here because config validation (core) checks [stage.positions] names against
# them; ``script/words.py`` re-exports the same objects.

# SR-F02-38, in the order of 02-script.md §3.7: the words fixed at F02, 37 since F34 freed
# ``cg`` (its gallery is ``lock gallery``, a row of F19's lock table; F34 07 I-1: loosen-only,
# so every older save still loads). Saved data never reads the live set (F14 07 I-1):
# ``StageState.from_json`` checks image words, tags and positions against these, so a word
# reserved later never makes an older save unreadable.
STATEMENT_WORDS_F02: frozenset[str] = frozenset((
    # F02 (available)
    "label", "jump", "call", "return", "if", "elif", "else", "define", "include",
    "default",                                                   # F03
    "scene", "show", "hide", "at", "behind", "as", "image",      # F04/F38
    "window", "pause",                                           # F05
    "menu",                                                      # F07
    "play", "stop", "queue", "voice",                            # F08
    "with", "shake", "flash",                                    # F09
    "nvl",                                                       # F17
    "chapter",                                                   # F18
    "ending", "lock", "unlock",                                  # F19/F21/F34–F37
    "points",                                                    # F22
    "minigame",                                                  # F23–F27
    "effect",                                                    # F28/F30
    "file",                                                      # F31
    "python",                                                    # never (E33)
))
# Every reserved statement word: F02's 37 and the words added since (F14 04 §18 A1:
# ``rollback``, the 39th; F20 04 §18 A1: ``flowchart``, the 40th). Restore drops a saved
# variable named after an added word, in any case (``runtime/state.reserved_since_save``).
STATEMENT_WORDS: frozenset[str] = STATEMENT_WORDS_F02 | frozenset((
    "rollback",                                                  # F14
    "flowchart",                                                 # F20
    "ui",                                                        # F32 (40 in all since F34)
))

# F04 stage words: not reserved (they only follow ``show``), but never part of an image
# name or a position name (F04 SR-F04-01, SR-F04-24).
STAGE_WORDS: frozenset[str] = frozenset(("layer", "zoom", "flip"))

# --- Stage (F04 §12, PR-F04-08, 13, 17) ---------------------------------------------------
STAGE_COORD_RANGE = (-1280, 2560)    # canvas units, x and y of `at` and [stage.positions]
LAYER_RANGE = (-100, 100)            # `layer` (E123)
ZOOM_RANGE = (0.25, 4.0)             # `zoom` (E124)
ART_HEIGHT_RANGE = (180, 4320)       # [stage] art_height
STAGE_POSITIONS_MAX = 1000           # entries in [stage.positions] (§7.8)
# left / center / right: bottom-center anchors at quarter widths on the bottom edge.
BUILTIN_POSITIONS: MappingProxyType[str, tuple[float, float]] = MappingProxyType({
    "left": (CANVAS_SIZE[0] / 4, float(CANVAS_SIZE[1])),
    "center": (CANVAS_SIZE[0] / 2, float(CANVAS_SIZE[1])),
    "right": (CANVAS_SIZE[0] * 3 / 4, float(CANVAS_SIZE[1])),
})

# --- Audio (F08 §13, 02 §3.6) ------------------------------------------------------------
AUDIO_VOLUME_RANGE = (0, 100)        # [audio] *_volume, percent
AUDIO_FADE_RANGE = (0, 60)           # seconds: [audio] *_fadein / *_fadeout
AUDIO_LOOP_START_RANGE = (0, 3600)   # seconds: [audio.loop_start] values
AUDIO_LOOP_STARTS_MAX = 1000         # entries in [audio.loop_start] (07 I-6)

# --- Transitions and effects (F09 §5, §12; SR-F09-03..07) --------------------------------
# Script ranges, in seconds; config validation and the script checks share them.
TRANSITION_SECONDS_RANGE = (0, 30)   # `with x <n>`, Dissolve/Fade/Mask, [effects] dissolve, fade
SHAKE_SECONDS_RANGE = (0.1, 10)      # `shake <n>`, [effects] shake
FLASH_SECONDS_RANGE = (0.1, 2)       # `flash <n>`, [effects] flash
PAUSE_SECONDS_RANGE = (0.1, 30)      # `pause <n>`
MASK_SOFT_RANGE = (0, 0.5)           # Mask(soft=…)
# Shake sizes in canvas units (PR-F09-11) and the shake directions.
SHAKE_SIZES: MappingProxyType[str, int] = MappingProxyType(
    {"small": 6, "medium": 12, "large": 24})
SHAKE_DIRECTIONS = ("horizontal", "vertical")
# The color words of `with fade`, `flash`, and Fade(color=…) (04 O1, 07 I-9: red = #FF0000).
COLOR_WORDS: MappingProxyType[str, str] = MappingProxyType(
    {"white": "#FFFFFF", "black": "#000000", "red": "#FF0000"})

# --- Glitch effects (F28 04 §2.2, §10; 07 I-10) -----------------------------------------
# The four F28 kinds in canonical order (`effect off` ends exactly these), the size words,
# and the length range of a burst, `with glitch`'s default, and [effects] glitch, in seconds.
GLITCH_KINDS = ("tear", "colorshift", "static", "jitter")
GLITCH_SIZES = ("small", "medium", "large")
GLITCH_SECONDS_RANGE = (0.1, 30)

# --- Start values (F44 §2, §6 item 3, PR-F44-19) ----------------------------------------
SET_MAX_COUNT = 100                  # `--set` values per run (or start-value lines in the editor)
SET_VALUE_MAX_CHARS = 10_000         # characters in one value, before stripping
SET_MAX_DEPTH = 100                  # nested lists and dictionaries in one value

# --- Fourth-wall tricks (F30 04 §2.2, §6.3; SEC-F30-06) ---------------------------------
WINDOW_TITLE_MAX = 100               # code points: `effect window_title`, GameState.window_title
CRASH_MESSAGE_MAX = 2_000            # code points: an `effect crash` message as written
USERNAME_MAX = 32                    # graphemes of the cleaned login name; also the
                                     # [meta] username_fallback limit (code points)
USERNAME_MAX_CODE_POINTS = 64        # code points after the grapheme cut (SEC-F30-06 (a))
USERNAME_RAW_MAX = 1_024             # code points of the raw name kept before cleaning
CRASH_GUARD_S = 0.5                  # drawn seconds before a fake crash (or "Allow") answers
CRASH_FADE_S = 0.3                   # the fake crash's fade under reduced effects

# --- Dynamic UI (F32 04 §2.2, §10; SR-F32-04, 07) ------------------------------------------
# A [style.<name>] name (lower case, also not ``off`` and not a reserved word; config.py),
# the table limits, the highest [playthrough.N], and a ``ui saving/loading off`` reason.
STYLE_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}", re.ASCII)      # fullmatch
STYLES_MAX = 32
PLAYTHROUGH_TABLES_MAX = 16
PLAYTHROUGH_MAX = 99
UI_REASON_MAX = 200                  # code points
