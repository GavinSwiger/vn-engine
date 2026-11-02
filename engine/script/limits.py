"""Every limit of the script loader (F02 ``04-technical.md`` §12.2).

Why this module exists (and is not part of ``engine/core/constants.py``): only ``script`` and
``app`` use these numbers, so they live with the package that enforces them. The limits are
part of the author- and security-facing contract (PR-F02-35, SEC-F02-02/03/04/05/09), so they
are kept in one place that is easy to review and test.

Pure data; no side effects.
"""

from engine.core.constants import MB

# --- Files, includes, blocks, lines (PR-F02-35) ------------------------------------------
SCRIPT_FILE_MAX_BYTES = 16 * MB
SCRIPT_MAX_FILES = 1000
SCRIPT_MAX_INCLUDE_DEPTH = 50
SCRIPT_MAX_BLOCK_DEPTH = 50
SCRIPT_MAX_LINE_CHARS = 10_000
SCRIPT_TOTAL_MAX_BYTES = 256 * MB            # Q-P1, E05b

# --- Errors, dialogue, files left out (PR-F02-32, SR-F02-36, PR-F02-05) -------------------
SCRIPT_MAX_ERRORS = 50
SCRIPT_MAX_ATTRIBUTES = 4
SCRIPT_UNINCLUDED_WARN_LIMIT = 20
SCRIPT_W04_LIMIT = 20                        # I-9: W04 records, then one summary line
SCRIPT_W42_LIMIT = 20                        # F05: W42 records, then one summary line (W42s)
SCRIPT_AUDIO_WARN_LIMIT = 20                 # F08: W20/W23 records, then one line (W20s)
SCRIPT_E09_NAMES = 5                         # E09 lists up to 5 other .vns files
SCRIPT_UNINCLUDED_SCAN_MAX_BYTES = 64 * MB   # §7.6.3 lazy scan for E43 "not included"

# --- Discovery walk (§7.1) ---------------------------------------------------------------
SCRIPT_WALK_MAX_ENTRIES = 10_000
SCRIPT_WALK_MAX_DEPTH = 32

# --- Report size (SR-F02-13, SEC-F02-04) -------------------------------------------------
SCRIPT_TODO_LOG_LIMIT = 150
SCRIPT_W03_LIMIT = 50
SCRIPT_REPORT_MAX_RECORDS = 400             # 378 + 21 W04 = 399 by construction (I-9)

# --- Python pieces (SEC-F02-02, §10) ------------------------------------------------------
SCRIPT_PY_PIECE_MAX_CHARS = 100_000          # E86b, counted as len(PyCode.source) (I-5)
SCRIPT_PY_MAX_LAMBDAS = 64                   # E86

# --- Whole-story totals (SEC-F02-03) ------------------------------------------------------
SCRIPT_MAX_STATEMENTS = 1_000_000            # E06b
SCRIPT_MAX_PY_PIECES = 250_000               # E06c
SCRIPT_MAX_PY_CHARS = 4_000_000              # E06d

# --- Messages and suggestions (SEC-F02-09, SEC-F02-05) ------------------------------------
SCRIPT_MESSAGE_MAX_CHARS = 1000
SCRIPT_MESSAGE_LIST_ITEMS = 3
SCRIPT_SOURCE_WINDOW = 120                   # §7.10.1: shown part of a source line
SCRIPT_SUGGEST_MAX_NAME = 100

# --- Loading inside the frame loop (§7.9) -------------------------------------------------
SCRIPT_LOAD_SLICE_S = 0.05
SCRIPT_YIELD_LINES = 512
IDENTITY_YIELD_ITEMS = 2_000                 # identity, index, and check loops yield this often

# --- F18 chapters (SPEC §3, §6; 07 I-2) ---------------------------------------------------
CHAPTERS_MAX = 1_000                         # E224
CHAPTER_NAME_MAX = 64                        # E222's name form; GameState.chapter's bound
CHAPTER_HEADING_MAX = 60                     # E222, code points as shown
CHAPTER_TITLE_MAX = 120                      # E222, code points as shown
CHAPTER_SECONDS_RANGE = (0, 30)              # E223; 0 shows no card

# --- F20 flowchart graph (04 §4, §7.1 steps 3 and 10; 05 SEC-F20-11, 12) -----------------------
# Read as ``limits.FLOW_*`` at run time, so tests can patch them small.
FLOW_NODES_MAX = 3_000                       # E265's node form: nodes other than gates
FLOW_EDGES_MAX = 10_000                      # E265's path form
FLOW_NAMES_MAX = 10_000                      # E265's name form; = runtime UNLOCK_NAMES_MAX (test)
FLOW_WORK_MAX = 20_000_000                   # E265's "too complex" form: graph work units
FLOW_STEP_UNITS = 2_000                      # FlowGraphJob.step's work units per step
FLOW_BUILD_MEM = 64 * MB                     # tested bound above the Program (TR-F20-08)
