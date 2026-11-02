"""File limits of persistent data (F12 ``04-technical.md`` §13; SEC-F12-02, -13) and of
save files (F11 ``04-technical.md`` §13; SEC-F11-06).

Why this module exists: the read bounds are the security boundary for an untrusted file
(``05-security.md`` SEC-F12-01/02), so they live in one place that is easy to review and
patch in tests. The store's own caps (names, bytes, records, kinds) are runtime limits.

Read at call time (``limits.NAME``) so tests can patch them. Pure data; no side effects.
"""

from engine.core.imageheader import ENGINE_JPEG_MAX_BYTES as _ENGINE_JPEG_MAX_BYTES

# --- Reading the file (§7.4; SEC-F12-02) -----------------------------------------------------
FILE_MAX_BYTES = 33_554_432          # 32 MiB; more is W50 "over 32 MB"
NON_ASCII_MAX_BYTES = 8_388_608      # 8 MiB: the engine writes ASCII only
PRESCAN_MAX = 1_500_000              # counted { [ , : bytes before json.loads
VALUES_MAX_ITEMS = 1_000_000         # list/dict members over all values (freeze_untrusted)
INT_MAX_DIGITS = 4_300               # parse_int hook, whatever int_max_str_digits says

# --- Launch slicing and eviction (§7.4 step 5) -----------------------------------------------
READ_STEP_KEYS = 50_000              # seen keys / choice keys / lookups per ReadJob step
READ_STEP_NAMES = 1_000              # value names per ReadJob step
READ_GROUP_KEYS = 16                 # one label / menu (its checks, its run, or its drop at
                                     # eviction) counts as this many keys of a step
EVICT_TO = 0.9                       # records above this share of their cap are trimmed
BLOCK_KEYS = 1_024                   # keys per cached encoder block (§7.5)

# --- Writing and merging (§7.5–7.7) ----------------------------------------------------------
MERGE_SLICE_S = 0.002
ENCODE_SLICE_S = 0.0005              # encoder warm-up per frame (step 5)
WRITE_MIN_INTERVAL_S = 1.0
CLOSE_WAIT_S = 2.0
TEMP_STALE_S = 60
TEMP_SCAN_MAX = 1_000
TEMP_CLEANUP_MAX = 16
IO_TRIES = 3
MERGES_IN_A_ROW_MAX = 3

# --- Saves (F11 ``04-technical.md`` §13; SEC-F11-06) ---------------------------------------
# The read bounds of a ``.vnsave`` file. AC-F11-62 pins them: lowering one is always safe;
# raising one needs AC-F11-64 re-run on the reference machine first.
SAVE_FORMAT = 1                      # the meta line's ``vnsave``; > 1 reads as NEWER
SLOTS_PER_PAGE = 6
SAVE_PAGES_MAX = 100                 # numbered pages ``page1`` … ``page100`` (``[saves] pages``)
META_MAX = 8_192                     # line 1 and its "\n"
THUMB_MAX_BYTES = _ENGINE_JPEG_MAX_BYTES     # 96 KiB, the JPEG ``check_engine_jpeg`` accepts
THUMB_LINE_MAX = 131_084             # {"jpeg":"<base64 of 96 KiB>"} and its "\n"
STATE_MAX_BYTES = 25_165_824         # 24 MiB: line 3 and its "\n"
SAVE_FILE_MAX = 25_305_100           # META_MAX + THUMB_LINE_MAX + STATE_MAX_BYTES
HEAD_MAX = 139_276                   # META_MAX + THUMB_LINE_MAX: what a page reads
SAVE_PRESCAN_MAX = 1_000_000         # { [ , : bytes in line 3 before json.loads
SEQ_MAX = 2**53                      # write order; the next seq saturates here (SEC-F11-04a)
SAVED_AT_MAX = 253_402_300_799       # 9999-12-31 23:59:59 UTC
DESCRIPTION_MAX = 200                # description and chapter, code points
VERSION_MAX = 64                     # game_version, code points
INDEX_MAX_EXAMINED = 6_000           # entries one index scandir looks at (SEC-F11-13; F20 A13:
                                     # 612 slots + 4,000 node files + their temps fit)
INDEX_STEP_EXAMINED = 1_000          # entries one IndexJob step lists (F20 07 I-4: 4,612
                                     # entries take longer than SAVE_STEP_S in one go)
SAVE_TEMP_SCAN_MAX = 6_000           # entries the saves root's stale-temp scan looks at (F20 A13;
                                     # the shared TEMP_SCAN_MAX stays 1,000 for other folders)
SAVE_STEP_S = 0.004                  # encode / index work per frame
MAX_REQUESTS = 64                    # save requests waiting

# --- F20 node-state files (F20 ``04-technical.md`` §4, §7.5; SEC-F20-01, -05, -07) ----------
# ``node-<16 hex>.vnnode`` in the saves root. The read bounds are F11's (SAVE_FILE_MAX,
# META_MAX, STATE_MAX_BYTES, SAVE_PRESCAN_MAX); these are F20's own.
NODE_FORMAT = 1                      # the meta line's ``vnnode``; > 1 reads as NEWER
NODE_ID_MAX = 1_200                  # ``node`` in the meta line, code points
FLOW_DISK_MAX = 256 * 1_048_576      # bytes of node files F20 keeps (eviction above)
FLOW_FILES_MAX = 4_000               # node files F20 keeps
FLOW_SCAN_MAX = 20_000               # entries FlowListJob's one listing looks at
FLOW_LIST_STEP = 1_000               # entries one FlowListJob step looks at, at most
FLOW_FREE_FLOOR = 256 * 1_048_576    # free bytes a node write must leave (SEC-F20-06)
FLOW_STEP_S = 0.002                  # node encoding / removals per frame
FLOW_REMOVES_PER_FRAME = 64          # removals per frame (SEC-F20-05(b))
