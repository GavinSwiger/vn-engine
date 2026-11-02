"""Every limit of the story runtime (F03 ``04-technical.md`` §12.2, §9.1).

Why this module exists (and is not part of ``engine/core/constants.py``): only ``runtime``
and ``app`` use these numbers, so they live with the package that enforces them. The state
limits are F11's trust boundary (§9.1), so they are kept in one place that is easy to review.

Pure data and one pure check (``saved_tag_ok``); no side effects.
"""

from engine.core.constants import STATEMENT_WORDS_F02
from engine.script.words import is_image_word

# --- Running the story (§7.2, §7.3) -------------------------------------------------------
STEP_LIMIT = 100_000                 # E45 (lines are exempt)
CALL_DEPTH_MAX = 1_000               # E45b; also the cap on a state's call_stack
LABEL_RING = 1_000                   # SR-F03-26

# --- Saveable values (§7.4, TR-F03-12) ----------------------------------------------------
STATE_MAX_DEPTH = 100                # list/dict nesting; also ends cycles
INT_LIMIT = 10**4300                 # refuse abs(v) >= INT_LIMIT (4,301+ digits)

# --- Untrusted states only (§9.1) ---------------------------------------------------------
STATE_MAX_NAMES = 100_000            # story variables in one state
STATE_MAX_ITEMS = 2_000_000          # list and dict members over all variables
STATE_NAME_MAX_CHARS = 255           # one variable name
POSITION_MAX_CHARS = 1_024           # a sid, and a hint's label
HINT_MAX_PATH = 128                  # a hint's path length

# --- Launch phase (§7.6) ------------------------------------------------------------------
LAUNCH_MAX_ERRORS = 50               # PR-F03-14
SPEAKER_CHECK_CHUNK = 2_000          # launch slicing

# --- F04 launch phases 4 and 5 (F04 04-technical.md §7.1, §7.2, §12) ----------------------
IMAGE_SCAN_MAX_FILES = 20_000        # listed entries (files and folders) the scan looks at
IMAGE_SCAN_MAX_DEPTH = 8             # a folder at most this many levels below images/ is listed
STAGE_CHECK_CHUNK = 2_000            # statements per step of each stage_check pass
STAGE_WARN_MAX = 100                 # launch stage warning records logged, then one summary
STAGE_W10_MAX_LINES = 20             # file lines in the one W10 record, then "…and N more."

# --- A saved stage's sprites (F04 04 §9.1; untrusted data). Here, not in runtime/stage.py,
# so runtime/glitch.py can check saved jitter tags without importing stage (F28 07 I-12).
STAGE_MAX_SPRITES = 256              # sprites in a saved stage
STAGE_WORD_MAX_CHARS = 100           # one word of a saved image name, a tag, a position name


def saved_tag_ok(value: object) -> bool:
    """A saved sprite tag (F04 §9.1; F28 §6.3): a ``str`` of at most ``STAGE_WORD_MAX_CHARS``
    characters that is an image word, with F02's 38 statement words reserved (F14 07 I-1)."""
    return (type(value) is str and len(value) <= STAGE_WORD_MAX_CHARS
            and is_image_word(value, STATEMENT_WORDS_F02))

# --- F08 story audio (F08 04-technical.md §6.3, §12; untrusted states: §6.3 from_json) ----
MUSIC_SEQUENCE_MAX = 64              # music entries in AudioState (queue drops from the front)
SOUND_LOOPS_MAX = 16                 # looping effects in AudioState; a 17th is refused
ONESHOTS_PER_BURST = 16              # one-shot PlaySound per burst; extras dropped (DEBUG)
AUDIO_BURST_MAX = 64                 # executor-held audio commands per burst, then one sync
AUDIO_FILE_MAX_CHARS = 1_024         # a saved audio file (as written, relative to audio/)

# --- F12 persistent data (F12 04-technical.md §13; read through runtime/persistent.py) ----
PERSIST_MAX_BYTES = 1_048_576        # the values object as compact JSON (E183)
PERSIST_MAX_NAMES = 10_000           # stored author names (E183)
PERSIST_NAME_MAX_CHARS = 255         # one author name
SEEN_MAX = 1_000_000                 # seen lines over all labels (W57)
CHOSEN_MAX = 100_000                 # choice marks over all menus (W57)
UNLOCK_KINDS_MAX = 32                # registered unlock kinds
UNLOCK_NAMES_MAX = 10_000            # names per unlock kind

# --- F20 flowchart records (F20 04-technical.md §4, §7.2; read as ``limits.FLOW_*``) --------
FLOW_PATH_MAX = 1_000                # node keys in GameState.flow.path (newest kept)
FLOW_MEMORY_STATES = 256             # node states the recorder holds (oldest dropped)
FLOW_PENDING_MAX = 16                # arrivals waiting for the next checkpoint (extras dropped)
FLOW_STATE_PATH_CHECK = 16           # a node file's state holds its key in the last 16 (s5)

# --- App driver and watchdog (§7.3, §7.7) -------------------------------------------------
RUN_SLICE_S = 0.004
RUN_CHUNK_STEPS = 64
AUTHOR_CODE_LIMIT_S = 5.0            # PR-F03-33
