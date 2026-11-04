"""The selectors a model may pass, and the one model string that becomes a path (F48
``04-technical.md`` §3.1; ``05-security.md`` SEC-F48-01, SEC-F48-02; 01 §6.6).

Why this module exists: a model's arguments are untrusted text. A selector (``file``,
``topic``, ``group``, ``label``, ``kind``, ``name``, ``id``, ``section``) is only ever an
**exact** member of a set the engine built from its own listings or registries: never
normalized, case-folded or stripped, never handed to ``Path``, ``open``, ``os.*``, ``glob``,
``fnmatch`` or ``re.compile``. So ``..``, ``C:\\``, ``script/CH2.vns``, an NFD form, a trailing
U+200B or a 10 KB string fail by not being a member, and no rule list can miss a form.

- ``RefTable``: the members. Script refs come from ``document.list_scripts`` (a contained
  link is listed, as Studio lists it; one leaving the game folder isn't), ``config.toml``
  when it is there, each ``ASSET_GROUPS`` group's listing (on first use), and the name kinds
  and names of the last check. Building it is the listing; a lookup makes no file-system
  call.
- ``select``: the exact lookup; a miss raises ``ToolError`` with 01 §6.6's text.
- ``check_keys``, ``int_arg``, ``flag_arg``, ``text_arg``: argument shapes. Integers are
  ``type(x) is int`` (no ``bool``) and clamped; flags are ``type(x) is bool``; unknown or
  missing keys are a tool error.
- ``new_ref_problem``: SEC-F48-02 for a new script ref in ``propose_edit``: ``files.new_script``'s
  (N) and (C) rules without writing, under ``script/``, ending ``.vns``, no Cc, Cf, Cs, Zl or
  Zp character, and a parent folder that already exists as a real folder.
- ``visible`` and ``one_line``: how a content string is shown (Cc, Cf, Cs, Zl and Zp as
  ``\\uNNNN``; ``one_line`` is ``echo()`` plus that, cut at 200).

Imports ``engine.core``, ``engine.script`` and the pure editor modules ``document`` and
``files`` (04 §3).
"""

import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Final

from engine.core.constants import REF_MAX_CHARS
from engine.core.errors import AssetMissing, AssetRefError
from engine.core.paths import GamePaths, RealDir, WalkResult, check_ref, is_plain_name
from engine.core.redact import escape_controls, redact, truncate
from engine.script.assetgroups import ASSET_GROUPS, CONFIG_REF
from engine.tools.editor import files
from engine.tools.editor.document import SCRIPT_DIR, SCRIPT_SUFFIX, list_scripts

SELECTOR_MAX_CHARS: Final = REF_MAX_CHARS        # 1,024 (SEC-F48-01)
ONE_LINE_MAX_CHARS: Final = 200                  # SEC-F48-09 (b)
SHOWN_MEMBERS: Final = 20                        # "{first 20 refs}" (01 §6.6)

# 01 §6.6.
BAD_SELECTOR: Final = "{value} isn't something the assistant can read. {noun}: {members}"
NOT_EDITABLE: Final = "The assistant can only change script files (.vns in script/)."
SCRIPT_FILES: Final = "Script files"
# Argument faults (01 §4.4: "Unknown tool, bad arguments → error text to the model").
NOT_AN_OBJECT: Final = "The arguments must be an object."
UNKNOWN_ARG: Final = "There is no argument {key}."
MISSING_ARG: Final = "The argument {key} is missing."
NOT_WHOLE: Final = "{key} must be a whole number."
NOT_FLAG: Final = "{key} must be true or false."
NOT_TEXT: Final = "{key} must be text of at most {limit:,} characters."
# SEC-F48-02: the hidden-character reason, in files.BAD_REF's form.
HIDDEN_CHARACTER: Final = "file names can't contain hidden or control characters"
NONE_LISTED: Final = "none"

_HIDDEN_CATEGORIES: Final = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))
_SCRIPT_GROUP: Final = files.group_by_key("script")


class ToolError(Exception):
    """A tool call refused before it did anything. ``text`` is the whole result the model
    gets (MCP sends it as an ``isError`` result)."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


# --- Showing strings ------------------------------------------------------------------------

def _escape_char(char: str) -> str:
    code = ord(char)
    return f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}"


def visible(text: str) -> str:
    """``text`` with every Cc, Cf, Cs, Zl and Zp character as ``\\uNNNN`` (``\\UNNNNNNNN``
    above U+FFFF): tabs, line breaks, U+200B, the bidi controls, U+FEFF and lone surrogates
    included. Other characters, the backslash included, are kept."""
    if text.isprintable():               # fast path: none of the five categories is printable
        return text
    return "".join(_escape_char(c) if unicodedata.category(c) in _HIDDEN_CATEGORIES else c
                   for c in text)


# SEC-F48-02's name rule (no Cc, Cf, Cs, Zl or Zp character) is S1's ``core.paths`` function,
# shared with the check child's ``read_overlay``; ``is_plain`` is its name here.
is_plain = is_plain_name


def one_line(text: str, limit: int = ONE_LINE_MAX_CHARS) -> str:
    """A content string as one line (SEC-F48-09 (b)): redacted, controls and bidi escaped
    (``echo()``'s escapes), every other hidden character made ``visible``, then cut to
    ``limit`` characters."""
    return truncate(visible(escape_controls(redact(text))), limit)


def shown_value(value: object) -> str:
    """A model-supplied value as an error text names it: a string as ``one_line``; JSON's
    other types as a word, never their contents."""
    if type(value) is str:
        return one_line(value) if value else '""'
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int and -10 ** 18 < value < 10 ** 18:
        return str(value)                  # never str() of a huge int (int_max_str_digits)
    if type(value) in (int, float):
        return "a number"
    if type(value) is list:
        return "a list"
    if type(value) is dict:
        return "an object"
    return "that value"


def _members_text(members: Sequence[str]) -> str:
    if not members:
        return NONE_LISTED
    first = [one_line(m) for m in members[:SHOWN_MEMBERS]]
    sep = "; " if any("," in m for m in first) else ", "   # docs topics hold commas
    extra = len(members) - SHOWN_MEMBERS
    return sep.join(first) + (f"{sep}…and {extra:,} more" if extra > 0 else "")


# --- Selectors (SEC-F48-01) -----------------------------------------------------------------

def is_member(value: object, members: Collection[str]) -> bool:
    """``value`` is a ``str`` of at most 1,024 characters **equal** to a member."""
    return type(value) is str and len(value) <= SELECTOR_MAX_CHARS and value in members


def select(value: object, members: Collection[str], *, listing: Sequence[str] | None = None,
           noun: str = SCRIPT_FILES) -> str:
    """``value`` when it is an exact member of ``members`` (SEC-F48-01). Otherwise
    ``ToolError`` with 01 §6.6's text: "{value} isn't something the assistant can read.
    {noun}: {the first 20 of listing}". ``listing`` defaults to ``members`` (sorted when it
    isn't a sequence). No file-system call."""
    if is_member(value, members):
        return value                     # type: ignore[return-value]
    if listing is None:
        listing = members if isinstance(members, Sequence) else sorted(members)
    raise ToolError(BAD_SELECTOR.format(value=shown_value(value), noun=noun,
                                        members=_members_text(listing)))


def _names_of(entries: Iterable[object]) -> tuple[str, ...]:
    """The names of a check's ``NameEntry`` rows (or plain strings), first seen first."""
    seen: dict[str, None] = {}
    for entry in entries:
        name = entry if type(entry) is str else getattr(entry, "name", None)
        if type(name) is str:
            seen.setdefault(name, None)
    return tuple(seen)


class RefTable:
    """Every member a selector may name, built from the engine's own listings.

    - ``scripts``: the ``.vns`` refs in ``list_scripts`` order (``script/main.vns`` first).
    - ``config``: ``config.toml`` is in the game folder (readable, never editable).
    - ``names``: name kind → names, in the check's order (``label`` gives the scenes).
    - Group listings (``group_listing``) are walked on first use and kept.

    Lookups (``file``, ``script``, ``group``, ``kind``, ``name``, ``label``) never touch the
    file system; each returns the member or raises ``ToolError``.
    """

    def __init__(self, scripts: Sequence[str], *, config: bool = False,
                 names: Mapping[str, Iterable[object]] | None = None,
                 paths: GamePaths | None = None) -> None:
        self.scripts: tuple[str, ...] = tuple(scripts)
        self.config: bool = config
        self.names: dict[str, tuple[str, ...]] = {
            kind: _names_of(entries) for kind, entries in (names or {}).items()
            if type(kind) is str}
        self.paths = paths
        self._scripts = frozenset(self.scripts)
        self._files = self._scripts | ({CONFIG_REF} if config else frozenset())
        self._name_sets = {kind: frozenset(found) for kind, found in self.names.items()}
        self._groups: dict[str, WalkResult] = {}

    @classmethod
    def build(cls, paths: GamePaths, *,
              names: Mapping[str, Iterable[object]] | None = None) -> "RefTable":
        """The table for the game at ``paths``: ``list_scripts``, whether ``config.toml``
        resolves, and ``names`` (a ``CheckResult.names``) when a check has run."""
        try:
            paths.resolve(CONFIG_REF)
            config = True
        except (AssetMissing, AssetRefError):
            config = False
        return cls(list_scripts(paths), config=config, names=names, paths=paths)

    # -- members ---------------------------------------------------------------------------

    @property
    def files(self) -> tuple[str, ...]:
        """The readable refs: the scripts, then ``config.toml``."""
        return self.scripts + ((CONFIG_REF,) if self.config else ())

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(self.names)

    @property
    def group_keys(self) -> tuple[str, ...]:
        return tuple(group.key for group in ASSET_GROUPS)

    def is_script(self, value: object) -> bool:
        return is_member(value, self._scripts)

    # -- lookups -----------------------------------------------------------------------------

    def file(self, value: object) -> str:
        """A readable ref: a listed script or ``config.toml``."""
        return select(value, self._files, listing=self.scripts)

    def script(self, value: object) -> str:
        """A listed script ref an edit may change. ``config.toml`` is "not editable";
        anything else gets the bad-selector text."""
        if is_member(value, self._scripts):
            return value                 # type: ignore[return-value]
        if value == CONFIG_REF:
            raise ToolError(NOT_EDITABLE)
        return select(value, self._scripts, listing=self.scripts)

    def group(self, value: object) -> str:
        """An ``ASSET_GROUPS`` key (``script``, ``images``, …)."""
        keys = self.group_keys
        return select(value, frozenset(keys), listing=keys, noun="Groups")

    def kind(self, value: object) -> str:
        """A name kind the last check reported."""
        return select(value, self._name_sets, listing=self.kinds, noun="Kinds")

    def name(self, kind: object, value: object) -> str:
        """A name of ``kind`` (itself selected first)."""
        found = self.kind(kind)
        return select(value, self._name_sets[found], listing=self.names[found],
                      noun=f"Names of kind {found}")

    def label(self, value: object) -> str:
        """A scene (a ``label`` name)."""
        return select(value, self._name_sets.get("label", frozenset()),
                      listing=self.names.get("label", ()), noun="Scenes")

    # -- group listings ----------------------------------------------------------------------

    def group_listing(self, key: str) -> WalkResult:
        """The refs of group ``key`` (an exact ``group_keys`` member), code-point sorted,
        walked once with Studio's tree caps; the script group is ``scripts``."""
        if key == _SCRIPT_GROUP.key:
            return WalkResult(self.scripts, False)
        cached = self._groups.get(key)
        if cached is not None:
            return cached
        group = files.group_by_key(key)
        found = WalkResult((), False)
        if self.paths is not None:
            try:
                walk = self.paths.walk_files(group.folder, suffix="",
                                             max_entries=files.TREE_MAX_ENTRIES,
                                             max_depth=files.TREE_MAX_DEPTH)
            except AssetRefError:
                walk = WalkResult((), False)
            refs = tuple(ref for ref in walk.refs
                         if files.takes(group, ref.rsplit("/", 1)[-1]))
            found = WalkResult(refs, walk.truncated)
        self._groups[key] = found
        return found


# --- Arguments (SEC-F48-01) -----------------------------------------------------------------

def check_keys(args: object, required: Collection[str] = (),
               optional: Collection[str] = ()) -> dict:
    """``args`` when it is a JSON object with every ``required`` key and no key outside
    ``required`` and ``optional``; else ``ToolError``."""
    if type(args) is not dict:
        raise ToolError(NOT_AN_OBJECT)
    for key in args:
        if key not in required and key not in optional:
            raise ToolError(UNKNOWN_ARG.format(key=shown_value(key)))
    for key in required:
        if key not in args:
            raise ToolError(MISSING_ARG.format(key=key))
    return args


def int_arg(args: Mapping[str, object], key: str, *, default: int, low: int,
            high: int) -> int:
    """``args[key]`` clamped to ``low..high``, or ``default`` when absent. Only
    ``type(x) is int`` counts (``true``, ``1.0``, ``"3"`` and ``null`` are refused)."""
    if key not in args:
        return default
    value = args[key]
    if type(value) is not int:
        raise ToolError(NOT_WHOLE.format(key=key))
    return max(low, min(high, value))


def flag_arg(args: Mapping[str, object], key: str, *, default: bool) -> bool:
    """``args[key]`` when it is ``true`` or ``false``, or ``default`` when absent."""
    if key not in args:
        return default
    value = args[key]
    if type(value) is not bool:
        raise ToolError(NOT_FLAG.format(key=key))
    return value


def text_arg(args: Mapping[str, object], key: str, *, limit: int,
             default: str | None = None) -> str:
    """``args[key]`` when it is a ``str`` of at most ``limit`` characters; ``default`` when
    absent and a default is given. Never a selector: the caller treats it as literal text."""
    if key not in args and default is not None:
        return default
    value = args.get(key)
    if type(value) is not str or len(value) > limit:
        raise ToolError(NOT_TEXT.format(key=key, limit=limit))
    return value


# --- New script refs (SEC-F48-02) -----------------------------------------------------------

def new_ref_problem(paths: GamePaths, ref: object, listed: Collection[str] = ()) -> str | None:
    """None when ``ref`` may become a new script file; else the one line why not.

    The rules, in order (each before any file-system call that depends on it):
    a ``str`` of at most 1,024 characters under ``script/`` (else "not editable"); no Cc,
    Cf, Cs, Zl or Zp character; ``check_ref`` (``..``, ``:``, ``\\``, a trailing dot or
    space, ``con``, …); a ``.vns`` name (``files.takes``); not ``listed``; then, after
    ``invalidate_listings``, its parent is an existing real folder (``real_dir``: no link,
    junction or file anywhere on the way, so no folder is made) holding no entry equal to the
    name up to case (links and FIFOs included). ``apply`` and the check child repeat these
    rules before acting."""
    if type(ref) is not str or len(ref) > SELECTOR_MAX_CHARS:
        return BAD_SELECTOR.format(value=shown_value(ref), noun=SCRIPT_FILES,
                                   members=_members_text(sorted(listed)))
    if not ref.startswith(SCRIPT_DIR + "/"):
        return NOT_EDITABLE
    folder_ref, _, name = ref.rpartition("/")
    if not is_plain_name(ref):
        return files.BAD_REF.format(name=visible(name), reason=HIDDEN_CHARACTER)
    try:
        check_ref(ref)
    except AssetRefError as exc:
        return files.BAD_REF.format(name=one_line(name), reason=exc.reason)
    if not ref.endswith(SCRIPT_SUFFIX) or not files.takes(_SCRIPT_GROUP, name):
        return NOT_EDITABLE
    shown = one_line(ref)
    if ref in listed:
        return files.EXISTS.format(ref=shown)
    paths.invalidate_listings()
    try:
        found = paths.real_dir(folder_ref)
    except AssetRefError:
        return files.NOT_A_FOLDER.format(folder=one_line(folder_ref))
    if not isinstance(found, RealDir):
        if found.kind == "missing" and found.other_case is None:
            return files.FOLDER_MISSING.format(folder=one_line(folder_ref))
        return files.NOT_A_FOLDER.format(folder=one_line(folder_ref))
    listing = paths.list_real(found.ref)
    if listing is None:
        return files.NOT_A_FOLDER.format(folder=one_line(folder_ref))
    key = name.casefold()
    if any(entry.casefold() == key
           for entry in (*listing.files, *listing.dirs, *listing.omitted)):
        return files.EXISTS.format(ref=shown)
    return None


__all__ = ["BAD_SELECTOR", "HIDDEN_CHARACTER", "MISSING_ARG", "NOT_AN_OBJECT", "NOT_EDITABLE",
           "NOT_FLAG", "NOT_TEXT", "NOT_WHOLE", "ONE_LINE_MAX_CHARS", "RefTable",
           "SCRIPT_FILES", "SELECTOR_MAX_CHARS", "SHOWN_MEMBERS", "ToolError", "UNKNOWN_ARG",
           "check_keys", "flag_arg", "int_arg", "is_member", "is_plain", "new_ref_problem",
           "one_line", "select", "shown_value", "text_arg", "visible"]
