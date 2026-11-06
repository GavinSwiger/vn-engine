"""One message template per code, transcribed from ``02-script.md`` §5 (the only source of
the texts). Prefixes (``<file>, line <N>[, column <C>]: ``) are added by
``UserFacingError.format()``; whole-file messages start with the file ref themselves.

Every argument that comes from file content, an include path, or a listing goes through
``show()`` (``echo()`` plus visible escapes for invisible characters, SR-F02-76), and every
finished message is cut to ``SCRIPT_MESSAGE_MAX_CHARS`` (SEC-F02-09).

Step 1 of the F02 checklist built the codes raised by the decoder, reader, block parser,
statements, and Python checks; step 9 added the loader, whole-game check, and reporting
codes (E07, E08–E09, E25, E26, E43, E47, E48, E70, E91–E94, E97, W02, W04 and their summary
lines), the SR-F02-74 look-alike suffix, the report lines (TODO, success), and
``source_window`` (the redacted 120-character window of a source line, §7.10.1). Step 7
added F44 C2's start-option codes E26b and E26c (drafted; Q-N1).

F03 (one catalogue, F03 ``04-technical.md`` §3.2) adds its load codes for ``default``:
E46b, E47b, E47c, and the ``default`` forms of E48, E48b, and E49 (the statement word is
their last argument, ``"define"`` when absent). F03 step 7 adds the run codes of the E85
family (E85, E85b–E85g, E85i, E85j, E85m, E85n), which ``engine/runtime/errors.py`` fills in; step 8
adds the launch codes (E75–E75g, E85k, E85l, E89, E89b, E89c), E75h, and E85c's Character
form. Step 10 adds E45 and E45b (the step and call limits, ``interpreter.py``). Step 11 adds
the ``$`` binding codes E87, E88, and W05 (``bindings.py``, which also raises E62 and E63).

F05 (step 2) adds every F05 text here, the launch and run ones included so that later steps
only format them: E160–E167 (``texttags.py``), W42 and its summary W42s (``checks.py``),
E168–E171, W40–W46 (runtime and app, F05 steps 3, 6, 7).

F04 adds its load codes (E110–E133, step 2), E135 and the run texts (steps 4, 5), and its
launch warnings W10–W16 with W10b and W10s (step 6), which ``engine/runtime/stage_check.py``
fills in.

F08 (step 1) adds its load codes: E140–E151 (``audio.py``), W20, W23, W24, and the W20s
summary line (``audio_checks.py``).

F07 (step 1) adds every F07 text (its ``01-design.md`` §5.3, ``04-technical.md`` §5.4): the
``menu`` and ``choice`` forms of E12, E172–E177 (``menu.py``, E175 ``texttags.py``), E178
(``runtime/menu.py``), W47 and W48 (launch checks, F07 step 4), and the headless runner's
``choose N`` texts (``runtime/headless.py``; not game errors). They are drafts until the
narrative designer approves the ``cases.toml`` rows (F07 07 I-4, I-5).

F09 (step 1) adds its texts (its ``01-design.md`` §5.6, ``07`` I-8, I-9): the load codes
E192–E198 (``effects.py``, ``checks.py``), the constructor code E199 and the launch codes
E190, E191, E194's launch form, and W60 (``runtime/transitions.py``), the headless
runner's wait-loop text, and the presentation's W61 and W62 (moved here from
``runtime/transitions.py``, which formats them for ``render``). W14 is retired (C5). Forms ``01`` leaves open are drafts for the
narrative designer (I-9).

F12 (step 3a) adds its story texts (its ``01-design.md`` §5.4): E180–E183 (run, through
``engine/runtime/errors.py``), E184 (load, ``default.py``/``checks.py``), E185 and W56
(launch). F03's E85h is retired. The file warnings W50–W57 are ``engine/persist/texts.py``'s.

F18 (step 1) adds its load codes (its SPEC §3, 07 I-2): E220 and E224 (``checks.py``),
E221–E223 (``chapter.py``). W110 and W111 come with its card and app steps.

F22 (step 1) adds every F22 text (its SPEC §3, 07 I-2, I-10): load E230 and E232
(``points.py``), E231 and E235 (``checks.py``), E233 and E234 (``bindings.py``); the run code E236
(``engine/runtime/points.py``) and W120 (dev), which step 2 raises.

F14 (step 1) adds its load codes (its ``04-technical.md`` §6.2): E200–E203 (``rollback.py``)
and E204 (``rollback.py``'s ``attach_fixed``). All are drafts for the narrative designer
(06 G3).

F17 (step 1) adds every F17 text (its ``01-design.md`` §5.4; ``06`` D3, G2; ``07`` §3.3, I-11):
load E210, E211 (``nvl.py``), the run code W102 (``engine/runtime/nvl.py``, dev), and the
launch codes W100 and W101 with its W101s summary, which F17 step 5 raises
(``app/text_check.py``). They are drafts until the narrative designer approves the
``cases.toml`` rows.

F19 (step 1) adds every F19 text (its ``01-design.md`` §5.5, ``06`` D2, G1): load E240, E242,
and E243/E244's line forms (``routes.py``), E241, E243/E244's name forms, E245, E246, and W130
(``checks.py``; E245's uses ``bindings.py``); W131 (launch) and W132 (run, dev), which step 3
raises, and E245's run form (``runtime/errors.py``, step 2).

F23 (s1) adds its script texts (its ``02-script.md`` §4.1; ``04`` §5.2–§5.4; F24 ``07`` I-2):
load E270 (``minigame.py``, ``checks.py``; its ``$`` form ``pycheck.py``) and E271
(``minigame.py``, ``checks.py``), E81's argument subject, and the run code E272 with both
plugin forms, which F23 s2 raises (``runtime/minigame.py``). E204 names a minigame line too
(F14 A3). All are drafts for the narrative designer (F23 ``06`` G2). F23 s2 adds the run
codes E275 (its line forms) and E276 (``runtime/minigame.py``), the headless E279 and
``finish`` forms (``runtime/headless.py``), and the shared headless catch-all's ``finish``.

F20 (s1) adds its parse and load texts (its ``02-script.md`` §5; ``04`` §6.1, §6.2): E260 and
E263 (``flowchart.py``'s parser), E261 (its ``top`` form at parse, its ``first`` form at
load), E262 and E264 (``flowchart.py``'s ``iter_attach_marks``, in the whole-game checks).
E204 names a flowchart line through its statement-word form. All are drafts for the
narrative designer (F20 ``06`` §0.1). F20 s2 adds the graph's texts (``04`` §7.1 step 10):
E265 (whole game; its node, path, name-count, and "too complex" forms) and the dev load
warnings W150–W153 (``flowgraph.py``); E265's last two forms are drafts for the narrative
designer (``06`` G7).

F28 (s2) adds every F28 text (its ``01-design.md`` §5.3; ``04`` §5.1, §12; ``07`` I-14): load
E294 (``glitch.py``), and W182, W183 (presentation) and W184 (dev, run), which F28 s3–s5 log
through ``runtime/glitch.py``. Forms ``01`` leaves open are drafts for the narrative designer.

F30 (s2) adds every F30 text (its ``01-design.md`` §5.4; ``04`` §6.8, §11): load E300
(``fourthwall.py``), E301 (``fourthwall.py``, ``texttags.py``), E302 (``chapter.py``; its
``name`` form at launch, ``runtime/character.py``), the ``username`` forms of E163, E164,
E175, and E252, and the ``{username}`` tag in E160's list; W188 (run, ``app``), W189 and W190
(dev launch, ``app/text_check.py``) with their summary lines W189s and W190s, which F30 s5
logs. Forms ``01`` leaves open are drafts for the narrative designer.

F32 (s2) adds every F32 text (its ``01-design.md`` §5.2; ``04`` §5.1, §12; ``07`` G5): load
E319, E320, and E321 (``ui.py``); W204, W206, and W207 (``app/looks.py``, F32 s4) and W205
(the restore, F32 s3). Forms ``01`` leaves open are drafts for the narrative designer.

F31 (s2) adds every F31 text (its ``01-design.md`` §5.2; ``04`` §5.1, §5.2, §11): load E309–E312
and E315 (``metafiles.py``), E312's target forms, E313, and E314 (``checks.py``); W196–W198
(``app/metafiles.py``, F31 s4) and W199, W200 (``runtime/metafiles.py``, F31 s3); and the
headless ``player deletes|restores <name>`` words in H-input (F31 ``07`` I-5). Forms ``01``
leaves open are drafts for the narrative designer.

F41 (L1) adds its six lint texts W237–W242 (its ``01-design.md`` §4.1, final): never the
load's; ``tools/lint.py`` findings that the check child sends as names rows and the ``lint``
CLI prints.

F43 (W0) adds its ten translation texts W247–W256 (its ``01-design.md`` §5.4, final, with
W248's "this kind of entry isn't supported" from ``04``): never the script load's; raised by
reading and checking ``translations/*.po``, the language setting, and ``check``/build.

Places (``Place``) are ``(file ref, line)`` pairs. Lists inside one message show at most
``SCRIPT_MESSAGE_LIST_ITEMS`` items, then "and N more" (SEC-F02-09).
"""

import math
import re
import unicodedata
from collections.abc import Callable, Sequence

from engine.core.constants import (CANVAS_SIZE, CRASH_MESSAGE_MAX, GLITCH_KINDS,
                                   GLITCH_SECONDS_RANGE, LAYER_RANGE, STAGE_COORD_RANGE,
                                   KIB, MB, META_CHANGES_MAX, META_NAMES_MAX,
                                   META_ORIGINAL_MAX_BYTES,
                                   META_ORIGINALS_DIR, META_READ_MAX_BYTES, META_SHOWN,
                                   META_TEXT_MAX_CHARS, UI_REASON_MAX, VALUE_ECHO_MAX_CHARS,
                                   WINDOW_TITLE_MAX, ZOOM_RANGE)
from engine.core.redact import echo, escape_controls, redact, truncate
from engine.script.limits import (
    SCRIPT_E09_NAMES,
    SCRIPT_MESSAGE_LIST_ITEMS,
    SCRIPT_MESSAGE_MAX_CHARS,
    SCRIPT_SOURCE_WINDOW,
)

Place = tuple[str, int]

# SEC-F02-07: characters that make a name look like another (§7.3.4).
INVISIBLE_CHARS = ("͏ᅟᅠ឴឵᠋-᠏ㅤ︀-️ﾠ"
                   "\U000e0100-\U000e01ef")
_INVISIBLE_RE = re.compile(f"[{INVISIBLE_CHARS}]")


def codepoint(char: str) -> str:
    """``U+202E`` style (at least 4 hex digits, upper case)."""
    return f"U+{ord(char):04X}"


def _escape_one(match: re.Match[str]) -> str:
    cp = ord(match.group())
    return f"\\u{cp:04x}" if cp <= 0xFFFF else f"\\U{cp:08x}"


def show(text: str) -> str:
    """Script text as it may appear in a message: invisible characters escaped, then
    ``echo()`` (redact, escape controls and bidi, cut to 120 characters)."""
    return echo(_INVISIBLE_RE.sub(_escape_one, text))


def _finish(text: str) -> str:
    """QA's "append ``.``" rule for Python's texts (06 §0.4)."""
    return text if text.endswith((".", "?", "!", "…")) else text + "."


_UTF8_FIX = ("Save it as UTF-8 in your editor (in Notepad: File > Save as > Encoding: UTF-8) "
             "and launch again.")

# SR-F02-24: the pair named for each opening character where text should start.
_QUOTE_PAIRS = {
    "“": "“ ”", "”": "“ ”", "„": "„ “", "‟": "‟ ”",
    "″": "″ ″", "＂": "＂ ＂", "«": "« »", "»": "« »", "「": "「 」", "『": "『 』",
}
_CURLY_OPENERS = frozenset("“”„‟")
E50_CHARS = frozenset(_QUOTE_PAIRS)
E51_CHARS = frozenset("'‘’")

_SPACE_NAMES = {" ": "a non-breaking space", "　": "a full-width space"}

_MODIFIER_EXAMPLES = {"at": "show hana at left", "as": "show hana as hana2",
                      "with": "scene bg river with fade",                 # F09
                      "behind": "show hana behind daichi"}

_PY_PREFIX = {"E80": "this Python", "E81": "this condition", "E82": "this value"}


def _e50(char: str) -> str:
    pair = _QUOTE_PAIRS.get(char, f"{char} {char}")
    if char in _CURLY_OPENERS:
        return (f"this line uses curly quotes {pair} around the text. Put the text between "
                'straight quotes "like this". Curly quotes inside the text are fine.')
    return (f"this line uses quote marks {pair} around the text. Put the text between "
            f'straight quotes "like this". Quote marks such as {pair} inside are fine.')


def _e52(sequence: str) -> str:
    text = (f'"{show(sequence)}" is not a special sequence. Write \\\\ for a backslash, '
            '\\" for a quote, or \\n for a new line.')
    if sequence == "\\{":
        text += " To show a {, write {{."
    return text


def _e10(kind: str) -> str:
    if kind == "\t":
        return ("this line is indented with a tab, but earlier lines in this file use "
                "spaces. Use one or the other in each file.")
    return ("this line is indented with spaces, but earlier lines in this file use tabs. "
            "Use one or the other in each file.")


def _e12(word: str, comments_only: bool) -> str:
    note = " (comment lines don't count)" if comments_only else ""
    if word == "label":
        return f"this label has no lines under it{note}. Indent the scene, or write return for now."
    if word == "menu":                                      # F07 (01 §5.3)
        return f"this menu has no lines under it{note}. Indent its question and choices under it."
    if word == "choice":                                    # F07 (01 §5.3)
        return (f"this choice has no lines under it{note}. Indent what happens when it's "
                "picked; to just go on, write $ pass.")
    if word in ("success", "failure"):                      # F59
        return (f"{word}: has no lines under it{note}. Indent what happens on a {word}; to "
                "just go on, write $ pass.")
    return f"this {word} has no lines under it{note}. Indent the lines that belong to it."


def _join_or(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def _e14(widths: tuple[int, ...], kind: str) -> str:
    unit = "tabs" if kind == "\t" else "spaces"
    listed = _join_or([str(w) for w in widths])
    return (f"this line's indentation doesn't line up with any block above it. "
            f"Indent it by {listed} {unit}.")


def _e21(name: str, fullwidth: bool) -> str:
    text = f"label {show(name)} needs : at the end of the line. Write label {show(name)}:"
    if fullwidth:
        text += " Use the ordinary colon :, not ：."
    return text


def _e31b(keyword: str, condition: str) -> str:
    written = f"{keyword} {show(condition)}" if condition else keyword
    return f"{keyword} needs : at the end of the line. Write {written}:"


def _e42(keyword: str, rest: str) -> str:
    if rest == ":":
        return f"{keyword} doesn't start a block. Remove the :."
    return (f"{keyword} takes one label name, but this line has more after it. "
            f'Remove "{show(rest)}", or join the words with _.')


# E49's example per statement word (F02 SR-F02-66; F03 SR-F03-01).
_E49_EXAMPLES = {"define": 'define hana = Character("Hana")', "default": "default trust = 0"}


def _e49(dotted: str | None, word: str = "define") -> str:
    if dotted:
        return (f'{word} sets one plain name, and "{show(dotted)}" has a dot. '
                "Use a name without dots.")
    return f"{word} needs a name, =, and a value, e.g. {_E49_EXAMPLES[word]}."


def _e64(name: str) -> str:
    example = re.sub(r"\W", "_", name)
    text = (f'"{show(name)}" can\'t be a name. Names use letters, digits, and _, '
            "and can't start with a digit")
    if example != name and example.isidentifier():
        return text + f", e.g. {show(example)}."
    return text + "."


def _and_list(items: Sequence[str]) -> str:
    """``a``; ``a, and b``; ``a, b, and c`` (places contain commas, so the serial comma is
    always used, as in ``02`` §5's E43 example)."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _place(place: Place, here: str | None = None) -> str:
    """``script/a.vns, line 30``, or ``line 30`` when the place is in ``here`` (E70's tail)."""
    ref, line = place
    return f"line {line}" if ref == here else f"{show(ref)}, line {line}"


def _more(count: int, one: str, many: str) -> str:
    return f"{count:,} more {one if count == 1 else many}"


def _places(places: Sequence[Place], more: int = 0, here: str | None = None) -> str:
    """At most ``SCRIPT_MESSAGE_LIST_ITEMS`` places, then ``and N more places``."""
    shown = [_place(p, here) for p in places[:SCRIPT_MESSAGE_LIST_ITEMS]]
    extra = len(places) - len(shown) + more
    if extra > 0:
        shown.append(_more(extra, "place", "places"))
    return _and_list(shown)


def _also(places: Sequence[Place], more: int, here: str | None) -> str:
    """E43/E70's "other uses" sentence (empty without other uses)."""
    if not places and more <= 0:
        return ""
    return f" It is also used at {_places(places, more, here)}."


def _script_of(char: str) -> str | None:
    """"Latin", "Greek", "Cyrillic", or None for a letter of another script or a non-letter."""
    if not char.isalpha():
        return None
    if char.isascii():
        return "Latin"
    name = unicodedata.name(char, "")
    for script in ("LATIN", "GREEK", "CYRILLIC"):
        if name.startswith(script):
            return script.capitalize()
    return None


def mixed_script(name: str) -> str | None:
    """SEC-F02-08 (b): "Cyrillic" or "Greek" when ``name`` mixes Latin letters with letters of
    that script (the first such script found), else None. ``привет`` and ``日本`` give
    None."""
    scripts = {_script_of(c) for c in name}
    if "Latin" not in scripts:
        return None
    for char in name:
        script = _script_of(char)
        if script in ("Greek", "Cyrillic"):
            return script
    return None


def show_name(name: str) -> str:
    """A name as it appears in a message: like ``show()``, but in a name that mixes Latin
    with Greek or Cyrillic letters those letters are escaped (``h\\u0430na``, AC-F02-47), so
    a look-alike can be seen. Names in one script are shown as written."""
    if mixed_script(name) is not None:
        name = "".join(f"\\u{ord(c):04x}" if _script_of(c) in ("Greek", "Cyrillic") else c
                       for c in name)
    return show(name)


def _describe(char: str) -> str:
    if char.isascii() and char.isprintable():
        return char
    name = unicodedata.name(char, "")
    return f"{codepoint(char)} {name}" if name else codepoint(char)


def lookalike_suffix(suggestion: str, written: str) -> str:
    """SR-F02-74: when ``suggestion`` differs from ``written`` only in non-ASCII characters,
    `` "st\\u0430rt" has U+0430 CYRILLIC SMALL LETTER A where "start" has a.``; else ``""``."""
    if len(suggestion) != len(written) or suggestion == written:
        return ""
    diffs = [(a, b) for a, b in zip(suggestion, written) if a != b]
    if any(a.isascii() and b.isascii() for a, b in diffs):
        return ""
    diffs = diffs[:SCRIPT_MESSAGE_LIST_ITEMS]
    has = " and ".join(_describe(a) for a, _ in diffs)
    where = " and ".join(_describe(b) for _, b in diffs)
    return f' "{show_name(suggestion)}" has {has} where "{show_name(written)}" has {where}.'


def _did_you_mean(suggestion: str, written: str) -> str:
    return f'Did you mean "{show_name(suggestion)}"?' + lookalike_suffix(suggestion, written)


def _e07(ref: str) -> str:
    base = ref.rstrip("/").rsplit("/", 1)[-1]
    return (f"The includes from script/main.vns to {show(ref)} chain more than 50 files, which "
            f"is the limit. Include {show(base)} from a file nearer main.vns.")


def _e09(names: Sequence[str], total: int | None = None) -> str:
    total = len(names) if total is None else total
    shown = [show(n) for n in names[:SCRIPT_E09_NAMES]]
    extra = total - len(shown)
    if extra > 0:
        shown.append(f"{extra:,} more")
    listed = " and ".join(shown) if len(shown) == 2 else _and_list(shown)
    return (f"script/main.vns doesn't exist, but script/ has other .vns files: {listed}. "
            "Rename the file where your story begins to main.vns.")


def _e25(name: str, others: Sequence[Place], more: int = 0) -> str:
    if len(others) + more <= 1:
        return (f'there is already a label named "{show_name(name)}" in {_places(others)}. '
                "Rename one of them.")
    return (f'there are other labels named "{show_name(name)}" in {_places(others, more)}. '
            "Rename all but one.")


def _e26(suggestion: str | None = None, place: Place | None = None) -> str:
    text = 'The story has no label named "start".'
    if suggestion is None:
        return text + " Add label start: to script/main.vns. The story begins there."
    where = f" ({_place(place)})" if place is not None else ""
    return (text + f' Did you mean "{show_name(suggestion)}"{where}?'
            + lookalike_suffix(suggestion, "start"))


# F44 C2 (Q-N1): E26b/E26c come from the command line (--start, --set), so they have no
# file or line. Drafted by the F02 step 7 builder from PR-F44-17–19 in F02's quoting style;
# the narrative designer owns the final wording.
def _e26b(name: str, suggestion: str | None = None, defined_in: str | None = None) -> str:
    text = f'There is no label named "{show_name(name)}" to start at (--start).'
    if suggestion is not None:
        return text + " " + _did_you_mean(suggestion, name)
    if defined_in is not None:
        path = defined_in.removeprefix("script/")
        return (text + f" It is defined in {show(defined_in)}, which is not included. "
                f'Add include "{show(path)}".')
    return text + " Check the spelling, or add that label."


def _e26c(name: str, is_define: bool, suggestion: str | None = None) -> str:
    if is_define:
        return (f'"{show_name(name)}" is a define, which can\'t be changed, so --set can\'t '
                "give it a start value. Use default for values the story changes.")
    text = f'"{show_name(name)}" has no default, so --set can\'t give it a start value.'
    if suggestion is not None:
        return text + " " + _did_you_mean(suggestion, name)
    return text + " Only names set with default can be given one."


def _e43(name: str, suggestion: str | None = None, defined_in: str | None = None,
         here: str | None = None, others: Sequence[Place] = (), more: int = 0) -> str:
    also = _also(others, more, here)
    if suggestion is not None:
        return (f'there is no label named "{show_name(name)}".{also} '
                + _did_you_mean(suggestion, name))
    if defined_in is not None:
        path = defined_in.removeprefix("script/")
        return (f'there is no label named "{show_name(name)}" in the game.{also} It is defined in '
                f'{show(defined_in)}, which is not included. Add include "{show(path)}".')
    return (f'there is no label named "{show_name(name)}".{also} '
            "Check the spelling, or add that label.")


def _e47(name: str, others: Sequence[Place], more: int = 0) -> str:
    if len(others) + more <= 1:
        return f'"{show_name(name)}" is already defined in {_places(others)}. Remove or rename one.'
    return (f'"{show_name(name)}" is also defined in {_places(others, more)}. '
            "Remove or rename all but one.")


def _e48(names: Sequence[str], places: Sequence[Place], more: int = 0,
         word: str = "define") -> str:
    """``names`` is the cycle from the reported define (not repeated at the end); ``places``
    are where the other members are defined. ``word`` is ``define`` or (F03) ``default``."""
    shown = [show_name(n) for n in names]
    if len(shown) == 2:
        a, b = shown
        return (f"{word} {a} uses {b}, and {b} uses {a} ({_places(places, more)}), so neither "
                "can be set first. Change one so it doesn't use the other.")
    links = [f"{shown[i]} uses {shown[(i + 1) % len(shown)]}"
             for i in range(min(len(shown), SCRIPT_MESSAGE_LIST_ITEMS))]
    if len(shown) > SCRIPT_MESSAGE_LIST_ITEMS:
        links.append(f"{len(shown) - SCRIPT_MESSAGE_LIST_ITEMS:,} more")
    return (f"{word} {_and_list(links)} ({_places(places, more)}), so none of them can be set "
            "first. Change one so it doesn't use the others.")


def _e46b(shown: str | None = None) -> str:
    """F03 E46b: ``shown`` is the line's own ``name = value`` (``misplaced_args``)."""
    example = show(shown) if shown else "name = value"
    return ("default sets a variable's starting value before the story begins, so it must be "
            f"at the top level. To change the value during the story, use $ {example}.")


def _e47b(name: str, first: Place) -> str:
    """F03 E47b, at the second ``default`` of ``name``; ``first`` is the first one."""
    return f'"{show_name(name)}" already has a default in {_place(first)}. Remove one of them.'


def _e47c(name: str, first: Place, define_first: bool) -> str:
    """F03 E47c, at whichever of the define and the default comes second; ``first`` is the
    other one."""
    if define_first:
        both = f'"{show_name(name)}" is set by define in {_place(first)}, and by default here.'
    else:
        both = f'"{show_name(name)}" has a default in {_place(first)}, and is set by define here.'
    return (both + " Use define for values that never change and default for values the story "
            "changes, and remove the other.")


def _e87(name: str, place: Place, value: str | None = None, character: bool = False) -> str:
    """F03 E87 (SR-F03-09): a ``$`` line or condition sets the define ``name``, defined at
    ``place``. ``value`` is the define's value as written, None when it is over 40
    characters (shown ``…``); ``character`` picks the Character form."""
    shown = show_name(name)
    text = f'"{shown}" is set by define in {_place(place)}, so the story can\'t change it.'
    if character:
        return (text + " To change the name the player sees, use "
                f'Character(name_from="{shown}_name") and set {shown}_name.')
    example = show(value) if value is not None else "…"
    return text + f" If the story changes it, write default {shown} = {example} instead of define."


def _e88(define: str = "math", module: str = "math", then: str | None = None) -> str:
    """F03 E88 (SR-F03-25): the ``define … = module(…)`` form of the import
    (``bindings.e88_args``); ``then`` adds `` Then write a.b.`` (G10, drafted for the forms
    ``02`` §5.1 doesn't list)."""
    text = ("a $ line can't import a module, because the module would become part of the saved "
            f'game. Add define {show_name(define)} = module("{show(module)}") at the top level '
            "instead.")
    return text + (f" Then write {show(then)}." if then is not None else "")


def _w05(name: str | None = None) -> str:
    """F03 W05 (SR-F03-21): ``name`` is the list when the call's argument is a plain name.
    G10 (drafted): the first sentence of the other form says ``the list``."""
    if name is None:
        return ("dice.shuffle gives back a shuffled copy and leaves the list unchanged. Store "
                "the result, e.g. $ deck = dice.shuffle(…).")
    shown = show_name(name)
    return (f"dice.shuffle gives back a shuffled copy and leaves {shown} unchanged. "
            f"Write $ {shown} = dice.shuffle({shown}).")


def _e70(name: str, suggestion: str | None = None, here: str | None = None,
         others: Sequence[Place] = (), more: int = 0) -> str:
    also = _also(others, more, here)
    if suggestion is not None:
        return f'no character named "{show_name(name)}".{also} ' + _did_you_mean(suggestion, name)
    return f'no character named "{show_name(name)}".{also} Check the spelling, or define it.'


def _e91(written: str, ref: str, suggestion: str | None = None) -> str:
    text = f'can\'t include "{show(written)}" because {show(ref)} doesn\'t exist.'
    if suggestion is not None:
        return text + f' Did you mean "{show(suggestion)}"?'
    if written.startswith("script/"):
        return (text + " Paths start inside the script folder, so write "
                f'include "{show(written.removeprefix("script/"))}".')
    return text + " Check the file name, or add the file."


def _e92(written: str, reason: str | None = None) -> str:
    """``reason`` is F01's ``check_ref`` reason; None (the loader passes it for
    ``REASON_OUTSIDE`` and for links leaving the script folder) gives the script-folder text."""
    if reason is None:
        return (f'can\'t include "{show(written)}": paths must stay inside the script folder '
                "and use forward slashes, e.g. routes/hana.vns.")
    return f'can\'t include "{show(written)}": {reason}'


def _e93(written: str) -> str:
    text = f'can\'t include "{show(written)}": only .vns files can be included.'
    return text + " Use lower case." if written.lower().endswith(".vns") else text


_CANT_READ = ("couldn't be read. Check that another program isn't locking it and that you "
              "have permission to read it.")


def _summary(count: int | str, text: str) -> str:
    shown = f"{count:,}" if isinstance(count, int) else count
    return f"…and {shown} more {text}"


def _python(code: str, text: str, subject: str | None = None) -> str:
    """``subject`` (F23): E81 for a minigame argument names it, e.g. ``the argument pairs``."""
    what = _PY_PREFIX[code] if subject is None else show(subject)
    return f"{what} has a mistake: {_finish(text)}"


def _too_big(code: str, role: str) -> str:
    what = {"exec": "this Python", "condition": "this condition",
            "value": "this value"}.get(role) or show(role)       # F23: "the argument pairs"
    if code == "E86":
        return (f"{what} is too complex to check (too deeply nested, or more than 64 lambda). "
                "Split it into several $ lines.")
    return (f"{what} is longer than 100,000 characters, which is the limit. "
            "Split it into several $ lines.")


# --- F05 (F05 02-script.md §5.1, §5.2, §5.4) ------------------------------------------------
# Tag names, values, and corrected tags come from line text, so they go through ``show()``.
# Forms the narrative designer left open (07 G3) are drafted from the nearest given form:
# the italic hint, ``{next=…}``, ``{pause=}``, the E160 lower-case form for values, E166's
# tag names, W41's "lighter" over black, W42s, W43's frame and made-from forms, W46.

# F29 (01 §5.3, 04 §6.3): the three effect tags join the list, the hints, E164, E165, E166;
# E297 and W185 are new; E175 gains an effect reason. The forms the design left open (07 G4,
# G6, G7) are drafted for the narrative designer (07 I-11).

# F30 (04 §5.3): ``username`` joins the list (12 tags).

TAG_NAMES = ("b", "i", "color", "size", "speed", "shake", "wave", "glitch", "pause", "var",
             "next", "username")
_EFFECT_TAGS = ("shake", "wave", "glitch")
_TAG_LIST = ("The tags are b, i, color, size, speed, shake, wave, glitch, pause, var, next, "
             "and username.")
_STYLE_WORDS = {"b": "bold", "i": "italic", "color": "color", "size": "size",
                "speed": "speed", "shake": "shaking", "wave": "waving", "glitch": "glitching"}
_E160_HINTS = {
    "bold": "For bold, write {b}…{/b}.",
    "italic": "For italics, write {i}…{/i}.",
    "pause": "To wait for a click, write {pause}; to wait half a second, write {pause=0.5}.",
    "speed": "To change typing speed, write {speed=2}…{/speed} for twice as fast.",
    "next": "To move on by itself, end the text with {next}.",
    "shake": "To shake text, write {shake}…{/shake}.",
    "wave": "To make text ripple, write {wave}…{/wave}.",
    "glitch": "To make text glitch, write {glitch}…{/glitch}.",
}


def _e160(form: str, written: str, extra: str | None = None) -> str:
    """``("suggest", name, suggestion)``, ``("list", name)``, ``("case", tag, fixed)``,
    ``("hint", name, kind)`` with a kind of ``_E160_HINTS``, or ``("missing", name)``."""
    if form == "case":
        return f"tags are lower case: write {{{show(extra or '')}}}, not {{{show(written)}}}."
    head = f'there is no tag "{show(written)}"'
    if form == "suggest" and extra is not None:
        return f"{head}. " + _did_you_mean(extra, written)
    if form == "hint" and extra in _E160_HINTS:
        return f"{head}. {_E160_HINTS[extra]}"
    if form == "missing":
        return f"{head} in this engine version. {_TAG_LIST}"
    return f"{head}. {_TAG_LIST}"


_E161 = {
    "open": "this { never closes. End the tag with }, or write {{ to show a {.",
    "empty": "{} is an empty tag. To show {}, write {{}.",
    "inside": "a { can't go inside a tag. To show a {, write {{.",
    "deep": "this line has more than 50 style tags open at once. Close some with {/…}.",
}


def _e161(form: str) -> str:
    return _E161[form]


def _e162(form: str, fixed: str) -> str:
    """``fixed`` is the tag as it should be written, without braces."""
    tag = f"{{{show(fixed)}}}"
    if form == "equals":
        return f"write {tag}, with = between the tag and its value."
    if form == "quote":
        return f"tag values have no quotes: write {tag}."
    if form == "colon":
        return f"write {tag}, with = instead of :."
    return f"tags have no spaces inside: write {tag}."


_E163_NEEDS = {
    "color": "{color} needs a color, e.g. {color=#e05050}…{/color}.",
    "size": "{size} needs a number, e.g. {size=1.5} for half again as big.",
    "speed": "{speed} needs a number, e.g. {speed=0.5} for half speed, or {speed=instant}.",
    "var": "{var} needs a variable's name, e.g. {var=player_name}.",
    "pause": "{pause=} needs a number of seconds, e.g. {pause=0.5}, or write {pause} to wait "
             "for a click.",
    "username": "{username=} needs a variable's name, e.g. {username=player_name}, or write "
                "{username} alone.",                                  # F30: a draft
}


def _e163(form: str, name: str) -> str:
    """``("needs", name)``: a value is missing; ``("none", name)``: ``b``, ``i``, ``next``
    take none; ``("close", name)``: a closing tag has one."""
    if form == "close":
        return f"a closing tag takes no value. Write {{/{name}}}."
    if form == "none":
        if name == "next":
            return "{next} takes no value. Write {next} at the very end of the text."
        return f"{{{name}}} takes no value. Write {{{name}}}…{{/{name}}}."
    return _E163_NEEDS[name]


_E164_RANGES = {
    "pause": "{pause=…} takes seconds from 0.1 to 30, but this has {v}.",
    "speed": ("{speed=…} takes a number from 0.1 to 10, or instant, but this has {v}. Speeds "
              "are relative: 2 is twice as fast, 0.5 half as fast."),
    "size": ("{size=…} takes a number from 0.5 to 2, but this has {v}. Sizes are relative: "
             "1.5 is half again as big."),
}


_E164_EFFECT_ENDS = {"shake": "for a bigger shake", "wave": "for a bigger wave",
                     "glitch": "for more glitching"}


def _e164(form: str, name: str, value: str, number: str = "") -> str:
    """Forms: ``color`` (not a color), ``hash`` (six hex digits without ``#``), ``range``
    (a bad or out-of-range number), ``unit`` (``number`` + a unit), ``dot`` (``.5``),
    ``var`` (not one name; F30: also ``{username=…}``'s), ``effect`` (F29: not small,
    medium, or large; an empty value is ``{shake=}``'s own form, 07 G6)."""
    shown = show(value)
    if form == "effect":
        if not value:
            return (f"{{{name}=}} takes small, medium, or large: write {{{name}}} for medium, "
                    f"or {{{name}=large}}.")
        return (f"{{{name}=…}} takes small, medium, or large, or no value, but this has "
                f'"{shown}". Write {{{name}=large}} {_E164_EFFECT_ENDS[name]}.')
    if form == "color":
        return (f'"{shown}" isn\'t a color. Write # and six digits or letters a to f, '
                "e.g. {color=#e05050}.")
    if form == "hash":
        return f"write the color with #: {{color=#{shown}}}."
    if form == "unit":
        return (f"numbers in tags have no units: write {{{name}={show(number)}}}, "
                f"not {{{name}={shown}}}.")
    if form == "dot":
        return f"write 0{shown}, not {shown}."
    if form == "var":
        return (f"{{{name}=…}} takes one variable's name, such as {{{name}=player_name}}, but "
                f'this has "{shown}". To show something else, store it in a variable first.')
    return _E164_RANGES[name].replace("{v}", shown)


def _e165(name: str) -> str:
    if name in _STYLE_WORDS:
        word = _STYLE_WORDS[name]
        return (f"{{/{name}}} closes {word}, but no {{{name}}} is open here. Remove it, or add "
                f"{{{name}}} where {word} should start.")
    return f"{{{name}}} doesn't open anything, so there is no {{/{name}}}. Remove it."


def _e166(closing: str, inside: str) -> str:
    return (f"{{/{closing}}} closes {_STYLE_WORDS[closing]}, but {{{inside}}} was opened "
            f"inside it and is still open. Close {{/{inside}}} first: "
            f"{{{closing}}}…{{{inside}}}…{{/{inside}}}{{/{closing}}}.")


def _e167(form: str) -> str:
    if form == "twice":
        return "this line has {next} twice. Keep the last one."
    return ("{next} goes at the very end of the text, because the line moves on as soon as "
            "it is shown. Move it to the end, or use {pause} to wait here.")


def _e175(tag: str = "pause") -> str:
    """F07's E175 (SR-F07-05); F29's effect tags give their own reason (07 G4); F30's
    ``{username}`` gives E302's wording."""
    if tag == "username":
        return _username_only("a choice")
    reason = ("choices are shown without text effects" if tag in _EFFECT_TAGS
              else "choices appear all at once")
    return (f"{{{tag}}} can't be used in a choice, because {reason}. Choices can use {{b}}, "
            "{i}, {color}, and {var}.")


def _e297(inner: str = "wave", outer: str = "shake") -> str:
    """F29: an effect opened inside a different open one (01 §5.3)."""
    return (f"{{{inner}}} can't go inside {{{outer}}}: a character has one effect at a time. "
            f"Close {{/{outer}}} first, or pick one: {{{outer}}}…{{/{outer}}}"
            f"{{{inner}}}…{{/{inner}}}.")


def _w185(count: int = 41, strength: str = "medium") -> str:
    """F29 (dev): an outermost ``{glitch}`` with more than 40 medium or large non-space
    graphemes, which is all it counts (07 G7); ``strength`` is the largest counted."""
    share = "about half" if strength == "large" else "about a quarter"
    return (f"this {{glitch}} has {int(count):,} characters glitching at medium or large, so "
            f"{share} of them show as symbols at any moment and the line is hard to read. Use "
            "a shorter span or {glitch=small}; History always shows the real text.")


def _e168(option: str, shown: str | None = None) -> str:
    """``shown``: the refused ``text_italic`` value as the script wrote it (``"yes"``)."""
    if option == "text_italic":
        text = "text_italic is True or False, e.g. text_italic=True"
        return text + (f", but this has {show(shown)}." if shown is not None else ".")
    return ('text_color must be a color: # and six digits or letters a to f, '
            'e.g. text_color="#9ec5ff".')


_TAG_RE = re.compile(r"\{[^{}]*\}")


def _e169(name: str) -> str:
    plain = _TAG_RE.sub("", name).replace("{", "").replace("}", "").strip() or "Hana"
    return (f'character names are shown exactly as written, so "{show(name)}" would show its '
            f'braces. Write Character("{show(plain)}"); the name\'s color is color="…".')


def _e170(name: str, suggestion: str | None = None) -> str:
    tag = f"{{var={show(name)}}}"
    if suggestion is not None:
        return f"{tag} shows a variable that doesn't exist. " + _did_you_mean(suggestion, name)
    return (f"{tag} shows a variable that doesn't exist yet. Add default {show(name)} = … at "
            "the top level so it always has a value.")


def _e171(name: str, kind: str, name_from: str | None = None) -> str:
    """``kind`` in SR-F03-33's words (``a list``); ``a character`` takes the Character form,
    whose example is the character's ``name_from`` (else ``<name>_name``)."""
    shown = show(name)
    head = f"{{var={shown}}} can show text or a number, but {shown}"
    if kind == "a character":
        example = show(name_from) if name_from else f"{shown}_name"
        return (f"{head} is a character. To show her name, show the variable her name_from "
                f"names, e.g. {{var={example}}}.")
    return f"{head} holds {kind}. Store the text to show in its own variable."


def _w40(boxes: int, size: int) -> str:
    clicks = "once" if boxes == 2 else f"{boxes - 1} times"
    return (f"this line needs {boxes} text boxes at text size {size}, so the player clicks "
            f"{clicks} partway through. To choose where it breaks, split it into two lines.")


def _ratio(value: float) -> str:
    """G1: contrast ratios print floored to one decimal (4.47 → 4.4)."""
    return f"{math.floor(value * 10 + 1e-9) / 10:.1f}"


def _hex_luminance(color: str) -> float | None:
    """WCAG relative luminance of a ``#rrggbb`` color, or None for anything else."""
    text = color[1:] if color.startswith("#") else color
    if len(text) != 6:
        return None
    try:
        channels = [int(text[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return None
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _w41(form: str, who: str, color: str, ratio: float, other: str,
         box: str | None = None) -> str:
    """``("name", who, color, ratio, plate_color)`` or ``("text", who, text_color, ratio,
    backdrop, box_color)``; ``backdrop`` is the worse picture, ``"white"`` or ``"black"``.
    The text form advises "darker" when the text is darker than the box (``box_color``,
    the box's fill), else "lighter": moving away from the box raises the contrast. Without
    ``box`` the backdrop decides, as before."""
    if form == "name":
        return (f"{show(who)}'s name color {color} is hard to read on the name plate "
                f"({_ratio(ratio)}:1; names need at least 3:1). Pick a color further from "
                f"the plate's {other}.")
    text_l = _hex_luminance(color)
    box_l = _hex_luminance(box) if box is not None else None
    if text_l is not None and box_l is not None:
        shade = "darker" if text_l < box_l else "lighter"
    else:
        shade = "lighter" if other == "black" else "darker"
    return (f"{show(who)}'s text_color {color} is hard to read on the text box "
            f"({_ratio(ratio)}:1 over a {other} picture; text needs at least 4.5:1). Pick a "
            f"{shade} color, or raise fill_opacity under [theme.textbox] in config.toml.")


def _w42(name: str, suggestion: str | None = None) -> str:
    shown = show(name)
    text = (f"{{var={shown}}} shows a variable that no default or define sets, so the story "
            "stops if this line runs before a $ line sets it. ")
    if suggestion is not None:
        return text + _did_you_mean(suggestion, name)
    return text + f'Add default {shown} = "" at the top level.'


_W43_MADE = {"bold_font": "bold text is made by thickening your text_font",
             "italic_font": "italic text is made by slanting your text_font",
             "bold_italic_font": "bold italic text is made from your text_font"}


def _w43(key: str, ref: str, problem: str, suggestion: str | None = None,
         made_from_text_font: bool = False, area: str = "textbox") -> str:
    """``problem`` is ``"missing"`` or ``"unreadable"``. A ``frame_image`` falls back to the
    drawn box; a font to the built-in one, or (G4) for ``bold_font``/``italic_font``/
    ``bold_italic_font`` with an author ``text_font``, to a face made from it. ``area``
    ``"choice"`` (F07, ``[theme.choice]``): a frame (``frame_image``,
    ``focused.frame_image``) falls back to the drawn button, ``text_font`` to the text
    box's font."""
    head = f'config.toml: [theme.{area}] {key} "{show(ref)}"'
    if area == "choice" and key.endswith("frame_image"):
        result = "so the drawn button is used."
        if problem == "unreadable":
            return f"{head} couldn't be read as an image, {result} Export it again as .png."
    elif area == "choice":
        result = "so the text box's font is used."
        if problem == "unreadable":
            return (f"{head} couldn't be read as a font, {result} Export it again as .ttf or "
                    ".otf.")
    elif key == "frame_image":
        result = "so the drawn box is used."
        if problem == "unreadable":
            return f"{head} couldn't be read as an image, {result} Export it again as .png."
    else:
        made = _W43_MADE.get(key) if made_from_text_font else None
        result = f"so {made}." if made else "so the built-in font is used."
        if problem == "unreadable":
            return (f"{head} couldn't be read as a font, {result} Export it again as .ttf or "
                    ".otf.")
    text = f"{head} doesn't exist, {result}"
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text


def _w44(text_color: str, fill_color: str, opacity: float, ratio: float,
         backdrop: str, area: str = "textbox", text_key: str = "text_color",
         fill_key: str = "fill_color", opacity_key: str = "fill_opacity") -> str:
    """``area`` ``"choice"`` (F07) names ``[theme.choice]`` and, for the focused or locked
    look, its keys (``focused.fill_color``, ``locked.text_color``,
    ``locked.fill_opacity``)."""
    return (f"config.toml: [theme.{area}] {text_key} {text_color} on {fill_key} {fill_color} "
            f"at {opacity_key} {opacity:g} gives {_ratio(ratio)}:1 over a {backdrop} picture; "
            f"text needs at least 4.5:1. Raise {opacity_key} or pick colors further apart.")


def _w45(face: str) -> str:
    if face == "italic":
        return ("config.toml: [theme.textbox] text_font is set but italic_font isn't, so "
                "italic text is made by slanting your font. Add italic_font for a real italic "
                "face.")
    return ("config.toml: [theme.textbox] text_font is set but bold_font isn't, so bold text "
            "is made by thickening your font. Add bold_font for a real bold face.")


def _w46(name: str, missing: bool = True) -> str:
    """G5: one form for load, rollback, and hot reload; ``missing`` False is a value that is
    no longer text or a number."""
    shown = show(name)
    what = "no longer exists" if missing else "no longer holds text or a number"
    return (f"this line was restored, but {{var={shown}}} {what} in this version of the game, "
            f"so it shows as empty text. Add default {shown} = … at the top level so older "
            "saves keep showing it.")


# --- F03 run (F03 02-script.md §5.3) ---------------------------------------------------------
# ``suffix`` is SR-F03-34's `` (in define bonus, script/main.vns, line 7)``; it ends the first
# sentence. ``subject`` is SR-F03-30's role words: "this Python" ($ line), "this condition"
# (if/elif), and (G10, drafted) "this value" for a define or default. Arguments are raw;
# names go through ``show_name`` here, while Python's own text arrives already echoed.

_CHECK_VALUES = "Check the values this line uses; the log has the details."


def _e85(subject: str, text: str | None = None, suffix: str = "") -> str:
    """E85; ``text`` is Python's message when SR-F03-32 lets it through (else None)."""
    head = f"{subject} stopped with an error"
    if text:
        text = text[:-1] if text.endswith(".") and not text.endswith("..") else text
        head = f"{head}: {text}"
        if not suffix and text.endswith(("?", "!", "…")):
            return f"{head} {_CHECK_VALUES}"
    return f"{head}{suffix}. {_CHECK_VALUES}"


def _e85b(name: str, suggestion: str | None = None, set_at: Place | None = None,
          value: str = "0", suffix: str = "") -> str:
    """E85b. ``set_at`` is the first ``$`` line that sets ``name`` (second form); ``value``
    is the value it sets, as written (``0`` when it isn't a plain assignment)."""
    shown = show_name(name)
    if set_at is not None:
        return (f'there is no variable named "{shown}" yet{suffix}. It is set by a $ line '
                f"({show(set_at[0])}, line {set_at[1]}) that hasn't run in this playthrough. "
                f"Add default {shown} = {show(value)} at the top level so it always has a "
                "value.")
    if suggestion is not None:
        return f'there is no variable named "{shown}"{suffix}. ' + _did_you_mean(suggestion, name)
    return (f'there is no variable named "{shown}"{suffix}. Check the spelling, or add a '
            f"default for it at the top level, e.g. default {shown} = 0.")


DICE_CALLS_TEXT = "dice can roll, pick, decimal, and shuffle."


def _e85c(owner: str, name: str, suggestion: str | None = None, dice: bool = False,
          suffix: str = "", locked: bool = False) -> str:
    """E85c. ``owner`` is the value in words: ``dice``, ``text``, ``the module math``,
    ``hana``, ``a list``, … (G9: lower case after the prefix). ``dice`` adds the list of its
    calls. ``locked`` is the third form (SR-F03-17): the story set or deleted the option
    ``name`` of the character ``owner`` (its define's name)."""
    if locked:
        return (f"{show_name(owner)}'s options are fixed when the game starts, so the story "
                f"can't change {show_name(name)}. To change the shown name, use name_from.")
    text = f'{owner} has no "{show_name(name)}"{suffix}.'
    if suggestion is not None and suggestion != name:
        text += " " + _did_you_mean(suggestion, name)
    if dice:
        return f"{text} {DICE_CALLS_TEXT}"
    if suggestion is None:
        text += " Check the spelling."
    return text


_NUMBER_KINDS = frozenset(("text", "a whole number", "a decimal number"))


def _e85d(form: str, left: str, right: str, op: str = "+", suffix: str = "") -> str:
    """E85d. ``form`` is ``add`` (CPython's concatenation text, or ``+``), ``operator``, or
    ``compare``; ``left`` and ``right`` are SR-F03-33 kinds. G10 (drafted): kinds other than
    text and numbers get "Check the values this line uses." as the fix."""
    if form == "compare":
        first = f"this compares {left} and {right} with {op}, which Python can't do"
        fix = "Convert one first with int(…) or str(…)."
    elif form == "add":
        first = f"this adds {left} and {right}, which Python can't do"
        fix = "Convert one first with int(…), float(…), or str(…)."
        if {left, right} == {"text", "a whole number"}:
            fix = 'Convert one first: int("3") + 1 adds numbers, "3" + str(1) joins text.'
    else:
        first = f"this uses {op} with {left} and {right}, which Python can't do"
        fix = "Convert one first with int(…), float(…), or str(…)."
    if not {left, right} <= _NUMBER_KINDS:
        fix = "Check the values this line uses."
    return f"{first}{suffix}. {fix}"


_E85E_ADVICE = {
    "a set": "Use a list instead, e.g. $ {n} = [].",
    "a function": "Put helpers in a define, e.g. define {n} = lambda: trust * 2.",
    "a module": 'Add define {n} = module("{m}") at the top level instead.',
    "a character": "Create characters with define, and use name_from to change a shown name.",
    # G10 (drafted): tuples and the dice.
    "a tuple": "Use a list instead, e.g. [1, 2] rather than (1, 2).",
    "the dice": "Store what dice gives back instead, e.g. $ {n} = dice.roll(1, 6).",
}
_PLAIN_KINDS = ("Story variables can hold None, True, False, numbers, text, lists, and "
                "dictionaries.")


def _e85e(reason: str, name: str, path: str | None = None, kind: str = "",
          detail: str = "") -> str:
    """E85e (no ``(set at …)`` clause, I-14). ``reason`` is one of ``values.py``'s
    Unsaveable reasons; ``path`` is ``inventory["bag"][2]`` when the value is inside the
    variable (shown unquoted); ``kind`` the value's SR-F03-33 words; ``detail`` the
    module's name (module) or the key (key)."""
    subject = f'"{show_name(name)}"' if path is None else show(path)
    if reason == "kind":
        advice = _E85E_ADVICE.get(kind)
        if advice is None:
            advice = _PLAIN_KINDS
        elif path is not None and kind == "a set":
            advice = "Use a list instead."
        elif path is not None and kind in ("a function", "a module", "the dice"):
            advice = _PLAIN_KINDS
        advice = advice.replace("{n}", show_name(name)).replace("{m}", show(detail or name))
        return f"{subject} holds {kind}, which can't be saved. {advice}"
    if reason == "key":
        example = f'Use text keys, e.g. "{show(detail)}".' if detail else "Use text keys."
        shown = f" ({show(detail)})" if detail else ""
        return (f"{subject} holds a dictionary with a key that isn't text{shown}, which can't "
                f"be saved. {example}")
    if reason == "nan":
        return (f'{subject} holds "not a number" (nan), which can\'t be saved. Check the '
                "calculation that set it.")
    if reason == "inf":
        return (f"{subject} holds infinity (inf), which can't be saved. Check the calculation "
                "that set it.")
    if reason == "big_int":
        return (f"{subject} holds a whole number with more than 4,300 digits, which can't be "
                "saved. Check the calculation that set it.")
    return (f"{subject} holds lists or dictionaries nested more than 100 levels deep, or one "
            "that contains itself, which can't be saved. Keep the data flatter, and store a "
            "copy, e.g. list(party), instead of the list itself.")


def _e85f(subject: str, call: str = "exit()", suffix: str = "") -> str:
    return (f"{subject} tried to close the game with {show(call)}{suffix}. To end the story, "
            "use return instead.")


_E85J_COUNTS = {"roll": "2 values, e.g. dice.roll(1, 6)", "pick": "1 value, e.g. "
                "dice.pick(fortunes)", "shuffle": "1 value, e.g. dice.shuffle(deck)"}


def _e85j(call: str, form: str, kind: str = "", value: str = "", got: int = 0,
          values: tuple[str, str] = ("", ""), arg: str | None = None, suffix: str = "") -> str:
    """E85j. ``form`` is ``dice.py``'s ``DiceArgumentError.form``: ``order`` (``values``
    are lo and hi as written), ``whole`` (``kind``, and ``value`` for plain values),
    ``empty`` (``arg``: the list as written, when known), ``list`` (``kind``), ``count``
    (``got``). G10 (drafted): ``pick`` and ``shuffle`` counts, a non-list ``pick``."""
    if form == "order":
        lo, hi = (show(v) for v in values)
        return (f"dice.{call}({lo}, {hi}) needs the smaller number first{suffix}. Write "
                f"dice.{call}({hi}, {lo}).")
    if form == "whole":
        shown = f" ({show(value)})" if value else ""
        return f"dice.{call} takes whole numbers, but got {kind}{shown}{suffix}."
    if form == "empty":
        head = f"dice.{call} got an empty list, so there is nothing to pick{suffix}."
        if arg:
            return f"{head} Check that the list has items first, e.g. if {show(arg)}:."
        return f"{head} Check that the list has items first."
    if form == "list":
        return f"dice.{call} takes a list, but got {kind}{suffix}."
    if call == "decimal":
        return f"dice.decimal takes nothing in the brackets{suffix}. Write dice.decimal()."
    return f"dice.{call} takes {_E85J_COUNTS.get(call, '1 value')}, but got {got}{suffix}."


def _e85m(subject: str, suffix: str = "") -> str:
    return (f"{subject} ran for 5 seconds without finishing, so it is probably stuck in a "
            f"loop{suffix}. Check any while loop in this line and in the helpers it uses.")


def _e85n(call: str, suffix: str = "") -> str:
    return (f"{call}() can't be used in a game, because there is no console to type "
            f"into{suffix}. Remove it; to ask the player, use a menu once choices are "
            "available.")


# --- F03 limits (F03 02-script.md §5.3; raised by engine/runtime/interpreter.py) -----------

def _e45(steps: int, labels: Sequence[str], more: int = 0) -> str:
    """E45 (SR-F03-26): ``steps`` (``STEP_LIMIT``) steps ran without a line. ``labels``
    are the labels of the loop to name (at most 3, most often entered first), ``more`` how
    many other labels were entered: ``"a"``; ``"a" and "b"``; ``"a", "b", and "c"``;
    ``"a", "b", "c", and 2 more``."""
    shown = [f'"{show_name(n)}"' for n in labels]
    if more > 0:
        shown.append(f"{more:,} more")
    listed = " and ".join(shown) if len(shown) == 2 else _and_list(shown)
    noun = "label" if len(shown) == 1 else "labels"
    return (f"the story ran {steps:,} steps without showing a line, so it is probably stuck in "
            f"a loop through the {noun} {listed}. Check the jumps there: every way around the "
            "loop needs a line or a way out.")


def _e45b(waiting: int, count: int, label: str) -> str:
    """E45b (SR-F03-27): ``waiting`` (``CALL_DEPTH_MAX``) calls wait to return, ``count``
    of them to ``label`` (the label with the most)."""
    return (f"{waiting:,} calls are waiting to return, and {count:,} of them called label "
            f'"{show_name(label)}". Did you mean jump? A call always comes back; jump goes to a '
            "label for good.")


# --- F03 launch (F03 02-script.md §5.2) and the Character run texts (§5.3) --------------------
# E75 to E75g have no prefix (``Character`` refuses its own call, AC-F03-32). E85k, E85l, E89,
# E89b, and E89c are the text after SR-F03-31's prefix ``define X couldn't be set: ``, which
# ``engine/runtime/launch.py`` adds, as for the E85 family above. ``kind`` arguments are
# SR-F03-33's words (``engine/runtime/values.kind_words``). Messages naming ``Character``
# start with its capital C: it is the name the author writes (as ``02`` §5.2 shows).

_COLOR_EXAMPLE = 'color="#e8a0b4"'


def _speaker_example(name: str, text: str | None) -> str:
    """E75's example name: the define's text if it is non-empty text, else the define's
    name with its first letter in capitals."""
    return text if text else name[:1].upper() + name[1:]


def _e75(name: str, kind: str, text: str | None = None, place: Place | None = None) -> str:
    """E75 (SR-F03-16). ``place`` is the first line where the define speaks (launch);
    without it, the run form: a ``$`` line replaced the speaker's value during the story
    (AC-F03-33's last row; G10, drafted). ``text`` is the value when it is text."""
    shown = show_name(name)
    fix = f'Write define {shown} = Character("{show(_speaker_example(name, text))}").'
    if place is None:
        return f'"{shown}" speaks here, but it holds {kind}, not a character. {fix}'
    return (f'"{shown}" speaks in the story ({_place(place)}), but its define gives {kind}, '
            f"not a character. {fix}")


def _option_list(options: Sequence[str]) -> str:
    """``color and name_from``; ``color, image_tag, and name_from`` (``02`` §5.2)."""
    items = list(options)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return _and_list(items)


def _e75b(key: str, options: Sequence[str], suggestion: str | None = None) -> str:
    """E75b. ``options`` are ``CHARACTER_OPTIONS``' names in order (QA G14: F04 adds
    ``image_tag``); ``name=`` gets its own fix."""
    if key == "name":
        return ('Character has no option "name". Write the name first, in quotes: '
                'Character("Hana").')
    hint = f" {_did_you_mean(suggestion, key)}" if suggestion is not None else ""
    return (f'Character has no option "{show_name(key)}".{hint} Its options are '
            f"{_option_list(options)}.")


def _e135(kind: str | None = None, value: str | None = None) -> str:
    """E135 (F04 SR-F04-23): ``image_tag`` isn't text (``kind``, SR-F03-33's words), or the
    text ``value`` isn't one word of an image name."""
    if value is not None:
        return (f'"{show(value)}" isn\'t a tag. A tag is the first word of image names, e.g. '
                'image_tag="daichi".')
    return (f'image_tag must be one word in quotes, e.g. image_tag="daichi", but this is '
            f"{kind or 'not text'}.")


_BLIP_RANGES = {"blip_every": "a whole number from 1 to 10, e.g. blip_every=2",
                "blip_pitch": "a number from 0.0 to 0.5, e.g. blip_pitch=0.1",
                "blip_volume": "a whole number from 0 to 100, e.g. blip_volume=60"}


def _e179(form: str, value: str = "", reason: str = "") -> str:
    """E179 (F06 SPEC §3), raised by ``runtime/character.py``. ``form``: ``"blip"`` (not
    text; ``value`` is the value as written or its kind), ``"path"`` (``reason`` is F01's),
    ``"format"``, ``"prefix"`` (``value`` is the file), an option of ``_BLIP_RANGES`` (the
    value as written), or ``"needs"`` (``value`` is the option given without ``blip``)."""
    if form == "blip":
        return ('blip is a file in quotes inside the audio folder, e.g. blip="blips/hana.ogg", '
                f"but this has {show(value)}.")
    if form == "path":
        return (f"can't use \"{show(value)}\" for blip: {reason}. Paths start in the audio "
                'folder and use /, e.g. "blips/hana.ogg".')
    if form == "format":
        return (f"\"{show(value)}\" isn't a format the engine plays, so it can't be a blip. "
                "Use .ogg, .opus, .flac, .mp3, or .wav.")
    if form == "prefix":
        return (f'blip paths start inside the audio folder, so write "{show(value[6:])}", not '
                f'"{show(value)}".')
    if form == "needs":
        return f'{value} needs blip="…" in the same Character(...).'
    return f"{form} must be {_BLIP_RANGES[form]}, but this has {show(value)}."


def _w49(file: str, seconds: float) -> str:
    """W49 (F06 SPEC §3; area ``audio``, once per path): ``file`` relative to ``audio/``."""
    return (f"audio/{show(file)} is {seconds:.1f} seconds long, so it plays without "
            "blip_pitch. Blips with blip_pitch must be at most 0.5 seconds; trim the file to "
            "one short sound.")


def _e75c(value: str | None = None) -> str:
    """E75c; ``value`` is the color as written (None: not text)."""
    if value is None:
        return f"color must be text in quotes, e.g. {_COLOR_EXAMPLE}."
    return (f'"{show(value)}" isn\'t a color. Write # and six digits or letters a to f, e.g. '
            f"{_COLOR_EXAMPLE}.")


def _e75d(form: str, count: int = 0) -> str:
    """E75d: ``missing`` (no name and no name_from), ``both``, or ``count`` (``count``
    names before the options)."""
    if form == "both":
        return ("Character takes either a name or name_from, not both. Put the starting name "
                'in the default instead: default hana_name = "???".')
    if form == "count":
        return (f"Character takes one name before its options, but this gives {count:,}. "
                f"Write options with =, e.g. {_COLOR_EXAMPLE}.")
    return 'Character needs the name to show, in quotes, e.g. Character("Hana").'


def _e75e(kind: str = "", name: str | None = None) -> str:
    """E75e: the name to show is ``kind`` (not text), or (SR-F03-12) the unknown bare name
    ``name`` written as the call's first argument."""
    if name is not None:
        shown = show_name(name)
        return (f'"{shown}" isn\'t a name the game knows. If it is the name to show, put it in '
                f'quotes: Character("{shown}").')
    return (f'the name to show must be text in quotes, e.g. Character("Hana"), but this is '
            f"{kind}.")


def _e75f(value: str, suggestion: str | None = None) -> str:
    shown = show_name(value)
    head = f'name_from="{shown}" doesn\'t name a default.'
    if suggestion is not None:
        return f"{head} {_did_you_mean(suggestion, value)}"
    return f'{head} Add default {shown} = "???" at the top level.'


def _e75h(speaker: str, source: str, kind: str | None = None, value: str = "") -> str:
    """E75h (SR-F03-14): ``source`` (the name_from default) holds ``kind``, with ``value``
    for plain values; ``kind`` None means it has no value now (deleted)."""
    if kind is None:
        holds = "which has no value now"
    elif value:
        holds = f"which holds {kind} ({show(value)}), not text"
    else:
        holds = f"which holds {kind}, not text"
    shown = show_name(source)
    return (f"{show_name(speaker)}'s name comes from {shown}, {holds}. Set it to text, e.g. "
            f'$ {shown} = "Hana".')


def _e85k(define: str) -> str:
    return ("it uses dice, which can only be used once a game has started, so the result "
            f"would change at every launch. Use default instead of define for "
            f"{show_name(define)}.")


def _e85l(define: str, name: str, set_at: Place | None = None) -> str:
    """E85l: the define reads ``name``, a default (``set_at`` None) or a name only ``$``
    lines set (``set_at`` is the first one, as E85b's second form)."""
    what = ("a story variable" if set_at is None
            else f"set by a $ line ({_place(set_at)})")
    return (f'it uses "{show_name(name)}", which is {what} and doesn\'t exist yet when defines '
            f"are set at launch. Make {show_name(define)} a default instead.")


def _e89(name: str, suggestion: str | None = None) -> str:
    tail = (f'Did you mean "{show(suggestion)}"?' if suggestion is not None
            else "Check the spelling.")
    return f'there is no Python module named "{show(name)}". {tail}'


def _e89c(form: str, name: str) -> str:
    """E89c: ``game`` (a file in the game folder), ``elsewhere`` (not part of Python or an
    installed package), or ``engine`` (``name`` is ``engine`` or ``main``)."""
    if form == "game":
        return (f'"{show(name)}" is a file in the game folder, and module can only use modules '
                "that come with Python or are installed. Write small helpers in a define with "
                "lambda instead.")
    if form == "engine":
        return (f'"{show(name)}" is the engine\'s own code, which a story can\'t use through '
                "module. Remove this define.")
    return (f'"{show(name)}" doesn\'t come with Python and isn\'t installed, so module can\'t '
            'use it. Use a module that comes with Python, such as "math".')


# --- F04 load (F04 02-script.md §5.1; raised by script/stage.py, statements.py, checks.py) ---
# Texts the table leaves open (F04 06 G4) are drafted from the nearest given form; the
# narrative designer approves them with the F04 cases.toml rows (F04 07 I-12).

_X_RANGE = f"{STAGE_COORD_RANGE[0]} to {STAGE_COORD_RANGE[1]}"
_SCREEN = f"0 to {CANVAS_SIZE[0]} across and 0 to {CANVAS_SIZE[1]} down"

# E110: what each modifier takes (``at``, ``as``, ``layer`` given; the rest drafted).
_TAKES = {"at": "at takes one position name, or one or two numbers.",
          "as": "as takes one tag.", "behind": "behind takes one tag.",
          "layer": "layer takes one number.", "zoom": "zoom takes one number.",
          "flip": "flip takes on or off."}

# E113: what each modifier needs after it (``zoom`` drafted; ``flip`` alone is E125).
_NEEDS = {"at": "a position after it, e.g. at left",
          "as": "a tag after it, e.g. show student as student_b",
          "behind": "the tag of a sprite, e.g. behind stall",
          "layer": "a number after it, e.g. layer 10",
          "zoom": "a number after it, e.g. zoom 1.5",
          "with": "a transition after it, e.g. with dissolve"}

_AT_TAKES = "at takes a position name or one or two numbers, e.g. at left or at 400 680"


def _e110(form: str, *args: object) -> str:
    """``("left", leftover, after, word)``: something left over after a modifier's value;
    ``("colon", word)``: the line ends with ``:``."""
    if form == "colon":
        return f"{args[0]} doesn't start a block. Remove the :."
    leftover, after, word = args
    return (f'this line has "{show(str(leftover))}" left over after {show(str(after))}. '
            f"{_TAKES.get(str(word), '')}").rstrip()


def _e112(word: str) -> str:
    if word == "hide":
        return "hide needs the tag of a sprite, e.g. hide hana."
    return f"{word} needs an image name, e.g. {word} hana happy."


def _e116(form: str, *args: str) -> str:
    """``("words", tag, written)`` (more than the tag) or ``("modifier", word)``."""
    if form == "words":
        tag, written = args
        return f"hide takes only the tag: write hide {show(tag)}, not {show(written)}."
    word = args[0]
    then = "To move a sprite, use show." if word == "at" else "To change a sprite, use show."
    return f"hide doesn't take {word}. {then}"


def _e117(form: str, word: str, written: str, name: str) -> str:
    """``form`` "file" (a file path for a name) or "quotes"; ``word`` is the statement."""
    if form == "quotes":
        return f"image names aren't written in quotes. Write {word} {show(name)}."
    return (f'"{show(written)}" is a file, not an image name. Write the name made from it: '
            f"{word} {show(name)}.")


def _e119(word: str, part: str, tag: str | None = None, speaker: str | None = None) -> str:
    """``tag`` is the speaker's image tag when the whole-game checks can tell it for sure
    (F04 07 I-12: the hint never names a tag that might be wrong); otherwise the hint names
    no tag. ``speaker`` is for those checks only."""
    head = f'"{word}" can\'t go on a dialogue line; only expression words can.'
    if tag is None:
        return f"{head} Put {show(part)} on a show line above."
    return f"{head} Put show {show(tag)} {show(part)} on the line above."


def _e120(name: str, suggestion: str | None = None) -> str:
    head = f'there is no position named "{show(name)}".'
    if suggestion is not None:
        return f'{head} Did you mean "{show(suggestion)}"?'
    return (f"{head} Use left, center, right, or a number such as at 400, or add "
            f"{show(name)} to [stage.positions] in config.toml.")


def _e121(written: str, direction: str) -> str:
    return (f"{show(written)} is {direction}. Positions go from {_X_RANGE}; the screen itself "
            f"is {_SCREEN}.")


def _e122(form: str, value: object) -> str:
    """``form`` "count" (``value`` numbers), or "units", "comma", "letter", "other" (``value``
    the text as written)."""
    if form == "count":
        return f"at takes at most two numbers, x and y, but this has {value}."
    text = f'{_AT_TAKES}, but this has "{show(str(value))}".'
    if form == "units":
        return f"{text} Numbers have no units."
    if form == "comma":
        return f"{text} Separate the two numbers with a space, not a comma."
    if form == "letter":
        return f"{text} A position name starts with a letter."
    return text


def _has(written: str, quoted: bool) -> str:
    return f'"{show(written)}"' if quoted else show(written)


def _e126(name: str, count: int, declared: bool = False) -> str:
    fix = "Use a shorter name." if declared else "Use fewer folders inside images/."
    return f'"{show(name)}" has {count} words, but an image name has at most 5. {fix}'


def _e127(form: str, word: str, tag: bool = False, fixed: str | None = None) -> str:
    """``form`` "stage" (a stage word), "statement" (a statement word), or "characters";
    ``tag``: the word is a sprite's tag (after ``as`` or ``behind``, or ``hide``'s);
    ``fixed`` is the word with ``_`` for the characters a name can't hold, when that gives
    a word."""
    what = "a tag" if tag else "part of an image name"
    if form == "stage":
        text = f'"{show(word)}" is a word show uses, so it can\'t be {what}.'
        return text if tag else f"{text} Rename the image."
    if form == "statement":
        return f'"{show(word)}" is a statement word, so it can\'t be {what}.'
    kind = "Tags" if tag else "Names"
    example = f", e.g. {show(fixed)}" if fixed else ""
    return f'"{show(word)}" can\'t be {what}. {kind} use letters, digits, and _{example}.'


def _e131(form: str = "shape") -> str:
    if form == "quotes":
        return 'the file or color goes in quotes, e.g. image bg festival = "art/festival.png".'
    return ('image needs a name, =, and a file or color in quotes, e.g. '
            'image bg dusk = "#2b2140".')


def _e132(form: str, value: str, reason: str | None = None) -> str:
    """``form`` "outside" (F01's REASON_OUTSIDE), "reason" (another PR-F01-55 reason),
    "type" (not PNG, JPEG, or WebP), or "color"."""
    if form == "color":
        return (f'"{show(value)}" isn\'t a color. Write # and six digits or letters a to f, '
                'e.g. "#2b2140".')
    if form == "type":
        return f'"{show(value)}" isn\'t a PNG, JPEG, or WebP file. Convert it to .png.'
    if form == "reason":
        return f'can\'t use "{show(value)}": {reason}.'
    return (f'can\'t use "{show(value)}": paths start in the game folder and must stay inside '
            'it, using forward slashes, e.g. "art/festival.png".')


def _e133(name: str, first: Place) -> str:
    return (f'there is already an image "{show(name)}" declared in {_place(first)}. '
            "Remove or rename one.")


# --- F04 launch warnings (F04 02-script.md §5.3; raised by engine/runtime/stage_check.py) ---
# Forms the table leaves open are drafted from the nearest given form (F04 07 I-12; 06 G2,
# G4): W10 for a folder, for "characters", and with no rename; W11's file order; W12's case
# form for a folder or a declared name; W12b and W16 with no suggestion; W13 for an
# image_tag. W14 is retired by F09 (C5). W10b (the scan stop line, I-10) and W10s (the
# summary after the 100-record cap, I-9) are the texts of 06 D2, with "…" (N1).

# W10's reasons (``engine/runtime/images.py`` NameProblem.reason) → the bracket.
_W10_WHY = {"hyphen": "(no - in names)", "space": "(no spaces in names)",
            "dot": "(one dot only, before the extension)",
            "characters": "(names use letters, digits, and _)"}
_W10_FOLDER_DOT = "(no dots in folder names)"
_LETTERS_ONLY = "so its name uses only letters, digits, and _."
W10_EXAMPLE = (("images/bg/bridge-day.png", "hyphen", "bridge-day.png", "bridge_day.png", False),)


def _stem(file_name: str) -> str:
    dot = file_name.rfind(".")
    return file_name[:dot] if dot > 0 else file_name


def w10_line(ref: str, reason: str, word: str | None = None, rename: str | None = None,
             folder: bool = False) -> str:
    """One line of W10: ``ref`` is the file; ``word`` the file name (with its extension) or,
    with ``folder``, the folder name that breaks a rule; ``rename`` what to rename it to."""
    head = f"{show(ref)}: "
    if reason == "too_many_words":
        return f"{head}move it so its name has at most 5 words."
    if reason in ("statement_word", "stage_word"):
        bare = show(word if folder else _stem(word or ""))
        what = "a statement word" if reason == "statement_word" else "a word show uses"
        why = f'("{bare}" is {what})'
    elif folder and reason == "dot":
        why = _W10_FOLDER_DOT
    else:
        why = _W10_WHY.get(reason, _W10_WHY["characters"])
    if folder:
        what = f"rename the folder {show(word or '')}"
        if rename is None:
            return f"{head}{what} {_LETTERS_ONLY}"
        return f"{head}{what} to {show(rename)} {why}."
    if rename is None:
        return f"{head}rename it {_LETTERS_ONLY}"
    return f"{head}rename it {show(rename)} {why}."


def w10_text(problems: Sequence[tuple] = W10_EXAMPLE, more: int = 0) -> str:
    """The one W10 record: the head line, one ``w10_line`` per problem (the caller gives at
    most 20), then ``…and N more.`` Each line is cut on its own (``show`` cuts each ref and
    name to 120 characters), so the record is at most about 21 × 300 characters."""
    lines = ["Some image files have names a script can't use:"]
    lines += [truncate(w10_line(*problem), SCRIPT_MESSAGE_MAX_CHARS) for problem in problems]
    if more:
        lines.append(f"…and {more:,} more.")
    return "\n".join(lines)


def _w11(name: str = "hana happy", used: str = "images/hana/happy.png",
         other: str = "images/hana/happy.webp") -> str:
    """The two files in ref code-point order; ``used`` is the one that gives the name."""
    first, second = sorted((used, other))
    suffix = used[used.rfind("."):] if "." in used else used
    return (f'{show(first)} and {show(second)} both give the image "{show(name)}". The '
            f"{show(suffix)} is used; remove or rename the other.")


def image_path(name: str) -> str:
    """The file a name would come from: ``hana blush`` → ``images/hana/blush.png``."""
    return "images/" + "/".join(name.split(" ")) + ".png"


def _w12(name: str = "hana blush", suggestion: str | None = None,
         rename: tuple[str, str, bool] | None = None) -> str:
    """No such image. ``suggestion`` is the did-you-mean; with ``rename`` = ``(old, new,
    folder)`` it is the case-only match and the text names the file (or folder) to rename."""
    head = f'there is no image "{show(name)}", so a placeholder will show.'
    if rename is not None and suggestion is not None:
        old, new, folder = rename
        what = f"the folder {show(old)}" if folder else show(old)
        return (f"{head} Names match files exactly: rename {what} to {show(new)}, or write "
                f"{show(suggestion)}.")
    if suggestion is not None:
        return f'{head} Did you mean "{show(suggestion)}"?'
    return f"{head} Add {show(image_path(name))}, or check the spelling."


def _w12b(name: str = "bg festival", ref: str = "art/festival_final.png",
          suggestion: str | None = None) -> str:
    text = (f'image {show(name)} uses "{show(ref)}", which doesn\'t exist, so a placeholder '
            "will show.")
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text


def _w13(speaker: str = "hana", words: str = "pout", tag: str | None = None) -> str:
    """``tag`` is the speaker's ``image_tag`` when it has one (drafted form)."""
    who = show_name(speaker)
    noun = "words" if " " in words else "word"
    owner = speaker if tag is None else tag
    head = (f'{who}\'s line has the {noun} "{show(words)}", but there are no images for '
            f"{show_name(owner)}, so it changes nothing. Add "
            f"{show(image_path(owner + ' ' + words))}, or if the images have another name, ")
    if tag is not None:
        return f'{head}change image_tag="{show(tag)}" in define {who} = Character(…).'
    return f'{head}add image_tag="that_name" to define {who} = Character(…).'


def _w16(tag: str = "dsk", suggestion: str | None = None) -> str:
    text = (f'behind {show(tag)}: no show in the game puts a sprite tagged "{show(tag)}" on '
            "stage, so this does nothing.")
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text


# --- F08 load (F08 02-script.md §5.1; raised by engine/script/audio.py, audio_checks.py) ---
# Forms 02 gives only by example are drafted from the nearest given form (F08 07 I-14; 06 G4)
# for the narrative designer to approve with the F08 cases.toml rows: E140 "isn't a channel"
# for stop and queue; E142 for play sound and queue music; E143's fix example for every input;
# E146's option list for queue and stop, its left-over tails other than "takes one number",
# its second-file form, and its with form for stop and queue; E148's prefix for queue music
# restart|from|crossfade and its stop voice form; E150's prefix for units and other words and
# for out-of-range negatives; E151 for an integer over 100 and for a word; W20 for jump, call,
# return, any other statement, and above a menu (F07); W23 for .aac, .wma, and the "other"
# tail; W24 with 1 or 2 files (files in order of first use); W20s, the summary line after
# SCRIPT_AUDIO_WARN_LIMIT W20/W23 records.

_E140_NEEDS = {
    "play": ('play needs a channel before the file, e.g. play music "bgm/festival.ogg" or '
             'play sound "sfx/door.ogg".'),
    "stop": "stop needs a channel: stop music, stop sound, or stop voice.",
    "queue": 'queue needs music before the file, e.g. queue music "bgm/shrine_steps.ogg".',
}
_E140_TAKES = {"play": "music or sound", "stop": "music, sound, or voice",
               "queue": "only music"}
_FILE_EXAMPLES = {"play music": "bgm/festival.ogg", "play sound": "sfx/door.ogg",
                  "queue music": "bgm/shrine_steps.ogg", "stop sound": "sfx/crowd.ogg",
                  "voice": "voice/hana_014.ogg"}
_E146_LISTS = {
    "play": "Its options are fadein, fadeout, volume, loop, once, restart, and from.",
    "queue": "Its options are fadein, volume, loop, and once.",
    "stop": "Its only option is fadeout.",
}
_FADE_EXAMPLE = {"stop": "fadeout 1.0"}
_W23_KINDS = {".m4a": "an M4A file", ".aac": "an AAC file", ".wma": "a WMA file"}
_MIDI = frozenset((".mid", ".midi"))
_AUDIO_FIX = "Convert it to .ogg (Ogg Vorbis) in an audio editor."


def _e140(form: str, word: str, written: str = "", suggestion: str | None = None) -> str:
    """``("needs", word)``: no channel; ``("unknown", word, written, suggestion)``."""
    if form == "needs":
        return _E140_NEEDS.get(word, _E140_NEEDS["play"])
    head = f'"{show(written)}" isn\'t a channel.'
    if suggestion is not None:
        head += f' Did you mean "{show(suggestion)}"?'
    return f"{head} {word} takes {_E140_TAKES.get(word, _E140_TAKES['play'])}."


def _e141(word: str, channel: str, file: str | None = None) -> str:
    """``play voice``, ``queue sound``, ``queue voice``; ``file`` is the line's file."""
    if word == "play":
        shown = show(file) if file else _FILE_EXAMPLES["voice"]
        return (f'voice lines aren\'t started with play. Put voice "{shown}" on the line above '
                "the line it voices.")
    if channel == "sound":
        shown = show(file) if file else _FILE_EXAMPLES["play sound"]
        return f'only music can be queued. To start an effect, write play sound "{shown}".'
    return 'a voice belongs to one line, so it can\'t be queued. Put voice "…" above each line.'


def _e142(form: str, name: str, written: str = "") -> str:
    """``("needs", name)``: no file; ``("quotes", name, written)``: a file without quotes.
    ``name`` is the statement as written (``play music``, ``voice``)."""
    if form == "quotes":
        return f'the file goes in quotes: {name} "{show(written)}".'
    example = _FILE_EXAMPLES.get(name, _FILE_EXAMPLES["play music"])
    return f'{name} needs a file in quotes, e.g. {name} "{example}".'


def _e146(form: str, *args: object) -> str:
    """``("unknown", word, written, suggestion)``, ``("case", word, written, lower)``,
    ``("left", written, after, last, word)``, ``("second_file", word, file)``,
    ``("colon", word)``, ``("with", word)``."""
    if form == "colon":
        return f"{args[0]} doesn't start a block. Remove the :."
    if form == "with":
        word = str(args[0])
        fade = _FADE_EXAMPLE.get(word, "fadein 1.0")
        return (f"{word} doesn't take with; transitions are for pictures. To fade, use "
                f"{fade}.")
    if form == "second_file":
        word, file = args
        return (f'this line has a second file, "{show(str(file))}". {word} takes one file; put '
                "each on its own line.")
    if form == "left":
        written, after, last, word = (str(a) for a in args)
        head = f'this line has "{show(written)}" left over after {show(after)}.'
        if last == "from":
            tail = "from takes one number or current."
        elif last in ("fadein", "fadeout", "volume"):
            tail = f"{last} takes one number."
        elif last in ("loop", "once", "restart"):
            tail = f"{last} takes nothing after it."
        elif last == "channel":
            tail = f"Only fadeout can follow it, e.g. {show(after)} fadeout 1.0."
        else:
            tail = ("Only options can follow the file, e.g. "
                    f"{_FADE_EXAMPLE.get(word, 'fadein 2.0')}.")
        return f"{head} {tail}"
    word, written, extra = args
    head = f'{word} has no option "{show(str(written))}".'
    if form == "case":
        return f"{head} Options are lower case: {extra}."
    if extra is not None:
        return f'{head} Did you mean "{extra}"?'
    return f"{head} {_E146_LISTS.get(str(word), _E146_LISTS['play'])}"


def _e147(form: str, first: str, second: str = "") -> str:
    if form == "clash":
        return f"{first} and {second} can't be used together. Keep one."
    return f"this line has {first} twice. Keep one."


def _e148(form: str, value: str = "") -> str:
    """The option or file this statement or channel doesn't take (SR-F08-05, 13, 18b, 21)."""
    if form == "sound_fadeout":
        return ("fadeout can't go on play sound, because a new effect never stops the others. "
                "To fade effects out, use stop sound fadeout 1.0.")
    if form == "sound_restart":
        return "restart only works with play music; each play sound already starts a new effect."
    if form == "sound_from":
        return "from only works with play music."
    if form == "queue_fadeout":
        return "queue music doesn't take fadeout; the track before it plays to its end."
    if form == "queue_start":
        return (f"queue music doesn't take {value}; a queued track always starts from the "
                "beginning.")
    if form == "stop":
        return f"stop takes only fadeout, e.g. stop {value or 'music'} fadeout 2.0."
    if form == "stop_file":
        return (f"stop {value} stops whatever {value} is playing, so it doesn't take a file. "
                "Only stop sound can name one.")
    if form == "voice":
        return "voice takes only the file. Voice volume is voice_volume in config.toml."
    return "crossfade is not available in this engine version. Use fadeout and fadein."


def _e149(option: str) -> str:
    if option == "volume":
        return "volume needs a percentage after it, e.g. volume 50."
    if option == "from":
        return "from needs a time in seconds or current, e.g. from 12.5."
    return f"{option} needs a number of seconds after it, e.g. {option} 2.0."


def _e150(form: str, option: str, written: str) -> str:
    """``form`` "range" (a number out of range, as written), "units" (a number with
    letters), or "other" (anything else, shown in quotes)."""
    if option == "from":
        if form == "range":
            return "from takes seconds from 0 to 3600, or current."
        head = "from takes seconds, e.g. from 90"
    else:
        head = f"{option} takes seconds from 0 to 60, e.g. {option} 2.0"
    if form == "range":
        return f"{head}, but this has {show(written)}."
    text = f'{head}, but this has "{show(written)}".'
    return f"{text} Numbers have no units." if form == "units" else text


def _e151(form: str, shown: str) -> str:
    """``("range", shown)``: not a whole number from 0 to 100 (``shown`` as written, in
    quotes when it isn't a number); ``("percent", number)``: written with ``%``."""
    if form == "percent":
        return f"write volume {show(shown)}, without %."
    return ("volume takes a whole number from 0 to 100 (a percentage), e.g. volume 50 for half, "
            f"but this has {show(shown)}.")


def _w20(form: str = "none") -> str:
    """``form``: what follows the voice in its block: "none" (no line: the block ends, or
    jump, call, return, …), "voice", "if", or "menu"."""
    if form == "voice":
        return ("this voice is followed by another voice before any line, so it never plays. "
                "Remove one of them.")
    if form == "if":
        return "voice goes directly above a line, not above an if. Put a voice inside each branch."
    if form == "menu":
        # F08 02 §5.1 ("menu the same") and AC-F07-01: the if form with "menu".
        return ("voice goes directly above a line, not above a menu. Put a voice inside each "
                "branch.")
    return ("this voice has no line of dialogue or narration below it, so it never plays. Put "
            "voice directly above the line it voices.")


# --- F07 (01-design.md §5.3) -------------------------------------------------------------------

def _e174(form: int = 3) -> str:
    """``form`` 1: a question line after the choices; 2: text that looks like a choice but
    has no ``:``; 3: anything else directly in a menu (a second question line included)."""
    if form == 1:
        return ("the question goes on the first line of the menu, before the choices. Move "
                "this line up, or indent it inside a choice.")
    if form == 2:
        return 'this looks like a choice but has no : at the end. Write "Go left":.'
    return ("only choices can go directly in a menu, after one optional question line. Indent "
            "this line inside a choice, or move it above menu:.")


# F51 timed choices (01 §5, final texts): E368 (menu.py, the header), E369 (menu.py, the
# marking; 07 I-3: form 1 at the marked choice, form 2 at the menu, form 3 at the second
# marked choice), E370 (menu.py, the timeout choice's if), W257 (checks.py step 6f, dev).

def _e368(form: int = 1, found: str = "five") -> str:
    """``form`` 1: ``menu time:``; 2: not a number from 1 to 60 (``found``: the text as
    written, cut to 30 characters); 3: something after the number (``found``: the number)."""
    if form == 2:
        return (f"menu time takes a number of seconds from 1 to 60, but found {show(found)}. "
                "Write e.g. menu time 5:")
    if form == 3:
        return (f"menu time {show(found)} takes nothing else on its line. Put the question "
                'on the first line inside the menu, e.g. hana "Where to?"')
    return "menu time needs a number of seconds after it, e.g. menu time 5:"


def _e369(form: int = 2, count: int = 2) -> str:
    """``form`` 1: ``timeout`` in an untimed menu; 2: a timed menu with no ``timeout``
    choice; 3: ``count`` choices marked ``timeout``."""
    if form == 1:
        return ("this choice is marked timeout, but its menu has no time limit. Write menu "
                "time 5: to give the player 5 seconds, or remove timeout.")
    if form == 3:
        return (f"this menu has {count} choices marked timeout, but time running out picks "
                "only one. Remove timeout from all but one.")
    return ("this menu has a time limit but no choice marked timeout, so nothing could "
            "happen when time runs out. Write timeout after one choice's text, e.g. "
            '"Say nothing" timeout:')


# F59 checks on choices (SPEC §4): E408 (choicecheck.parse_check, the choice line), E409
# (choicecheck.parse_check_block, the lines under it). An unknown meter is F22's E233.

_TIER_WORDS = "trivial, easy, medium, hard, heroic, legendary or impossible"


def _e408(form: str = "empty", *args: object) -> str:
    """``empty``; ``meter`` (found); ``missing`` (meter); ``bad`` (found); ``left`` (the
    check as written, found); ``retry``."""
    if form == "meter":
        return (f"check takes a meter name first, then a difficulty, but found "
                f"{show(str(args[0]))}. Write e.g. check logic medium")
    if form == "missing":
        return (f"check {show(str(args[0]))} needs a difficulty after the meter: a number "
                f"from 1 to 99, or {_TIER_WORDS}.")
    if form == "bad":
        return (f"check takes a difficulty from 1 to 99 or a word ({_TIER_WORDS}), but found "
                f"{show(str(args[0]))}.")
    if form == "left":
        return (f"check {show(str(args[0]))} takes nothing else before the : (an if may "
                f"follow it), but found {show(str(args[1]))}.")
    if form == "retry":
        return ("checks can't be retried yet: each check is tried once per playthrough. "
                "Remove retry.")
    return ('check needs a meter and a difficulty, e.g. "Pick the lock" check logic medium:')


def _e409(form: str = "missing", word: str = "failure") -> str:
    """``other``: a line that isn't ``success:``/``failure:``; ``twice`` (word); ``order``;
    ``missing`` (word)."""
    if form == "other":
        return ("a choice with a check holds only success: and failure:, each with its own "
                "lines. Indent this line under one of them.")
    if form == "twice":
        return f"this choice already has {word}:. Put all its lines under the first one."
    if form == "order":
        return "write success: first, then failure:, under a choice with a check."
    return (f"this choice has a check but no {word}: under it. Add {word}: with what happens "
            "then; to just go on, write $ pass under it.")


def _w257(seconds: str = "3", chars: int = 112, read: int = 8) -> str:
    """``seconds``: the time as written; ``chars``: the choices' shown characters;
    ``read``: ``ceil(chars / 15)``."""
    return (f"this menu gives the player {show(seconds)} seconds, but its choices are "
            f"{chars} characters long, about {read} seconds of reading. Raise the time, e.g. "
            f"menu time {read}:, or shorten the choices.")


def _w47(lines: int = 2, size: int = 28) -> str:
    """A choice that needs ``lines`` lines at text size ``size`` (dev launches)."""
    if lines <= 2:
        return (f"this choice needs {lines} lines at text size {size}. Choices are easiest to "
                "read on one line, about 50 characters.")
    return (f"this choice needs {lines} lines at text size {size}, but a choice shows at most "
            '2, so the end is cut with "…". Shorten it.')


def _w48(key: str = "pick_sound", ref: str = "pick.ogg", suggestion: str | None = None) -> str:
    """A ``[theme.choice]`` sound token naming a file that doesn't exist (relative to
    ``audio/``, 07 I-4 O1)."""
    text = (f"config.toml: [theme.choice] {key} \"{show(ref)}\" doesn't exist, so no sound "
            "plays.")
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text


def _w23(file: str = "bgm/theme.m4a", ext: str = ".m4a") -> str:
    """``ext`` is the file's lower-cased extension (``audio.suffix``)."""
    head = f'"{show(file)}"'
    kind = _W23_KINDS.get(ext)
    if kind is not None:
        return f"{head} is {kind}, which the engine can't play, so it will be silent. {_AUDIO_FIX}"
    if ext in _MIDI:
        return (f"{head} is a MIDI file, which holds notes rather than sound, so it will be "
                "silent. Export the track as .ogg from your music program.")
    return (f"{head} isn't a format the engine plays (.ogg, .opus, .flac, .mp3, .wav), so it "
            f"will be silent. {_AUDIO_FIX}")


def _w24(files: Sequence[str] = ("bgm/festival.mp3",), total: int | None = None) -> str:
    """``files``: the first looping MP3 files in order of first use (at most 2 are shown);
    ``total``: how many there are (``len(files)`` when None)."""
    count = len(files) if total is None else total
    shown = [show(f) for f in files[:2]]
    if count == 1:
        return (f"1 music file loops but is MP3: {shown[0]}. MP3 adds a short silence each time "
                "a track loops; convert it to .ogg for a seamless loop.")
    if count == 2:
        listed = f"{shown[0]} and {shown[1]}"
    else:
        listed = f"{shown[0]}, {shown[1]}, and {count - 2:,} more"
    return (f"{count:,} music files loop but are MP3: {listed}. MP3 adds a short silence each "
            "time a track loops; convert them to .ogg for seamless loops.")


# --- F12 persistent data (F12 01-design.md §5.4; drafts marked G…/O… await narrative) -------

_PERSIST_SAVED = "because persistent data is saved as plain values"
_PERSIST_KIND_ADVICE = {
    "a set": "Use a list instead, e.g. [].",
    "a tuple": "Use a list instead, e.g. [1, 2] rather than (1, 2).",   # drafted
}
_PERSIST_PLAIN = ("Persistent data can hold None, True, False, numbers, text, lists, and "
                  "dictionaries.")                                       # drafted


def persist_example(name: str) -> str:
    """A name without its leading ``_`` for E182's and E184's "Use a name such as" (a
    name that would still not be one becomes ``flag``)."""
    stripped = name.lstrip("_")
    return stripped if stripped.isidentifier() else "flag"


def megabytes(size: int) -> str:
    """E183's size: MiB with one decimal, rounded half up, and never "1.0" (07 I-4 O3)."""
    tenths = (size * 20 + 1_048_576) // (2 * 1_048_576)
    return f"{max(tenths, 11) // 10}.{max(tenths, 11) % 10}"


def _e180(name: str, suggestion: str | None = None, suffix: str = "") -> str:
    """No stored value and no default (SR-F12-03). ``suggestion`` is drawn from the defaults
    and stored names (shown through ``_did_you_mean``, SEC-F12-09d)."""
    shown = show_name(name)
    head = f"persistent.{shown} has no value yet{suffix}."
    if suggestion is not None and suggestion != name:
        return f"{head} {_did_you_mean(suggestion, name)}"
    return (f"{head} Give it a starting value with default persistent.{shown} = False at the "
            "top level of a file.")


def _e181(reason: str, subject: str, kind: str = "", detail: str = "", suffix: str = "") -> str:
    """A value persistent data can't hold. ``reason`` is one of ``values.py``'s Unsaveable
    reasons; ``subject`` is ``persistent.bag`` or the path inside it
    (``persistent.bag["key"][2]``); ``kind`` the SR-F03-33 words; ``detail`` the key (key).
    The kind form for a set is design §5.4's; the others are drafted (G13)."""
    subject = show(subject)
    if reason == "kind":
        advice = _PERSIST_KIND_ADVICE.get(kind, _PERSIST_PLAIN)
        return f"{subject} can't hold {kind}, {_PERSIST_SAVED}{suffix}. {advice}"
    if reason == "key":
        shown = f" ({show(detail)})" if detail else ""
        example = f'Use text keys, e.g. "{show(detail)}".' if detail else "Use text keys."
        return (f"{subject} can't hold a dictionary with a key that isn't text{shown}, "
                f"{_PERSIST_SAVED}{suffix}. {example}")
    what = {"nan": '"not a number" (nan)', "inf": "infinity (inf)",
            "big_int": "a whole number with more than 4,300 digits"}.get(reason)
    if what is not None:
        return (f"{subject} can't hold {what}, {_PERSIST_SAVED}{suffix}. Check the calculation "
                "that set it.")
    return (f"{subject} can't hold lists or dictionaries nested more than 100 levels deep, or "
            f"one that contains itself, {_PERSIST_SAVED}{suffix}. Keep the data flatter.")


def _e182(form: str, name: str = "_clear", value: str = "", suggestion: str | None = None,
          suffix: str = "") -> str:
    """Engine names (SR-F12-02, 08). ``form``: ``set`` (a ``_`` name set or deleted),
    ``read`` (a ``_`` name read; ``suggestion`` from the engine's names), ``progress``
    (``value`` as written, ``short_value``), ``call`` (``_clear`` called another way;
    drafted) or ``name`` (``setattr`` with a name that can't be one; 07 I-4 O1, drafted)."""
    shown = show_name(name)
    if form == "set":
        return (f"persistent names starting with _ belong to the engine, so persistent.{shown} "
                f'can\'t be set{suffix}. Use a name such as "{show(persist_example(name))}".')
    if form == "read":
        head = f'persistent has no "{shown}"{suffix}.'
        if suggestion is not None:
            return f"{head} {_did_you_mean(suggestion, name)}"
        return (f"{head} Names starting with _ belong to the engine, and _clear is the only "
                "one, e.g. persistent._clear().")
    if form == "progress":
        return (f"persistent._clear takes progress=True or progress=False, but this has "
                f"{show(value)}{suffix}.")
    if form == "call":
        return (f"persistent._clear takes only progress=True or progress=False{suffix}, e.g. "
                "persistent._clear(progress=True).")
    return (f'"{shown}" can\'t be a persistent name{suffix}. Use letters, digits, and _ (at '
            "most 255 characters, not starting with a digit or _), e.g. "
            "persistent.seen_intro.")


def _e183(form: str, size: int, suffix: str = "", limit: int = 10_000) -> str:
    """Over a cap (PR-F12-15). ``bytes``: ``size`` is the values object's size; ``names``:
    the name count, over ``limit``."""
    if form == "bytes":
        return (f"persistent data is now {megabytes(size)} MB, over the 1 MB limit, so it "
                f"can't be saved{suffix}. Store flags and counts rather than long text or big "
                "lists.")
    return (f"persistent data now has {size:,} names, over the {limit:,} limit{suffix}. Keep "
            "related values in one list or dictionary.")


def _e184(form: str, name: str, first: Place | None = None) -> str:
    """A bad ``default persistent.…`` (load). ``dotted``: ``name`` is the target as written;
    ``engine``: the ``_`` name; ``duplicate``: the name and its first default."""
    if form == "dotted":
        return (f'default {show(name)} sets one name after "persistent.", e.g. default '
                "persistent.seen_intro = False.")
    if form == "engine":
        return (f"default persistent.{show_name(name)}: names starting with _ belong to the "
                f'engine. Use a name such as "{show(persist_example(name))}".')
    assert first is not None
    return (f"persistent.{show_name(name)} already has a default at {_place(first)}. "
            "Keep one.")


def _e185(define: str, attr: str = "", value: str | None = None) -> str:
    """A define reads ``persistent`` (after the ``define X couldn't be set: `` prefix).
    ``value`` is the define's value as written (one line, ``echo``-sized), else None (G13:
    the example uses the define's own name and value; drafted without one)."""
    reads = f"persistent.{show_name(attr)}" if attr else "persistent"
    head = (f"it reads {reads}, but define values are set once at launch and would miss "
            "changes made during play.")
    if value:
        return f"{head} Use a lambda, e.g. define {show_name(define)} = lambda: {show(value)}."
    return f"{head} Use a lambda, so the value is worked out each time it is used."


def _w56(name: str, suggestion: str | None = None) -> str:
    """A ``persistent.<name>`` read that nothing sets, deletes, or declares (dev launch)."""
    shown = show_name(name)
    head = f"persistent.{shown} is read here but never set or given a default."
    if suggestion is not None and suggestion != name:
        return f"{head} {_did_you_mean(suggestion, name)}"
    return (f"{head} Give it a starting value with default persistent.{shown} = False at the "
            "top level of a file.")                                      # drafted


# --- F09 transitions and effects (F09 01-design.md §5.6; 07 I-8, I-9) -------------------------
# Load E192–E198 (engine/script/effects.py, checks.py), the constructors' E199, and the launch
# E190, E191, E194 (launch form), W60 (engine/runtime/transitions.py). Forms 01 leaves open
# are drafted from the nearest given form (I-9): E193 for a color name it knows, E194's "two
# colors" and launch forms, E195–E197's repeated forms, E199's seconds/reverse/path/type/color
# forms, and W60's no-suggestion form.

TRANSITION_LIST_MAX = 10           # E190's list: the define names shown (07 I-9)
_TRANSITION_TAKES = "with takes a transition name, then a length and, for fade, a color."
# E193: a hex example for a color name an author may write (else the design's own example).
_COLOR_EXAMPLES = {"pink": "#ffc0cb", "blue": "#0000ff", "green": "#008000",
                   "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
                   "gray": "#808080", "grey": "#808080", "gold": "#ffd700",
                   "silver": "#c0c0c0", "brown": "#a52a2a", "cyan": "#00ffff",
                   "magenta": "#ff00ff", "violet": "#ee82ee"}
_KIND_ARTICLES = {"dissolve": "a dissolve", "fade": "a fade", "mask": "a Mask"}


def _e190(name: str = "disolve", suggestion: str | None = None, defined: Sequence[str] = (),
          more: int = 0) -> str:
    """Unknown transition: the did-you-mean, else the list of every transition (built-ins in
    fixed order, then up to ``TRANSITION_LIST_MAX`` define names in code-point order, and
    ``more`` not shown)."""
    head = f'there is no transition "{show(name)}".'
    if suggestion is not None:
        return f'{head} Did you mean "{show(suggestion)}"?'
    if defined:
        names = ", ".join(show(n) for n in defined)
        if more:
            names += f", …and {more:,} more transition{'' if more == 1 else 's'}"
    else:
        names = "none yet"
    return (f"{head} The transitions are cut, dissolve, fade, and the ones this game defines: "
            f"{names}.")


def _e191(name: str = "hana", kind: str = "a Character") -> str:
    return (f"with {show(name)}: {show(name)} is {kind}, not a transition. Use cut, dissolve, "
            "or fade, or define one, e.g. define slow = Dissolve(1.5).")


def _e192(form: str = "range", name: str = "dissolve", written: str = "90") -> str:
    """``range``: a length outside 0–30 (``name`` the transition); ``units``: a length with a
    unit (``written`` the whole word, ``name`` its number); ``dot``: a length written
    ``.5``."""
    if form == "units":
        return f"lengths have no units: write {show(name)}, not {show(written)}."
    if form == "dot":
        return f"write {show(written.replace('.', '0.', 1))}, not {show(written)}."
    return (f"with {show(name)} takes a length from 0 to 30 seconds, but this has "
            f"{show(written)}.")


def _e193(form: str = "hex", text: str = "#e0505") -> str:
    """A quoted text that isn't a color: ``hex`` (it starts with #) or ``name``. ``text`` is
    the text inside the quotes."""
    if form == "hex":
        return (f'"{show(text)}" isn\'t a color. Write "#" and six digits or letters a to f in '
                'quotes, e.g. "#ffe08a", or use white, black, or red.')
    example = _COLOR_EXAMPLES.get(text.strip().lower(), "#ffe08a")
    return (f'"{show(text)}" isn\'t a color here. Use white, black, red, or a color in quotes '
            f'such as "{example}".')


def _e194(form: str = "cut", *args: object) -> str:
    """``cut``; ``color`` (name): a color on a built-in that isn't a fade; ``twice`` (name,
    "lengths" | "colors"); ``left`` (leftover, name); ``launch`` (name, kind): a define of
    that kind takes no color (launch)."""
    if form == "cut":
        return "cut takes no length or color."
    if form == "color":
        return (f"{show(str(args[0]))} takes a length but no color; only fade goes through a "
                "color.")
    if form == "twice":
        return f"with {show(str(args[0]))} has two {args[1]}; give one."
    if form == "launch":
        name, kind = str(args[0]), str(args[1])
        article = _KIND_ARTICLES.get(kind, f"a {kind}")
        return (f"with {show(name)}: {show(name)} is {article}, so it takes a length but no "
                "color; only fade goes through a color.")
    leftover, name = args
    return (f'this line has "{show(str(leftover))}" left over after with {show(str(name))}. '
            f"{_TRANSITION_TAKES}")


def _e195(form: str = "bad", written: str = "huge", quoted: bool = True) -> str:
    """``bad``: a word or value shake doesn't take; ``length``: a length outside 0.1–10;
    ``twice`` (``written`` = "sizes" | "directions" | "lengths")."""
    if form == "twice":
        return f"shake has two {written}; give one."
    if form == "length":
        return ("shake takes a length from 0.1 to 10 seconds, but this has "
                f"{_has(written, quoted)}.")
    return ("shake takes small, medium, or large, horizontal or vertical, and a length from "
            f"0.1 to 10 seconds, but this has {_has(written, quoted)}.")


def _e196(form: str = "bad", written: str = "5", quoted: bool = False) -> str:
    """``bad``: a word, value, or length flash doesn't take; ``twice`` ("colors" |
    "lengths")."""
    if form == "twice":
        return f"flash has two {written}; give one."
    return ("flash takes a color and a length from 0.1 to 2 seconds, but this has "
            f"{_has(written, quoted)}.")


def _e197(form: str = "bad", written: str = "45", quoted: bool = False) -> str:
    """``bad``: anything but one length from 0.1 to 30; ``twice``: two lengths."""
    if form == "twice":
        return "pause has two lengths; give one."
    return ("pause takes a length from 0.1 to 30 seconds, or nothing to wait for a click, but "
            f"this has {_has(written, quoted)}.")


def _e198(name: str = "dissolve") -> str:
    return (f"{show(name)} is a built-in transition, so define can't use that name. Pick "
            f"another, e.g. {show(name)}_slow.")


def _e199(form: str = "file", *args: object) -> str:
    """A constructor's argument (SR-F09-07). Values come already shown (``transitions.py``):
    ``seconds`` (constructor, value), ``file``, ``soft`` (value), ``reverse`` (value),
    ``path`` (file, reason or None for outside the game folder), ``type`` (file), ``color``
    (value)."""
    if form == "seconds":
        return f"{args[0]} takes seconds from 0 to 30, but this has {args[1]}."
    if form == "file":
        return 'Mask needs an image file in quotes, e.g. Mask("masks/iris.png", 1.0).'
    if form == "soft":
        return f"Mask's soft takes a number from 0 to 0.5, but this has {args[0]}."
    if form == "reverse":
        return f"Mask's reverse takes True or False, but this has {args[0]}."
    if form == "path":
        file, reason = str(args[0]), args[1]
        if reason is not None:
            return f'Mask can\'t use "{show(file)}": {reason}.'
        return (f'Mask can\'t use "{show(file)}": paths start in the game folder and must stay '
                'inside it, using forward slashes, e.g. "masks/iris.png".')
    if form == "type":
        return (f'Mask needs a PNG, JPEG, or WebP image, but "{show(str(args[0]))}" isn\'t one. '
                "Convert it to .png.")
    return ("Fade's color takes white, black, red, or a color in quotes such as "
            f'"#ffe08a", but this has {args[0]}.')


def _w60(file: str = "masks/iris.png", name: str = "lantern",
         suggestion: str | None = None) -> str:
    text = (f'Mask uses "{show(file)}", which doesn\'t exist, so {show(name)} plays as a '
            "dissolve.")
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text


# W61 and W62 (06 AC-F09-36, AC-F09-30; 07 I-9): the presentation logs them with the statement's
# location in front, once per statement (``render/effects.py``, ``render/stage.py``, through
# ``runtime/transitions.py``'s ``flash_refused_text``, ``fade_refused_text``, and
# ``transition_failed_text``). W62's built-in form only (no code transitions before F28).
_FLASH_LIMIT_REASON = ("because the game shows at most 3 flashes a second to protect players "
                       "who are sensitive to flashing.")


def _w61(form: str = "flash") -> str:
    """``flash``: the flash was not drawn; ``fade``: a fade under 1 s played as a dissolve."""
    if form == "fade":
        return f"the fade from this line played as a dissolve, {_FLASH_LIMIT_REASON}"
    return f"the flash from this line wasn't shown, {_FLASH_LIMIT_REASON}"


def _w62(name: str = "lantern", error_type: str = "MemoryError") -> str:
    shown = echo(name, VALUE_ECHO_MAX_CHARS)
    return (f"the transition \"{shown}\" couldn't be drawn ({echo(error_type, 40)}), so the "
            f"picture changed instantly. {shown} plays as a cut for the rest of this run.")


# --- F28 glitch effects (01-design.md §5.3; 04 §5.1, §12; 07 I-14) ---------------------------
# Load E294 (engine/script/glitch.py); the presentation's W182 and W183 and the dev run
# warning W184, which F28 s3–s5 log through runtime/glitch.py. The forms 01 leaves open are
# drafts for the narrative designer (07 I-14): ``twice`` with lengths, ``onoff``, ``left``
# after ``effect off``, W182's ``with glitch`` form, W184's longer lists, and D5's ``dot`` and
# D7's W183 as 04 drafts them.

_GLITCH_TAKES = "effect takes a glitch, then a size and a length, on, or off."


def _seconds_text(value: float) -> str:
    return f"{value:g}"


def _e294(form: str = "kind", *args: object) -> str:
    """``kind`` (written, suggestion or None, the table's kind words); ``hint`` (written):
    a text-corruption word; ``empty`` (kind words); ``tag``: jitter without a sprite;
    ``notag`` (kind, written); ``length`` (subject, written); ``units`` (number, written);
    ``dot`` (written); ``twice`` (subject, "sizes" | "lengths"); ``both``, ``off_args``,
    ``onoff`` (subject); ``left`` (leftover, subject or None after ``effect off``). A subject
    is the kind, or ``jitter <tag>``."""
    if form == "kind":
        written, suggestion, kinds = (args + ("tare", "tear", GLITCH_KINDS)[len(args):])[:3]
        head = f'there is no glitch effect "{show(str(written))}".'
        if suggestion is not None:
            return f'{head} Did you mean "{show(str(suggestion))}"?'
        return f"{head} The effects are {_and_list(list(kinds))}."     # type: ignore[arg-type]
    if form == "hint":
        written = str(args[0]) if args else "corrupt"
        return (f'there is no glitch effect "{show(written)}". To corrupt a line\'s text, write '
                "{glitch}…{/glitch} inside it.")
    if form == "empty":
        kinds = list(args[0]) if args else list(GLITCH_KINDS)          # type: ignore[call-overload]
        return f"effect needs a glitch: {_join_or(kinds)}, or off to stop them all."
    if form == "tag":
        return "effect jitter needs the sprite to jitter, e.g. effect jitter hana."
    if form == "notag":
        kind, written = (args + ("static", "hana")[len(args):])[:2]
        return (f"effect {kind} doesn't take a sprite; only jitter does, but this has "
                f'"{show(str(written))}".')
    if form == "length":
        subject, written = (args + ("tear", "45")[len(args):])[:2]
        low, high = GLITCH_SECONDS_RANGE
        return (f"effect {show(str(subject))} takes a length from {_seconds_text(low)} to "
                f"{_seconds_text(high)} seconds, but this has {show(str(written))}.")
    if form == "units":
        number, written = (args + ("0.5", "0.5s")[len(args):])[:2]
        return _e192("units", str(number), str(written))
    if form == "dot":
        return _e192("dot", "", str(args[0]) if args else ".5")
    subject = show(str(args[0])) if args and args[0] is not None else "tear"
    if form == "twice":
        what = str(args[1]) if len(args) > 1 else "sizes"
        return f"effect {subject} has two {what}; give one."
    if form == "both":
        return (f"effect {subject} has both on and a length. on lasts until effect {subject} "
                "off, so give one.")
    if form == "off_args":
        return f"effect {subject} off takes no size or length."
    if form == "onoff":
        return f"effect {subject} has both on and off; give one."
    # left (leftover, subject); subject None: after a bare ``effect off``.
    leftover = str(args[0]) if args else "slowly"
    after = args[1] if len(args) > 1 else "tear"
    if after is None:
        return (f'this line has "{show(leftover)}" left over after effect off. effect off takes '
                "nothing after it.")
    return (f'this line has "{show(leftover)}" left over after effect {show(str(after))}. '
            f"{_GLITCH_TAKES}")


def _w182(form: str = "burst") -> str:
    """``burst``: the glitch burst was not drawn; ``transition``: a ``with glitch`` played as
    a dissolve (07 I-3; drafted)."""
    if form == "transition":
        return f"the glitch transition from this line played as a dissolve, {_FLASH_LIMIT_REASON}"
    return f"the glitch from this line wasn't shown, {_FLASH_LIMIT_REASON}"


def _w183(kind: str = "static", error_type: str = "MemoryError") -> str:
    """A kind failed to draw and is off for the run (04 §12, D7 draft): names the error's
    type on purpose, as W62 does."""
    return (f'the glitch effect "{echo(kind, 40)}" couldn\'t be drawn '
            f"({echo(error_type, 40)}), so it is off for the rest of this run.")


def _w184(tag: str = "daichi", on_stage: Sequence[str] = ("hana", "monika")) -> str:
    """Dev run: ``effect jitter <tag>`` with no such sprite on the stage. ``on_stage`` is
    the stage's tags in draw order; at most ``SCRIPT_MESSAGE_LIST_ITEMS`` are named."""
    shown = [show_name(t) for t in on_stage[:SCRIPT_MESSAGE_LIST_ITEMS]]
    extra = len(on_stage) - len(shown)
    if not shown:
        listed = "no sprites"
    elif extra:
        listed = ", ".join(shown) + f", and {_more(extra, 'sprite', 'sprites')}"
    else:
        listed = ", ".join(shown)
    name = show_name(tag)
    return (f"effect jitter {name}: no sprite tagged {name} is on the stage, so nothing "
            f"jitters. On the stage: {listed}.")


# --- F30 fourth-wall tricks (01-design.md §5.4; 04 §5, §6.8, §11) -----------------------------
# Load E300 and E301 (engine/script/fourthwall.py; E301's tag form texttags.py), E302
# (chapter.py; its name form at launch, runtime/character.py); W188 (run, app), W189 and W190
# (dev launch, app/text_check.py) with their summary lines, which F30 s5 logs. W188 names only
# the fallback word, never a name read (SR-F30-04). The forms 01 leaves open are drafts for
# the narrative designer: E300's ``left`` after ``off``, E301's ``tag`` for a closing tag,
# E163's ``{username=}``, and the two summary lines.

def _e300(form: str = "needs", *args: object) -> str:
    """``needs``; ``long`` (count); ``tags``; ``left`` (the first leftover chunk as
    written)."""
    if form == "long":
        count = int(args[0]) if args else 140                    # type: ignore[call-overload]
        return (f"the window title can be at most {WINDOW_TITLE_MAX:,} characters, but this one "
                f"has {count:,}.")
    if form == "tags":
        return ("the window title is plain text, so it can't hold {username} or other tags. To "
                "show a {, write {{.")
    if form == "left":
        leftover = str(args[0]) if args else "slowly"
        return (f'effect window_title takes a title or off, but this line has "{show(leftover)}" '
                "left over.")
    return ('effect window_title needs the title in quotes, e.g. effect window_title "Hello?", '
            "or off to bring back the game's own title.")


def _e301(form: str = "left", *args: object) -> str:
    """``left`` (the leftover chunk as written); ``long`` (count); ``tag`` (the tag's name)."""
    if form == "long":
        count = int(args[0]) if args else 2400                   # type: ignore[call-overload]
        return (f"the fake crash message can be at most {CRASH_MESSAGE_MAX:,} characters, but "
                f"this one has {count:,}.")
    if form == "tag":
        tag = str(args[0]) if args else "b"
        return (f"a fake crash message can hold only {{username}} and {{var=…}}, but this one "
                f"has {{{show(tag)}}}.")
    leftover = str(args[0]) if args else "again"
    return (f'effect crash takes one message in quotes, but this line has "{show(leftover)}" '
            "left over.")


def _username_only(place: str) -> str:
    """E302's text, also E175's and E252's ``username`` forms: ``place`` is where it was
    found (``a character name``, ``a title card``, ``a choice``, ``a codex entry``)."""
    return ("{username} shows the player's computer user name, so it can be used only in "
            f"dialogue, narration, and effect crash messages, not in {place}.")


def _e302(form: str = "name") -> str:
    """``name`` (a ``Character`` name, launch) or ``title_card`` (a chapter or ending)."""
    return _username_only("a title card" if form == "title_card" else "a character name")


def _w188(fallback: str = "friend") -> str:
    return (f"the computer's user name couldn't be read, so {{username}} shows "
            f'"{show(fallback)}" this session.')


def _w189(fallback: str = "friend") -> str:
    return (f"this line uses {{username}}, but [meta] username is off in config.toml, so every "
            f'player sees "{show(fallback)}". Set username = true under [meta] to let players '
            "choose.")


_W190 = ("this Python code reads the computer's user name or environment. Anything it stores "
         "goes into saves, history, and persistent data that players share. To show the "
         "player's name, use {username} in text instead.")


# --- F32 dynamic UI (01-design.md §5.2; 04 §5.1, §12; 07 G5) ----------------------------------
# Load E319, E320, E321 (engine/script/ui.py); W204, W206, W207 (app/looks.py, area ui, F32 s4)
# and W205 (the restore's warning path, F32 s3). Drafts for the narrative designer: E319's
# ``left`` forms other than ``saving on`` (04 §12, G5), E320 without a did-you-mean, and W207.

_UI_LEFT = {                         # E319 ``left``: what each form takes (04 §12, G5)
    "style": "ui style takes one style name or off",
    "saving off": "ui saving off takes at most one reason in quotes",
    "loading off": "ui loading off takes at most one reason in quotes",
    "saving on": "ui saving on takes nothing more",
    "loading on": "ui loading on takes nothing more",
    "delete": "ui delete saves takes nothing more",
}


def _e319(form: str = "needs", *args: object) -> str:
    """``needs``; ``unknown`` (the word as written, the suggestion or None); ``style_needs``;
    ``block_needs`` (``saving`` or ``loading``); ``delete_needs``; ``left`` (a ``_UI_LEFT``
    key, the first left-over item as written); ``top``."""
    if form == "unknown":
        word = str(args[0]) if args else "colour"
        hint = args[1] if len(args) > 1 else None
        text = f'ui can change style, saving, loading, or delete saves, but not "{show(word)}".'
        if hint is not None:
            text += f' Did you mean "{show(str(hint))}"?'
        return text
    if form == "style_needs":
        return "ui style needs a style name from config.toml, or off, e.g. ui style ashes."
    if form == "block_needs":
        word = str(args[0]) if args else "saving"
        return (f'ui {word} needs off or on, e.g. ui {word} off "Not here." or ui {word} on.')
    if form == "delete_needs":
        return "ui delete needs the word saves: ui delete saves."
    if form == "left":
        which = str(args[0]) if args else "saving on"
        leftover = str(args[1]) if len(args) > 1 else "now"
        return f'{_UI_LEFT[which]}, but this line has "{show(leftover)}" left over.'
    if form == "top":
        return "ui goes inside a label, because it runs when the story reaches it."
    return ("ui needs what to change, e.g. ui style ashes, ui saving off, ui loading on, or "
            "ui delete saves.")


def _e320(name: str = "ashs", suggestion: str | None = "ashes") -> str:
    shown = show(name)
    text = f'there is no UI style "{shown}" in config.toml.'
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text + f" Add a [style.{shown}] table, or use ui style off."


def _e321(form: str = "empty", count: int = 240) -> str:
    """``empty``; ``long`` (the reason's length in code points); ``tags``."""
    if form == "long":
        return (f"the reason can be at most {UI_REASON_MAX:,} characters, but this one has "
                f"{count:,}.")
    if form == "tags":
        return ("the reason is plain text, so it can't hold {b} or other tags. To show a {, "
                "write {{.")
    return ("the reason needs at least one character, or leave it out to use the game's own "
            "words.")


def _w204(kind: str = "text") -> str:
    """``kind`` is the stored value's kind in words (``text``, ``true or false``, ``a decimal
    number``, ``a list``, …); the value itself is never shown (PR-F12-16)."""
    return (f"persistent.playthrough isn't a whole number (it holds {kind}), so the title uses "
            "playthrough 0's look.")


def _w205(name: str = "ashes") -> str:
    return (f'this save uses the UI style "{show(name)}", which config.toml no longer has, so '
            "the normal look is used.")


def _w206(name: str = "ashes") -> str:
    return f"config.toml: [style.{show(name)}] isn't used by any ui style line."


_W207_PROBLEMS = {"missing": "doesn't exist", "image": "couldn't be read as an image",
                  "font": "couldn't be read as a font"}


def _w207(table: str = "style.ashes.theme.textbox", key: str = "frame_image",
          ref: str = "gui/x.png", problem: str = "missing",
          suggestion: str | None = None) -> str:
    """A look's font or image that can't be used (04 §12): ``table`` is its full table path
    (``style.ashes.theme.textbox``, ``playthrough.2.theme.title``); the ``[theme]`` table it
    falls back to drops the look's two leading parts. ``problem``: a ``_W207_PROBLEMS`` key."""
    base = table.split(".", 2)[2] if table.count(".") >= 2 else table
    text = (f'config.toml: [{table}] {key} "{show(ref)}" {_W207_PROBLEMS[problem]}, so '
            f"[{base}] {key} is used.")
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text


# --- F31 meta files (01-design.md §5.2; 04 §5.1, §5.2, §11) ------------------------------------
# Load E309–E312 and E315 (engine/script/metafiles.py's parser), E312's target forms, E313,
# and E314 (checks.py, step 12; E314 whole game); W196–W198 (run, app/metafiles.py, F31 s4)
# and W199, W200 (run, runtime/metafiles.py, F31 s3). Warnings name only META_SHOWN plus a
# listed name and fixed words: never note text, a reason from the OS, or a real path
# (SEC-F31-07). Drafts for the narrative designer (04 §11, 06 G10): E309's ``needs`` with a
# verb and ``left`` after write, E310 ``long``/``chars``, E312 ``engine`` and ``no_default``
# without a suggestion, and W198 ``folder_at_name``, ``original_missing``, ``original_large``,
# ``busy``, ``other``.

_FILE_VERBS = "write, delete, exists, or read"
_META_BASE_MAX = 32                 # metafiles.NAME_BASE_MAX (META_NAME_RE's base)
_META_NAME_RULE = ('a meta file name is in quotes: lowercase letters, digits, - or _, up to '
                   f'{_META_BASE_MAX} of them, then .chr or .txt, such as "hana.chr".')
_META_FOLDER = META_SHOWN.rstrip("/")
# E312's example target per verb (``into hana_here``, ``into answer``).
_INTO_EXAMPLE = {"exists": ('"hana.chr"', "hana_here"), "read": ('"answer.txt"', "answer")}


def _e309(form: str = "needs", *args: object) -> str:
    """``needs`` (the verb, or None for a bare ``file``); ``unknown`` (the word as written,
    the suggestion or None); ``left`` (the verb, the first left-over item as written);
    ``block``."""
    if form == "unknown":
        word = str(args[0]) if args else "delte"
        hint = args[1] if len(args) > 1 else None
        text = f'"{show(word)}" isn\'t a file word.'
        if hint is not None:
            text += " " + _did_you_mean(str(hint), word)
        return f"{text} file takes {_FILE_VERBS}."
    if form == "left":
        verb = str(args[0]) if args else "delete"
        leftover = str(args[1]) if len(args) > 1 else "now"
        takes = ("a file name and, if you like, the text in quotes" if verb == "write"
                 else "one file name")
        return f'file {verb} takes {takes}, but this line has "{show(leftover)}" left over.'
    if form == "block":
        return ("file doesn't take a block. Remove the \":\" and un-indent the lines under "
                "it.")
    verb = args[0] if args else None
    if verb in ("write", "delete"):
        return f'file {verb} needs a file name in quotes, e.g. file {verb} "hana.chr".'
    if verb in _INTO_EXAMPLE:
        file, example = _INTO_EXAMPLE[str(verb)]
        return (f"file {verb} needs a file name in quotes, e.g. file {verb} {file} into "
                f"{example}.")
    return ('file needs what to do and a file name, e.g. file delete "hana.chr". It takes '
            f"{_FILE_VERBS}.")


def _e310(form: str = "slash", name: str = "../hana.chr") -> str:
    """``variable`` (the name word as written); else a name form (04 §5.1 step 2's order):
    ``slash``, ``capitals``, ``ending``, ``reserved``, ``long``, ``chars`` with the name as
    written."""
    if form == "variable":
        return ('the file name must be written in quotes, such as "hana.chr", not a variable '
                f"like {show(name)}.")
    shown = f'"{show(name)}"'
    if form == "slash":
        what = "/" if "/" in name else "\\"
        return f"{_META_NAME_RULE} {shown} has a {what}."
    if form == "capitals":
        return f"{_META_NAME_RULE} {shown} has capital letters."
    if form == "ending":
        suffix = name[name.rfind("."):] if "." in name else ""
        if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix, re.ASCII):
            return f"{_META_NAME_RULE} {shown} ends in {suffix}."
        return f"{_META_NAME_RULE} {shown} doesn't end in .chr or .txt."
    if form == "reserved":
        return f"{_META_NAME_RULE} {shown} is a name Windows keeps for itself."
    base = name.rsplit(".", 1)[0]
    if form == "long":
        return (f"{_META_NAME_RULE} {shown} has {len(base):,} characters before the dot, but "
                f"at most {_META_BASE_MAX} are allowed.")
    if not base:
        return f"{_META_NAME_RULE} {shown} has nothing before the dot."
    if base[0] in "-_":
        return f"{_META_NAME_RULE} {shown} starts with {base[0]}."
    if "." in base:
        return f"{_META_NAME_RULE} {shown} has more than one dot."
    bad = next((c for c in base if not (c.isascii() and (c.isalnum() or c in "-_"))), base[0])
    return f'{_META_NAME_RULE} {shown} has "{show(bad)}" in it.'


def _e311(form: str = "long", name: str = "read_me.txt", arg: object = 18_200) -> str:
    """``long`` (the name, the count of code points); ``control`` (the name, the first
    control character)."""
    if form == "control":
        char = str(arg) if arg else "\x07"
        return (f'the text for "{show(name)}" has a control character ({codepoint(char[0])}). '
                "Only \\n and \\t are allowed.")
    count = int(arg) if isinstance(arg, int) else 18_200
    return (f'the text for "{show(name)}" can be at most {META_TEXT_MAX_CHARS:,} characters, '
            f"but this one has {count:,}.")


def _e312(form: str = "needs", *args: object) -> str:
    """``needs`` (the verb); ``one_name`` (the verb, the target as written); ``no_default``
    (the target, the suggestion or None); ``define`` and ``engine`` (the target)."""
    if form == "no_default":
        name = str(args[0]) if args else "hana_her"
        hint = args[1] if len(args) > 1 else None
        text = f'there is no default named "{show_name(name)}".'
        if hint is not None:
            return f"{text} {_did_you_mean(str(hint), name)}"
        return (f"{text} Add default {show_name(name)} = None at the top level of a file, or "
                "use a variable that has one.")
    if form == "define":
        name = show_name(str(args[0])) if args else "hana"
        return (f'"{name}" is set by define, so the story can\'t change it. Use a variable that '
                "has a default.")
    if form == "engine":
        name = show_name(str(args[0])) if args else "dice"
        return f'"{name}" is a name the engine uses. Use a variable that has a default.'
    verb = str(args[0]) if args else "exists"
    file, example = _INTO_EXAMPLE.get(verb, _INTO_EXAMPLE["exists"])
    if form == "one_name":
        written = str(args[1]) if len(args) > 1 else "persistent.hana"
        text = (f"into takes one story variable's name, such as into {example}, but this has "
                f'"{show(written)}".')
        if re.fullmatch(r"persistent\.\w+", written):
            return (f"{text} To keep it across playthroughs, write $ {show(written)} = "
                    f"{example} on the next line.")
        return f"{text} Use a variable that has a default."
    return (f"file {verb} needs into and a story variable, e.g. file {verb} {file} into "
            f"{example}.")


def _e313(form: str = "missing", name: str = "hana.chr", size: int = 5_452_595,
          cap: int = META_ORIGINAL_MAX_BYTES) -> str:
    """``missing`` (the name); ``large`` (the name, its size and the cap in bytes)."""
    shown = show(name)
    if form == "large":
        return (f"{META_ORIGINALS_DIR}/{shown} is {size / MB:.1f} MB, but an original can be "
                f"at most {cap / MB:g} MB.")
    return (f'file write "{shown}" copies {META_ORIGINALS_DIR}/{shown}, but there is no such '
            f"file. Add it to the {META_ORIGINALS_DIR} folder, or give the text: file write "
            f'"{shown}" "your text".')


def _e314(count: int = 33, name: str = "extra.txt", ref: str = "script/act3.vns",
          line: int = 40) -> str:
    return (f"This game uses {count:,} meta file names, but at most {META_NAMES_MAX} are "
            f'allowed. The first one over is "{show(name)}" ({show(ref)}, line {line}).')


def _e315(name: str = "hana.chr") -> str:
    shown = show(name)
    return (f'file read reads text, so it works only on .txt files, not "{shown}". To see '
            f"whether {shown} is there, use file exists.")


# W198's reasons (04 §6.4): fixed words, never the OS's text.
_W198_REASONS = {
    "full": "the disk is full",
    "permission": "no permission",
    "folder_at_name": "something that isn't a file is there",
    "original_missing": "its original in files/ is gone",
    "original_large": "its original in files/ is now over 4 MB",
    "busy": "too many file changes are still being written, so this one was skipped",
    "other": "another program may be using it",
}


def _w198(form: str = "permission", verb: str = "delete", name: str = "hana.chr") -> str:
    """One change that failed (run): ``form`` a ``_W198_REASONS`` key, ``verb`` ``write`` or
    ``delete``, ``name`` the listed name."""
    reason = _W198_REASONS.get(form, _W198_REASONS["other"])
    return f"couldn't {verb} {META_SHOWN}{show(name)}: {reason}."


_W200_REASONS = {
    "large": f"the file is over {META_READ_MAX_BYTES // KIB} KB",
    "utf8": "it isn't UTF-8 text",
    "not_file": "it is a link or not a file",
    "hard_link": "it has another name elsewhere (a hard link)",
}


def _w200(form: str = "large", name: str = "answer.txt") -> str:
    """A read that found no text (run, once per name): ``form`` a ``_W200_REASONS`` key."""
    return (f'file read "{show(name)}" found no text: '
            f"{_W200_REASONS.get(form, _W200_REASONS['not_file'])}.")


# --- F18 chapters (F18 SPEC §3; 07 I-2) ----------------------------------------------------------
# Load E220 (checks.py), E221–E223 (engine/script/chapter.py), E224 (checks.py, whole game).
# Forms the SPEC leaves open are drafts for the narrative designer: E221's count for more than
# three texts, E222's empty heading.

_COUNT_WORDS = {3: "three", 4: "four", 5: "five", 6: "six"}


def _e220(name: str = "festival", first: Place = ("script/story.vns", 12)) -> str:
    return (f'there are two chapters named "{show(name)}": here and at {_place(first)}. '
            "Give each chapter its own name.")


def _e221(form: str = "need", arg: object = None) -> str:
    """``need``: no name or no title; ``texts`` (count): more than two texts; ``left``
    (written): something left over after the title."""
    if form == "texts":
        count = int(arg) if isinstance(arg, int) else 3
        return (f"chapter has {_COUNT_WORDS.get(count, f'{count:,}')} texts; give at most a "
                "heading and a title.")
    if form == "left":
        return (f'this line has "{show(str(arg))}" left over after the chapter title. chapter '
                "takes a name, an optional heading, a title, a card length, and with, in that "
                "order.")
    return ('chapter needs a name and a title in quotes, e.g. chapter festival "The Lantern '
            'Festival".')


def _e222(form: str = "long", which: str = "title", count: int = 140, limit: int = 120) -> str:
    """``empty`` (which), ``long`` (which, count, limit), ``tags``, ``name`` (count, limit:
    07 I-2's form, ``which`` unused)."""
    if form == "empty":
        return f"the chapter {which} is empty."
    if form == "tags":
        return ('chapter text is shown as written, so it can\'t use text tags such as {b}. '
                'Write {{ for a "{".')
    if form == "name":
        which = "name"
    return f"the chapter {which} has {count:,} characters; keep it to {limit:,}."


def _e223(written: str = "45") -> str:
    return ("chapter takes a card length from 0 to 30 seconds (0 shows no card), but this has "
            f"{show(written)}.")


def _e224(count: int = 1204, limit: int = 1000) -> str:
    return f"this story has {count:,} chapters; the engine allows {limit:,}."


# --- F22 character stats (F22 SPEC §3; 07 I-2, I-10) ----------------------------------------------
# Load E230, E232 (engine/script/points.py), E231, E233–E235 (checks.py, bindings.py); run E236
# (engine/runtime/points.py), W120 (dev). Forms the SPEC leaves open are drafts for the narrative
# designer: E230's "left" form, E232's "same" form, E236's "none" form (07 I-10), and the E233
# form without a suggestion.

_METER_EXAMPLE = "sayori"


def _n(value: object) -> str:
    """A whole number with thousands commas (``5,000,000,000``); anything else as written."""
    if type(value) is int:
        return f"{value:,}"
    written = str(value)
    if re.fullmatch(r"-?[0-9]{1,15}", written):
        return f"{int(written):,}"
    return show(written)


def _e230(form: str = "need", *args: object) -> str:
    """``need``, ``change``, ``declare``, ``operator`` (op), ``word`` (word), ``long`` (count,
    limit; 07 I-2), ``left`` (written; drafted)."""
    if form == "change":
        return "points in a label changes a meter: write points sayori += 2, -= 1, or = 5."
    if form == "declare":
        return ("points at the top level declares meters, e.g. points sayori 0 to 10. To change a "
                "meter, put this line inside a label.")
    if form == "operator":
        return f"points takes +=, -=, or =, but this has {show(str(args[0]))}."
    if form == "word":
        return (f'"{show(str(args[0]))}" is a word of the points statement, so it can\'t be a '
                "meter name.")
    if form == "long":
        count, limit = args
        return f"the meter name has {count:,} characters; keep it to {limit:,}."
    if form == "left":
        return (f'this line has "{show(str(args[0]))}" left over. points takes meter names, then '
                "a range such as 0 to 10, then start and a number, in that order.")
    return ("points needs a meter name, e.g. points sayori 0 to 10 at the top level, or points "
            "sayori += 2 in a label.")


def _e231(name: str = "sayori", first: Place = ("script/story.vns", 3)) -> str:
    return (f'there are two meters named "{show(name)}": here and at {_place(first)}. '
            "Declare each meter once.")


def _e232(form: str = "backwards", *args: object) -> str:
    """``backwards`` (low, high), ``same`` (low, high; drafted), ``big`` (written), ``start``
    (start, low, high), ``whole`` (written)."""
    if form == "big":
        return (f"points go from -1,000,000,000 to 1,000,000,000, but this has "
                f"{_n(args[0])}.")
    if form == "start":
        start, low, high = args
        return f"start {_n(start)} is outside the range {_n(low)} to {_n(high)}."
    if form == "whole":
        return f"points are whole numbers, but this has {show(str(args[0]))}."
    low, high = args or (10, 0)
    if form == "same":
        return (f"the range {_n(low)} to {_n(high)} holds only one number; make the high number "
                "bigger.")
    return f"the range {_n(low)} to {_n(high)} is backwards; write the low number first."


def _e233(name: str = "sayory", suggestion: str | None = None) -> str:
    text = f'there is no meter named "{show_name(name)}".'
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, name)
    return (text + f" Declare meters at the top level, e.g. points {show_name(name)} 0 to 10.")


def _e234(name: str = "sayori") -> str:
    return (f"Python can't change points.{show_name(name)}. Use the points statement, e.g. "
            f"points {show_name(name)} = 3.")


def _e235(count: int = 240, limit: int = 200) -> str:
    return f"this story has {count:,} meters; the engine allows {limit:,}."


def _e236(form: str = "unknown", *args: object) -> str:
    """``amount`` (meter, value shown, kind words), ``unknown`` (name, suggestion), ``write``
    (example meter), ``define`` (the launch prefix is added by ``errors.py``), ``none``
    (``highest()`` with no meters; drafted, 07 I-10)."""
    if form == "amount":
        name, shown, kind = args
        return (f"the amount for points {show_name(str(name))} must be a whole number, but it is "
                f"{shown} ({kind}).")
    if form == "write":
        example = str(args[0]) if args and args[0] else _METER_EXAMPLE
        return (f"Python can't change points. Use the points statement, e.g. points "
                f"{show_name(example)} = 3.")
    if form == "define":
        return ("it reads points, which exist only once a game has started. Use a lambda or a "
                "default.")
    if form == "none":
        return ("points.highest() needs a meter, but this story declares none. Declare meters at "
                "the top level, e.g. points sayori 0 to 10.")
    if form == "no_ranks":
        return _e416(str(args[0]) if args else _METER_EXAMPLE)
    name = str(args[0]) if args else "sayory"
    suggestion = args[1] if len(args) > 1 else None
    text = f'there is no meter named "{show_name(name)}".'
    if type(suggestion) is str:
        text += " " + _did_you_mean(suggestion, name)
    return text


# F62 round 1 (specs/F62-visible-meters/SPEC.md): load E411–E415 (engine/script/points.py), E416
# and W290 (engine/script/meterranks.py, the whole-game checks); run E236's ``no_ranks`` form.

_RANKS_EXAMPLE = 'ranks "Stranger" 0 "Friend" 4 "Close" 8'


def _e411(form: str = "need", *args: object) -> str:
    """``need``; ``label`` (found); ``at`` (label); ``many`` (limit)."""
    if form == "label":
        return (f"ranks takes a label in quotes, then the number it starts at, but found "
                f"{show(str(args[0]))}. Write e.g. {_RANKS_EXAMPLE}")
    if form == "at":
        return (f'the rank "{show(str(args[0]))}" needs the number it starts at after it, e.g. '
                f'"{show(str(args[0]))}" 4')
    if form == "many":
        return f"a meter can have at most {args[0] if args else 20} ranks."
    return f"ranks needs at least one label and the number it starts at, e.g. {_RANKS_EXAMPLE}"


def _plain_text(form: str, what: str, args: tuple) -> str:
    """The plain-text forms shared by E412 (a rank label) and E415 (a notice)."""
    if form == "long":
        count, limit = args[:2] if len(args) >= 2 else (50, 40)
        return f"{what} has {count:,} characters; keep it to {limit:,}."
    if form == "newline":
        return f"{what} is one line: remove the \\n."
    if form == "tags":
        return f"{what} is plain text, without {{b}} or {{var}}. Write {{{{ to show a {{."
    return f"{what} is empty; write a few words between the quotes."


def _e412(form: str = "empty", *args: object) -> str:
    """``empty``, ``long`` (count, limit), ``newline``, ``tags``; ``twice`` (label)."""
    if form == "twice":
        return (f'two ranks are named "{show(str(args[0]))}"; give each rank its own label.')
    return _plain_text(form, "a rank label", args)


def _e413(form: str = "rising", *args: object) -> str:
    """``range`` (label, at, low, high); ``rising`` (label, at, previous label, its at)."""
    if form == "range":
        label, at, low, high = args
        return (f'the rank "{show(str(label))}" starts at {_n(at)}, outside the range '
                f"{_n(low)} to {_n(high)}.")
    label, at, before, before_at = args or ("Friend", 4, "Stranger", 4)
    return (f'the rank "{show(str(label))}" starts at {_n(at)}, but it must start higher than '
            f'"{show(str(before))}" ({_n(before_at)}). List ranks from lowest to highest.')


def _e414() -> str:
    return ('"rank" can\'t be a meter name: points.rank("hana") gives a meter\'s rank. Pick '
            "another name, e.g. standing.")


def _e415(form: str = "empty", *args: object) -> str:
    """``empty``, ``long`` (count, limit), ``newline``, ``tags``."""
    return _plain_text(form, "the notice", args)


def _e416(name: str = "sayori") -> str:
    return (f"points.rank needs a meter with ranks, but {show_name(name)} has none. Add ranks "
            f"to its points line, e.g. points {show_name(name)} 0 to 10 {_RANKS_EXAMPLE}")


def _w290(label: str = "Closee", name: str = "hana", suggestion: str | None = None,
          labels: tuple = ("Stranger", "Friend", "Close")) -> str:
    """A rank comparison that can't match: ``labels`` are the meter's ranks."""
    text = f'{show_name(name)} has no rank named "{show(label)}".'
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, label)
    shown = ", ".join(f'"{show(str(item))}"' for item in labels[:6])
    more = f" and {len(labels) - 6} more" if len(labels) > 6 else ""
    return text + f" Its ranks are {shown}{more}."


# F62 round 2 (specs/F62-visible-meters/SPEC.md "Round 2"): load E417, E418
# (engine/script/showmeter.py, parse), W291–W293 (showmeter.check_story); E233 for an unknown
# meter. E419 and W294 are spare.

def _e417(form: str = "name", word: str = "show", found: str = "hana,") -> str:
    """``name`` (what was found); ``modifier`` (the word); ``colon``."""
    example = f"{word} meter hana sanity"
    found = found if found.startswith('"') else f'"{found}"'
    if form == "modifier":
        return (f"{word} meter takes only meter names, but found {show(found)}. A meter "
                f"comes and goes on its own; write e.g. {example}")
    if form == "colon":
        return f"{word} meter takes no colon or block after it. Write e.g. {example}"
    return (f"{word} meter takes meter names separated by spaces, but found {show(found)}. "
            f"Write e.g. {example}")


def _e418(form: str = "twice", word: str = "show", arg: object = "hana") -> str:
    """``twice`` (the name); ``many`` (the limit)."""
    if form == "many":
        return (f"{word} meter can name at most {arg} meters on one line. Split it over two "
                "lines.")
    return f"{word} meter names {show_name(str(arg))} twice; name each meter once."


def _w291(name: str = "hanna", suggestion: str | None = "hana") -> str:
    text = f"[meter.{show_name(name)}] is set up, but no points line declares a meter named "            f"{show_name(name)}, so it is never used."
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, name)
    return text


def _w292(name: str = "hana", look: str = "hearts") -> str:
    return (f"{show_name(name)} is shown as {look}, which needs a range, but its points line "
            f"has none, so it is shown as a number. Give it a range, e.g. points "
            f"{show_name(name)} 0 to 10.")


def _w293(image: str = "meter hana") -> str:
    return (f'this shows the picture "{show(image)}", not the meter. A meter takes no at, as or '
            f"with: write show meter {show(image.split(' ', 1)[-1])}")


# --- F14 rollback (F14 04 §6.2; 06 D1, G3) ----------------------------------------------------
# Load E200–E203 (engine/script/rollback.py, parse) and E204 (rollback.py's attach_fixed, in the
# whole-game checks). Every text is a draft for the narrative designer (06 G3). E205–E209 are
# spare.

_ROLLBACK_WORDS = "block, off, on, or fixed"
# E204's forms for the statement after ``rollback fixed`` (the others are its statement word).
_NEXT_FORMS = {"say": "a line of dialogue", "py": "a $ line"}


def _e201(written: str = "of", suggestion: str | None = "off") -> str:
    text = f'"{show(written)}" isn\'t a rollback word.'
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return f"{text} rollback takes {_ROLLBACK_WORDS}."


def _e202(word: str = "off", rest: str = "now") -> str:
    return (f'rollback {word} takes nothing after "{word}", but this line goes on with '
            f'"{show(rest)}". Put anything else on its own line.')


def _e204(form: str = "say", line: int | None = 31) -> str:
    if form == "nothing":
        what = "nothing comes after it here"
    else:
        kind = _NEXT_FORMS.get(form)
        if kind is None:
            kind = f"{'an' if form[:1] in 'aeiou' else 'a'} {form} line"
        what = f"the next line here is {kind} (line {line})"
    # F23 A3 (F14 SPEC I-17): a minigame line is a step, like a menu.
    return (f"rollback fixed must be the line right above a menu: or a minigame line, but "
            f'{what}. Move it above the menu or minigame, or use "rollback block".')


_W90_CAUSES: dict[str, str] = {
    "position": "no longer matches the script (it was changed)",
    "scheme": "uses a different script version",
    "default": "failed while filling a default (see the error above)",
}


def _w90(label: str = "bridge", cause: str = "position") -> str:
    """F14 (04 §12): a rollback step that can't be restored; ``cause`` is ``position``,
    ``scheme``, or ``default`` (the restore's result)."""
    return (f"Rollback stopped: a step in label \"{show_name(label)}\" {_W90_CAUSES[cause]}, so "
            "it and older steps were dropped.")


def _w120(name: str = "sayori", op: str = "+=", amount: str = "5", top: bool = True,
          value: int = 10, wanted: int = 12) -> str:
    end = "top" if top else "bottom"
    return (f"points {show_name(name)} {op} {show(amount)} went past the {end} of its range, so "
            f"{show_name(name)} is {_n(value)}, not {_n(wanted)}.")


# --- F17 NVL mode (F17 01 §5.4; 06 AC-F17-02, 05, 29, 30, D3, G2; 07 §3.3, I-11) -----------------
# Load E210, E211 (engine/script/nvl.py); run W102 (engine/runtime/nvl.py, dev, once per run);
# launch W100, W101, W101s (app/text_check.py, F17 step 5). W100's white-picture, name and
# indicator forms are QA drafts (06 D3, G2). E212–E219 and W103–W109 are spare.

_NVL_ACTIONS = "on, off, or clear"
# W100's theme form: what each key colors, and the ratio it needs (06 AC-F17-30).
_W100_NEEDS: dict[str, tuple[str, str]] = {
    "text_color": ("full-screen text needs", "4.5"),
    "name.text_color": ("full-screen names need", "3"),
    "indicator.fill_color": ("the full-screen indicator needs", "3"),
}


def _e210(form: str = "unknown", written: str = "of", suggestion: str | None = "off") -> str:
    """``form``: ``needs`` (nothing after nvl), ``case`` (``written`` is the action in lower
    case), or ``unknown`` (``written`` as written, with an optional did-you-mean)."""
    if form == "needs":
        return f"nvl needs {_NVL_ACTIONS} after it, e.g. nvl on."
    if form == "case":
        return f"write nvl {show(written)} in lower case."
    text = f'nvl takes {_NVL_ACTIONS}, but this has "{show(written)}".'
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return text


def _e211(form: str = "extra", action: str = "on", written: str = "now") -> str:
    """``form``: ``extra`` (a second item, as written), ``with`` (``written`` runs from
    ``with`` to the end of the line), or ``colon``."""
    if form == "with":
        return (f"full-screen text appears instantly, so nvl {action} can't take "
                f'"{show(written)}". Put the transition on the scene line before it.')
    if form == "colon":
        return (f"nvl doesn't start a block, so it takes no \":\". Write nvl {action}, then "
                "the lines under it at the same indentation.")
    return f'nvl {action} takes nothing else on its line, but this has "{show(written)}".'


def _w100(form: str = "theme", key: str = "text_color", color: str = "#A0A0A0",
          ratio: float = 1.7, backdrop: str = "black", fill: str = "#FFF4F8",
          opacity: float = 0.85) -> str:
    """``("theme", key, color, ratio, backdrop, fill_color, fill_opacity)``: a ``[theme.nvl]``
    color (``text_color``, ``name.text_color``, ``indicator.fill_color``) on the panel,
    ``backdrop`` the picture (``black``/``white``) giving the lower ratio. ``("character",
    who, color, ratio)``: a ``Character``'s name color on the panel."""
    if form == "character":
        return (f"{show(key)}'s color {color} gives {_ratio(ratio)}:1 on the full-screen text "
                "panel ([theme.nvl]); names need at least 3:1. Pick a darker color, or change "
                "[theme.nvl] fill_color.")
    what, need = _W100_NEEDS[key]
    return (f"config.toml: [theme.nvl] {key} {color} on fill_color {fill} at fill_opacity "
            f"{opacity:g} gives {_ratio(ratio)}:1 over a {backdrop} picture; {what} at least "
            f"{need}:1. Pick colors further apart.")


def _w101(pages: int = 2, size: int = 28) -> str:
    clicks = "once" if pages == 2 else f"{pages - 1} times"
    return (f"this full-screen line needs {pages} pages at text size {size}, so the player "
            f"clicks {clicks} partway through. To choose where it breaks, split it into two "
            "lines.")


def _w102(count: int = 33) -> str:
    return (f"{count} lines have gone by in full-screen text since the last nvl clear, so the "
            "oldest isn't kept for loading and rollback, and a page restored here may start "
            "at a different line. Add nvl clear where a new page should begin.")


# --- F19 routes and endings (F19 01 §5.5; 04 §6; 06 AC-F19-03 to 07, D2, G1; 07 I-6) ---------
# Load E240, E242, E243 (forms need, many, twice, empty), E244 (need, unlock_ending, top,
# declare) (engine/script/routes.py); E241, E243 (label, until), E244 (route, ending), E245,
# E246, W130 (checks.py, bindings.py). Launch W131 and run W132 are raised in
# runtime/endings.py, run E245 in runtime/errors.py (built, F19 steps 2–3).
# Drafts for the narrative designer (06 G1): E242's heading and route forms, E245's default
# form for routes, and the no-suggestion forms of E243's until and E244's route and ending.

_E242_FORMS = frozenset(("empty", "long", "tags", "name"))


def _e240(form: str = "need", arg: object = None) -> str:
    """``need``; ``texts`` (count); ``left`` (written); ``top``."""
    if form == "texts":
        count = int(arg) if isinstance(arg, int) else 3
        return (f"ending has {_COUNT_WORDS.get(count, f'{count:,}')} texts; give at most a "
                "heading and a title.")
    if form == "left":
        return (f'this line has "{show(str(arg))}" left over after the ending title. ending '
                "takes a name, an optional heading, a title, a card length, and with, in that "
                "order.")
    if form == "top":
        return "ending goes inside a label, because it runs when the story reaches it."
    return ('ending needs a name and a title in quotes, e.g. ending good "The Lantern '
            'Festival".')


def _e241(kind: str = "ending", name: str = "good",
          first: Place = ("script/story.vns", 40)) -> str:
    if kind == "route":
        return (f'route "{show(name)}" is declared twice: here and at {_place(first)}. Keep one '
                "lock route line.")
    return (f'there are two endings named "{show(name)}": here and at {_place(first)}. Give '
            "each ending its own name.")


def _e242(form: str = "long", *args: object) -> str:
    """``empty`` (which[, word]); ``long`` (which, count, limit[, word]); ``tags`` ([word]);
    ``name`` (which, count, limit[, word]); ``word`` is ``"ending"`` (default) or ``"route"``.
    Any other first argument is the written card length (``chapter.card_args`` reports it
    with the ``seconds`` code alone)."""
    if form not in _E242_FORMS:
        return ("ending takes a card length from 0 to 30 seconds (0 shows no card), but this "
                f"has {show(form)}.")
    if form == "tags":
        word = str(args[0]) if args else "ending"
        return (f"{word} text is shown as written, so it can't use text tags such as {{b}}. "
                'Write {{ for a "{".')
    if form == "empty":
        which = str(args[0]) if args else "title"
        word = str(args[1]) if len(args) > 1 else "ending"
        return f"the {word} {which} is empty."
    which, count, limit = (args + ("title", 140, 120)[len(args):])[:3]
    word = str(args[3]) if len(args) > 3 else "ending"
    if form == "name":
        which = "name"
    return f"the {word} {which} has {int(count):,} characters; keep it to {int(limit):,}."


def _e243(form: str = "need", *args: object) -> str:
    """``need``; ``label`` (name, suggestion); ``until`` (name, suggestion); ``twice`` (name);
    ``many`` (count, limit); ``empty``."""
    if form == "label":
        name, suggestion = (args + (None,))[:2] if args else ("promis", None)
        text = (f"lock route {show_name(str(name))} names the label the route starts at, but "
                f'there is no label "{show_name(str(name))}". ')
        if suggestion is not None:
            return text + _did_you_mean(str(suggestion), str(name))
        return text + ("Add that label, or use the name of the label where the route "
                       "starts.")
    if form == "until":
        name, suggestion = (args + (None,))[:2] if args else ("god", None)
        text = f'until names endings, but there is no ending "{show_name(str(name))}".'
        if suggestion is not None:
            return text + " " + _did_you_mean(str(suggestion), str(name))
        return text + " Use the name of an ending line."
    if form == "twice":
        name = str(args[0]) if args else "good"
        return f'until lists "{show_name(name)}" twice.'
    if form == "many":
        count, limit = (args + (40, 32)[len(args):])[:2]
        return f"until lists {int(count):,} endings; the most is {int(limit):,}."
    if form == "empty":
        return "until needs at least one ending name, e.g. until sad, good."
    return ('lock route needs a label name and a title in quotes, e.g. lock route promise '
            '"Hana\'s Promise".')


# E244's ``top`` form names what each row declares; a row's word unless listed here.
_TOP_NOUNS: dict[str, str] = {"gallery": "gallery picture", "track": "music-room track",
                               "replay": "scene replay"}
# Rows with no in-label form (F35's ``track``: E336), left out of E244's ``need`` list.
_TOP_ONLY: frozenset[str] = frozenset({"track"})


def _e244(form: str = "need", *args: object) -> str:
    """``need`` (the target words, table order); ``route``/``ending`` (name, suggestion);
    ``unlock_ending``; ``top`` (the words of the rows with a top-level form, F21 07 I-14);
    ``declare`` (name)."""
    if form in ("route", "ending"):
        name, suggestion = (args + (None,))[:2] if args else ("promis", None)
        text = f'there is no {form} "{show_name(str(name))}".'
        if suggestion is not None:
            text += " " + _did_you_mean(str(suggestion), str(name))
        if form == "route":
            return text + ' Declare routes at the top level with lock route promise "Title".'
        return text if suggestion is not None else (
            text + ' Name an ending from an ending line, e.g. lock ending good.')
    if form == "unlock_ending":
        return ("unlock ending can't be used: an ending is recorded when the story reaches its "
                "ending line.")
    if form == "top":
        # F21 07 I-14: the words of the rows with a top-level form, table order.
        # F34: the gallery row declares a picture; F35: the track row a music-room track.
        words = [_TOP_NOUNS.get(str(w), str(w)) for w in args[0]] if args and args[0] \
            else ["route"]
        return (f'at the top level, lock only declares a {_join_or(words)}, e.g. lock route '
                'promise "Hana\'s Promise". Put unlock and lock ending inside a label.')
    if form == "declare":
        name = show_name(str(args[0])) if args else "promise"
        return (f"lock route {name} declares a route, so it goes at the top level. To lock it "
                f"again during the story, write lock route {name} with no title.")
    words = ([str(w) for w in args[0] if str(w) not in _TOP_ONLY] if args and args[0]
             else ["route", "ending"])
    return (f"lock and unlock take {_join_or(words)}, then a name, e.g. unlock route "
            "promise.")


def _e245(form: str = "change", name: str = "endings") -> str:
    """``default`` (name) at a ``default persistent.<name>``; ``change`` (name) at a write or
    change the script shows (load) or a computed ``setattr``/``delattr`` (run)."""
    if form == "default":
        what = ("the endings reached so far" if name == "endings" else
                "the routes open so far")
        return (f"persistent.{name} is kept by the engine ({what}), so it can't have a "
                "default. Remove this line.")
    if name == "routes":
        return ("persistent.routes is kept by the engine, so this line can't change it. Open a "
                "route with unlock route and close it with lock route.")
    return ("persistent.endings is kept by the engine, so this line can't change it. Endings "
            "are recorded by the ending statement and forgotten with lock ending.")


def _e246(kind: str = "ending", count: int = 1204, limit: int = 1000) -> str:
    plural = "routes" if kind == "route" else "endings"
    return f"this story has {count:,} {plural}; the engine allows {limit:,}."


def _w131(form: str = "endings", count: int = 2) -> str:
    if form == "routes":
        return ('persistent data had its own value named "routes" from an older version of the '
                "game. It was dropped; routes now open with unlock route.")
    names = "ending name" if count == 1 else "ending names"
    return ('persistent data had its own value named "endings" from an older version of the '
            f"game. {count:,} {names} in it were recorded as reached, and the value was "
            "dropped.")


def _w132(name: str = "promise", until: Sequence[str] = ("sad", "good")) -> str:
    listed = ", ".join(show_name(str(n)) for n in until)
    return (f"lock route {show_name(name)} has no effect while its until endings ({listed}) "
            "are reached. Lock one of those endings too, or remove until.")


# --- F21 codex: tips and items (F21 01 §5.5; 04 §6; 06 AC-F21-02 to 07, G1; 07 I-3, I-14) ---
# Load E250, E252 (engine/script/codex.py); E251, E253, E254, W140, W142 (checks.py); E255
# (bindings.py); launch and run E256, run W141 (engine/runtime/codex.py, F21 step 2). The item
# forms swap the word ``tip`` for ``item`` (and the article). Drafts for the narrative designer
# (06 G1, 07 I-14): E250's left-over form for parts out of order, E252's empty category, E253
# and E255 with no close match, E256 form 1's tips wording, E256 form 2 (it names no entry: the
# name a computed ``setattr`` changes isn't known), and E256 form 3 with no close match.

_CODEX_EXAMPLE = {"tip": ('lanterns', '"Paper Lanterns"'), "item": ('brass_key', '"Brass Key"')}


def _a(kind: str) -> str:
    return f"an {kind}" if kind[:1] in "aeiou" else f"a {kind}"


def _e250(form: str = "need", *args: object) -> str:
    """``need`` (kind); ``left`` (written, kind); ``in``; ``declare`` (kind, name, title as
    written); ``body`` (kind); ``top``."""
    if form == "left":
        written, kind = (args + ("slowly", "tip")[len(args):])[:2]
        return (f'this line has "{show(str(written))}" left over after the title. lock {kind} '
                'takes a name, a title, in "Category", and image, in that order.')
    if form == "in":
        return 'in needs a category in quotes, e.g. in "Festival".'
    if form == "declare":
        kind, name, title = (args + ("tip", "lanterns", '"Paper Lanterns"')[len(args):])[:3]
        name = show_name(str(name))
        return (f"lock {kind} {name} {show(str(title))} declares {_a(str(kind))}, so it goes at "
                f"the top level. To make the game forget it during the story, write lock "
                f"{kind} {name} with no title.")
    if form == "body":
        kind = str(args[0]) if args else "tip"
        return (f"only quoted text can go under {_a(kind)}, one paragraph per line, e.g. "
                '"Lanterns are made of paper."')
    if form == "top":
        return "unlock goes inside a label, because it runs when the story reaches it."
    kind = str(args[0]) if args else "tip"
    name, title = _CODEX_EXAMPLE.get(kind, _CODEX_EXAMPLE["tip"])
    return f"lock {kind} needs a name and a title in quotes, e.g. lock {kind} {name} {title}."


def _e251(form: str = "twice", *args: object) -> str:
    """``twice`` (name, first place); ``mixed`` (category, kind here, kind there, place)."""
    if form == "mixed":
        text, here, there, place = (args + ("Festival", "item", "tip",
                                             ("script/codex.vns", 30))[len(args):])[:4]
        return (f'the category "{show(str(text))}" holds {here}s here and {there}s at '
                f"{_place(place)}. Give {here}s their own category.")  # type: ignore[arg-type]
    name, first = (args + ("lanterns", ("script/codex.vns", 4))[len(args):])[:2]
    return (f'there are two codex entries named "{show_name(str(name))}": here and at '
            f"{_place(first)}. Give each tip and item its own name.")  # type: ignore[arg-type]


def _e252(form: str = "long", *args: object) -> str:
    """``name`` (count, limit, kind); ``empty`` (which, kind); ``long`` (which, count, limit,
    kind); ``paragraphs`` (count, limit, kind); ``paragraph`` (count, limit); ``tags``
    (kind); ``tag`` (tag, kind). ``which`` is ``"title"`` or ``"category"``."""
    if form == "name":
        count, limit, kind = (args + (70, 64, "tip")[len(args):])[:3]
        return f"the {kind} name has {int(count):,} characters; keep it to {int(limit):,}."
    if form == "empty":
        which, kind = (args + ("title", "tip")[len(args):])[:2]
        return "the category is empty." if which == "category" else f"the {kind} {which} is empty."
    if form == "paragraphs":
        count, limit, kind = (args + (40, 32, "tip")[len(args):])[:3]
        return f"this {kind} has {int(count):,} paragraphs; keep it to {int(limit):,}."
    if form == "paragraph":
        count, limit = (args + (2300, 2000)[len(args):])[:2]
        return f"this paragraph has {int(count):,} characters; keep it to {int(limit):,}."
    if form == "tags":
        kind = str(args[0]) if args else "tip"
        return (f"{kind} titles and categories are shown as written, so they can't use text "
                'tags such as {b}. Write {{ for a "{".')
    if form == "tag":
        tag, kind = (args + ("var", "tip")[len(args):])[:2]
        if tag == "username":                                           # F30: E302's wording
            return _username_only("a codex entry")
        return (f"{_a(str(kind))} paragraph can use {{b}}, {{i}}, and {{color}}, but not "
                f"{{{tag}}}.")
    which, count, limit, kind = (args + ("title", 75, 60, "tip")[len(args):])[:4]
    what = "the category" if which == "category" else f"the {kind} {which}"
    return f"{what} has {int(count):,} characters; keep it to {int(limit):,}."


def _e253(form: str = "unknown", *args: object) -> str:
    """``unknown`` (kind, name, suggestion); ``kind`` (name, its kind, the line's kind,
    verb)."""
    if form == "kind":
        name, actual, wanted, verb = (args + ("brass_key", "item", "tip", "unlock")[len(args):])[:4]
        name = show_name(str(name))
        return f"{name} is {_a(str(actual))}, not {_a(str(wanted))}. Write {verb} {actual} {name}."
    kind, name, suggestion = (args + ("tip", "lantern", None)[len(args):])[:3]
    shown = show_name(str(name))
    text = f'there is no {kind} "{shown}".'
    if suggestion is not None:
        text += " " + _did_you_mean(str(suggestion), str(name))
    return text + f' Declare {kind}s at the top level, e.g. lock {kind} {shown} "Title".'


def _e254(form: str = "tip", count: int = 1204, limit: int = 1000) -> str:
    """``tip``/``item`` (count, limit) or ``categories`` (count, limit)."""
    if form == "categories":
        return f"this story has {count:,} codex categories; the engine allows {limit:,}."
    return f"this story has {count:,} {form}s; the engine allows {limit:,}."


def _e255(form: str = "unknown", *args: object) -> str:
    """``unknown`` (attribute, suggestion); ``change`` (``tips`` or ``items``)."""
    if form == "change":
        name = str(args[0]) if args else "items"
        fix = "Use unlock tip." if name == "tips" else "Use unlock item and lock item."
        return f"Python can't change codex.{name}. {fix}"
    name, suggestion = (args + ("itmes", None)[len(args):])[:2]
    text = f"there is no codex.{show_name(str(name))}."
    if suggestion is not None:
        text += " " + _did_you_mean(str(suggestion), str(name))
    return text + " codex has tips and items."


def _e256(form: str = "define", *args: object) -> str:
    """``define`` (what was read: ``tips``, ``items``, or another name; the launch prefix
    ``define X couldn't be set: `` is added by ``errors.py``); ``change`` (``tips``,
    ``items``, or another name); ``unknown`` (attribute, suggestion): E255 form 1's text
    (06 D4)."""
    if form == "change":
        name = str(args[0]) if args else ""
        if name in ("tips", "items"):
            return _e255("change", name)
        return "Python can't change codex. Use unlock tip, unlock item, and lock item."
    if form == "unknown":
        return _e255("unknown", *args)
    name = str(args[0]) if args else "items"
    held = "tips" if name == "tips" else "items"
    return (f"it reads codex, which holds {held} only once a game has started. Use a lambda "
            "or a default.")


def _w141(name: str = "brass_key") -> str:
    return (f"lock item {show_name(name)} does nothing here, because the player doesn't have "
            "it.")


def _w140(text: str = "festival", first: str = "Festival",
          place: Place = ("script/codex.vns", 1)) -> str:
    return (f'the category "{show(text)}" differs from "{show(first)}" ({_place(place)}) only '
            "in capitals or spaces, so they show as two tabs. Use one spelling.")


def _w142(name: str = "river_god") -> str:
    name = show_name(name)
    return (f"tip {name} is declared, but no unlock tip {name} line names it, so players get "
            "it only if code unlocks it.")


# --- F34 CG gallery (F34 01 §5.3; 04 §3) ---------------------------------------------------------
# Load E342, E344 (engine/script/gallery.py); E343, E345, W226 (checks.py; W226 dev only, area
# script). E346, E347, W227, W228 are claimed and spare. Picture names go through
# ``show_name``, titles and leftovers through ``show``.

_GALLERY_EXAMPLE = 'lock gallery cg festival "Festival Night"'


def _e342(form: str = "need", *args: object) -> str:
    """``need``; ``left`` (written); ``body``; ``declare`` (picture, title as written);
    ``top``."""
    if form == "left":
        written = str(args[0]) if args else "slowly"
        return (f'this line has "{show(written)}" left over after the title. lock gallery '
                "takes a picture name, then a title in quotes.")
    if form == "body":
        return ("only picture names can go under a gallery picture, one per line, e.g. "
                "cg festival_smile.")
    if form == "declare":
        picture, title = (args + ("cg festival", '"Festival Night"')[len(args):])[:2]
        picture = show_name(str(picture))
        return (f"lock gallery {picture} {show(str(title))} adds a picture to the gallery, so it "
                "goes at the top level. To make the game forget it during the story, write "
                f"lock gallery {picture} with no title.")
    if form == "top":
        return "unlock gallery goes inside a label, because it runs when the story reaches it."
    return f"lock gallery needs a picture name and a title in quotes, e.g. {_GALLERY_EXAMPLE}."


def _e343(form: str = "twice", *args: object) -> str:
    """``twice`` (picture, first place); ``many`` (count, limit)."""
    if form == "many":
        count, limit = (args + (520, 500)[len(args):])[:2]
        return f"this story has {int(count):,} gallery pictures; the engine allows {int(limit):,}."
    picture, first = (args + ("cg festival", ("script/gallery.vns", 4))[len(args):])[:2]
    return (f'the picture "{show_name(str(picture))}" is in the gallery twice: here and at '
            f"{_place(first)}. Give each picture one place in the gallery.")  # type: ignore[arg-type]


def _e344(form: str = "long", *args: object) -> str:
    """``empty``; ``long`` (count, limit); ``tags``; ``versions`` (count, limit)."""
    if form == "empty":
        return "the gallery title is empty."
    if form == "tags":
        return ("gallery titles are shown as written, so they can't use text tags such as {b}. "
                'Write {{ for a "{".')
    if form == "versions":
        count, limit = (args + (11, 8)[len(args):])[:2]
        return f"this gallery picture has {int(count):,} versions; keep it to {int(limit):,}."
    count, limit = (args + (75, 60)[len(args):])[:2]
    return f"the gallery title has {int(count):,} characters; keep it to {int(limit):,}."


def _e345(picture: str = "cg festivl", suggestion: str | None = None) -> str:
    shown = show_name(str(picture))
    text = f'there is no gallery picture "{shown}".'
    if suggestion is not None:
        text += " " + _did_you_mean(str(suggestion), str(picture))
    return (text + " Add pictures to the gallery at the top level, e.g. lock gallery "
            f'{shown} "Title".')


def _w226(picture: str = "cg storm") -> str:
    return (f'the gallery picture "{show_name(str(picture))}" never shows in the story and no '
            "unlock gallery line names it, so players can't get it.")


# --- F35 Music room (F35 SPEC.md §3) -------------------------------------------------------------
# Load E336 (engine/script/musicroom.py); E337, E338, W220, W221 (checks.py; W220 and W221 dev
# only, area script). W222 is claimed and spare. Track and ending names go through
# ``show_name``, titles, files and leftovers through ``show``; nothing read from the
# persistent file is printed.

_TRACK_EXAMPLE = 'lock track main_theme "Main Theme" file "music/main_theme.ogg"'


def _e336(form: str = "need", *args: object) -> str:
    """``need``; ``left`` (written); ``top`` ([name[, title as written]]); ``unlock``;
    ``empty``; ``long`` (count, limit); ``tags``; ``until``."""
    if form == "left":
        written = str(args[0]) if args else "loud"
        return (f'this line has "{show(written)}" left over. lock track takes a name, a title, '
                'file "…", then open or until and endings, in that order.')
    if form == "top":
        name, title = (args + ("main_theme", '"Main Theme"')[len(args):])[:2]
        line = f"lock track {show_name(str(name))}"
        if title is not None:
            line += f" {show(str(title))}"
        return f"{line} declares a music-room track, so it goes at the top level."
    if form == "unlock":
        return ("there is no unlock track: a track opens when the story plays its music. Add "
                "open or until to its lock track line to open it another way.")
    if form == "empty":
        return "the track title is empty."
    if form == "long":
        count, limit = (args + (75, 60)[len(args):])[:2]
        return f"the track title has {int(count):,} characters; keep it to {int(limit):,}."
    if form == "tags":
        return ("track titles are shown as written, so they can't use text tags such as {b}. "
                'Write {{ for a "{".')
    if form == "until":
        return "until needs 1 to 32 ending names, e.g. until good, true."
    return f"lock track needs a name, a title in quotes and a file, e.g. {_TRACK_EXAMPLE}."


def _e337(form: str = "twice", *args: object) -> str:
    """``twice`` (name, first place); ``file`` (first name, this name, file); ``many``
    (count, limit)."""
    if form == "file":
        first, name, file = (args + ("festival", "night_walk",
                                     "music/festival.ogg")[len(args):])[:3]
        return (f"tracks {show_name(str(first))} and {show_name(str(name))} both play "
                f'"{show(str(file))}". Put each file in the music room once.')
    if form == "many":
        count, limit = (args + (230, 200)[len(args):])[:2]
        return (f"this story has {int(count):,} music-room tracks; the engine allows "
                f"{int(limit):,}.")
    name, first = (args + ("festival", ("database.vns", 4))[len(args):])[:2]
    return (f'there are two tracks named "{show_name(str(name))}": here and at '
            f"{_place(first)}. Give each track its own name.")  # type: ignore[arg-type]


def _e338(name: str = "ture", suggestion: str | None = "true") -> str:
    text = f'until names endings, but there is no ending "{show_name(str(name))}".'
    if suggestion is not None:
        return text + " " + _did_you_mean(str(suggestion), str(name))
    return text + " Use the name of an ending line."


def _w220(name: str = "festival", file: str = "music/festval.ogg",
          suggestion: str | None = "music/festival.ogg") -> str:
    text = (f'track {show_name(str(name))} plays "{show(str(file))}", but there is no such file '
            "in audio/.")
    if suggestion is not None:
        text += f' Did you mean "{show(str(suggestion))}"?'
    return text


def _w221(name: str = "festival", file: str = "music/festival.ogg") -> str:
    return (f'track {show_name(str(name))} opens when the story plays "{show(str(file))}", but '
            "no play music or queue music line plays it, so players never get it. Add open or "
            "until, or play it in the story.")


# --- F36 Ending list & scene replay (F36 01 §5.3) -----------------------------------------------
# Load E348, E350, E351's own form, E352's value, twice and dotted forms (engine/script/replay.py);
# E349, E351, E352's variable form (checks.py). Run W229 (runtime/replay.py, F36-W2; area story,
# once per line per session). E353, E354, W230, W231 are claimed and spare. Scene and variable
# names go through ``show_name``, titles, values, files and leftovers through ``show``.

_REPLAY_EXAMPLE = 'lock replay festival "The Festival"'


def _e348(form: str = "need", *args: object) -> str:
    """``need``; ``left`` (written); ``to``; ``body``; ``declare`` (scene, title as written);
    ``top``."""
    if form == "left":
        written = str(args[0]) if args else "slowly"
        return (f'this line has "{show(written)}" left over. lock replay takes a scene name, a '
                "title in quotes, then image and to, in that order.")
    if form == "to":
        return "to needs a scene name, e.g. to fireworks."
    if form == "body":
        return "only starting values can go under a replay, one per line, e.g. coins = 3."
    if form == "declare":
        scene, title = (args + ("festival", '"The Festival"')[len(args):])[:2]
        scene = show_name(str(scene))
        return (f"lock replay {scene} {show(str(title))} declares a scene replay, so it goes at "
                "the top level. To make the game forget it during the story, write lock replay "
                f"{scene} with no title.")
    if form == "top":
        return "unlock replay goes inside a label, because it runs when the story reaches it."
    return f"lock replay needs a scene name and a title in quotes, e.g. {_REPLAY_EXAMPLE}."


def _e349(form: str = "twice", *args: object) -> str:
    """``twice`` (scene, first place); ``many`` (count, limit)."""
    if form == "many":
        count, limit = (args + (520, 500)[len(args):])[:2]
        return f"this story has {int(count):,} replays; the engine allows {int(limit):,}."
    scene, first = (args + ("festival", ("extras.vns", 4))[len(args):])[:2]
    return (f'the scene "{show_name(str(scene))}" has two replays: here and at '
            f"{_place(first)}. Give each scene one replay.")  # type: ignore[arg-type]


def _e350(form: str = "long", *args: object) -> str:
    """``empty``; ``long`` (count, limit); ``tags``; ``values`` (count, limit)."""
    if form == "empty":
        return "the replay title is empty."
    if form == "tags":
        return ("replay titles are shown as written, so they can't use text tags such as {b}. "
                'Write {{ for a "{".')
    if form == "values":
        count, limit = (args + (40, 32)[len(args):])[:2]
        return f"this replay has {int(count):,} starting values; keep it to {int(limit):,}."
    count, limit = (args + (75, 60)[len(args):])[:2]
    return f"the replay title has {int(count):,} characters; keep it to {int(limit):,}."


def _e351(form: str = "scene", *args: object) -> str:
    """``scene`` (name, suggestion); ``own`` (name); ``replay`` (name, suggestion)."""
    if form == "own":
        name = show_name(str(args[0])) if args else "festival"
        return (f"to {name} names the replay's own scene. Name the scene where the replay "
                "should stop, or leave out to.")
    name, suggestion = (args + ("festivl", "festival")[len(args):])[:2]
    shown = show_name(str(name))
    if form == "replay":
        text = f'there is no replay of "{shown}".'
        if suggestion is not None:
            text += " " + _did_you_mean(str(suggestion), str(name))
        return text + f' Declare it at the top level, e.g. lock replay {shown} "Title".'
    text = f'there is no scene "{shown}".'
    if suggestion is not None:
        return text + " " + _did_you_mean(str(suggestion), str(name))
    return text + " Use the name of a label."


def _e352(form: str = "variable", *args: object) -> str:
    """``variable`` (name as written, maybe dotted); ``value`` (the value as written);
    ``twice`` (name)."""
    if form == "value":
        written = str(args[0]) if args else "coins + 1"
        return ("a starting value is a number, text in quotes, True, False, or None, but this "
                f'has "{show(written)}".')
    if form == "twice":
        name = show_name(str(args[0])) if args else "coins"
        return f"{name} has two starting values here; keep one."
    written = str(args[0]) if args else "coins"
    plain = written.rpartition(".")[2] or "coins"
    return (f"{show_name(written)} isn't a story variable. Starting values are for names made "
            f"with default, e.g. default {show_name(plain)} = 0.")


def _w229(form: str = "delete", name: str = "hana.chr") -> str:
    """``write``/``delete`` (the file as written in the script); ``saves``."""
    if form == "saves":
        return ("ui delete saves doesn't run during a replay, so the player's saves stay as "
                "they are.")
    verb = "write" if form == "write" else "delete"
    return (f'file {verb} "{show(str(name))}" ' "doesn't run during a replay, so the player's "
            "files stay as they are.")


# --- F37 Achievements (SPEC §3) -------------------------------------------------------------------
# Load E339 (engine/script/achievements.py), E340 (checks.py); run W223 (runtime/achievements.py,
# area story, once per achievement per session); dev load W224 (checks.py). W225 (the platform
# hook) is minigames/messages.py's, as F23's plugin texts are (``minigames`` never imports
# ``script``); its docs row is docs/minigames.md's. E341 is claimed and spare. Names go
# through ``show_name``, titles, leftovers and Python's text through ``show``.

_ACHIEVEMENT_EXAMPLE = 'lock achievement first_steps "First Steps" "Finish the prologue."'


def _e339(form: str = "need", *args: object) -> str:
    """``need``; ``left`` (written); ``declare`` (name, title as written); ``relock``
    (name or None); ``top``; ``when``; ``python`` (Python's text); ``empty``; ``long``,
    ``description``, ``condition`` (count, limit); ``tags``."""
    if form == "left":
        written = str(args[0]) if args else "now"
        return (f'this line has "{show(written)}" left over. lock achievement takes a name, a '
                "title, a description, image …, hidden, then when and a condition, in that "
                "order.")
    if form == "declare":
        name, title = (args + ("first_steps", '"First Steps"')[len(args):])[:2]
        name = show_name(str(name))
        return (f"lock achievement {name} {show(str(title))} declares an achievement, so it "
                "goes at the top level. To give it to the player, write unlock achievement "
                f"{name}.")
    if form == "relock":
        name = args[0] if args else "first_steps"
        what = f"lock achievement {show_name(str(name))}" if name is not None \
            else "lock achievement"
        return f"achievements can't be taken back, so {what} can't go in a label."
    if form == "top":
        return ("unlock achievement goes inside a label, because it runs when the story "
                "reaches it.")
    if form == "when":
        return 'when needs a condition, e.g. when "good" in persistent.endings.'
    if form == "python":
        text = str(args[0]) if args else "this isn't valid Python"
        return f"the condition after when isn't valid Python: {_finish(text)}"
    if form == "empty":
        return "the achievement title is empty."
    if form == "tags":
        return ("achievement titles and descriptions are shown as written, so they can't use "
                'text tags such as {b}. Write {{ for a "{".')
    if form in ("long", "description", "condition"):
        default = {"long": (75, 60), "description": (230, 200), "condition": (620, 500)}[form]
        count, limit = (args + default[len(args):])[:2]
        what = {"long": "the achievement title", "description": "the achievement description",
                "condition": "the condition"}[form]
        return f"{what} has {int(count):,} characters; keep it to {int(limit):,}."
    return f"lock achievement needs a name and a title in quotes, e.g. {_ACHIEVEMENT_EXAMPLE}"


def _e340(form: str = "twice", *args: object) -> str:
    """``twice`` (name, first place); ``many``, ``when`` (count, limit); ``unknown`` (name,
    suggestion)."""
    if form in ("many", "when"):
        count, limit = (args + ((230, 200) if form == "many" else (70, 64))[len(args):])[:2]
        what = "achievements" if form == "many" else "achievements with when"
        return f"this story has {int(count):,} {what}; the engine allows {int(limit):,}."
    if form == "unknown":
        name, suggestion = (args + ("first_step", "first_steps")[len(args):])[:2]
        shown = show_name(str(name))
        text = f'there is no achievement "{shown}".'
        if suggestion is not None:
            text += " " + _did_you_mean(str(suggestion), str(name))
        return (text + " Declare achievements at the top level, e.g. lock achievement "
                f'{shown} "Title".')
    name, first = (args + ("first_steps", ("database.vns", 9))[len(args):])[:2]
    return (f'there are two achievements named "{show_name(str(name))}": here and at '
            f"{_place(first)}. Give each achievement its own name.")  # type: ignore[arg-type]


def _w223(name: str = "completionist", reason: str = "NameError") -> str:
    """``reason``: the exception's type name, or ``it ran too long`` (the watchdog)."""
    return (f"achievement {show_name(str(name))}'s when condition failed ({show(str(reason))}), "
            "so it isn't checked again until the game restarts.")


def _w224(name: str = "first_steps") -> str:
    return (f"achievement {show_name(str(name))} has no when condition and no unlock "
            "achievement line names it, so players never get it.")


# --- F41 Script linter (F41 01 §4.1 PR-F41-05; 04 §7.2) -------------------------------------
# Lint W237–W242 (``tools/lint.py`` findings, F41-P2; the check child's names rows and the
# ``lint`` CLI's ``source: "lint"`` items, F41-P3). Never raised by the load: ``checks.py``
# has no rule for them. Final texts (01 §4.1). W243–W246 and E360–E364 are claimed and spare.
# Labels, characters, pictures, variables and defines go through ``show_name``; a sound's
# file (its name under ``audio/``, as Database's Sounds category shows it) through ``show``.

_W242_KINDS = ("define", "transition", "position", "meter")


def _w237(label: str = "old_ending") -> str:
    return (f'nothing leads to label "{show_name(str(label))}" from start (no jump, call or '
            "choice), so players never see it. Add a jump to it, or delete it if you don't "
            "need it.")


def _w238(name: str = "kenji") -> str:
    return f'character "{show_name(str(name))}" never speaks and no line names it.'


def _w239(name: str = "hana sad_blink1") -> str:
    return f'picture "{show_name(str(name))}" isn\'t shown anywhere in the story.'


def _w240(file: str = "music/old_theme.ogg") -> str:
    return f'sound "{show(str(file))}" isn\'t played anywhere in the story.'


def _w241(name: str = "lantern_count") -> str:
    return f'variable "{show_name(str(name))}" has a default, but no line reads or changes it.'


def _w242(kind: str = "define", name: str = "max_tries") -> str:
    """``kind``: ``define``, ``transition``, ``position`` or ``meter`` (anything else reads
    as ``define``)."""
    word = kind if kind in _W242_KINDS else "define"
    return f'{word} "{show_name(str(name))}" is defined but never used.'


# --- F43 Localization (F43 01 §5.4, final; 04 W0) -------------------------------------------
# Translation warnings W247–W256: never the script load's. Raised by reading
# ``translations/*.po`` (``po.py`` W247/W248, ``translations.discover`` W253), by checking an
# entry as its kind (``translatecheck.py`` W249–W251, W254, W252's missing characters), by the
# language setting (W255) and by ``check``/build (W252, W256). E365–E367 are claimed and spare.
# ``file`` is the file's name inside ``translations/`` (``ja.po``); W247, W253 and W254 start
# with ``translations/<file>``, so they are raised with that ``file=`` and no line. W248–W251
# carry no place: raise them with ``file="translations/ja.po"`` and the entry's line, which
# ``format()`` puts first. Language names (the English name, ``Japanese``), file names, keys
# and characters go through ``show``; ``{var}`` names through ``show_name``.

_PO_MAX_TEXT = "16 MB"                  # 04 §8 rule 3: a .po's cap (bytes) ...
_PO_MAX_ENTRIES = 100_000               # ... and entries
_W247_REASONS = {
    "utf8": "it isn't UTF-8 text",
    "large": f"it is larger than {_PO_MAX_TEXT}",
    "entries": f"it has more than {_PO_MAX_ENTRIES:,} entries",
}
_W248_FORMS = frozenset(("quote", "no_msgstr", "twice", "long", "unsupported"))
_W253_FORMS = frozenset(("bad_name", "original", "too_many"))
_W252_SHOWN = 3                         # AC-F43-21: three characters, then "and N more"


def _plain_and(items: Sequence[str]) -> str:
    """``a``; ``a and b``; ``a, b and c`` (01 §5.4 writes no serial comma)."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _var_names(names: str | Sequence[str]) -> str:
    listed = [names] if isinstance(names, str) else list(names)
    return _plain_and([f"{{{show_name(str(n))}}}" for n in listed])


def _w247(form: str = "utf8", file: str = "ja.po", language: str = "Japanese") -> str:
    """A .po that isn't read at all: ``form`` a ``_W247_REASONS`` key (anything else reads as
    ``utf8``)."""
    reason = _W247_REASONS.get(form, _W247_REASONS["utf8"])
    return (f"translations/{show(str(file))} can't be read ({reason}), so {show(str(language))} "
            "shows the original text.")


def _w248(form: str = "quote", detail: object = "") -> str:
    """One skipped entry (no place: the caller gives the file and line). ``form``: ``quote``;
    ``no_msgstr``; ``twice`` (``detail`` the key); ``long`` (``detail`` the kind's character
    cap, an int); ``unsupported`` (``msgid_plural``, an unknown keyword). Anything else reads
    as ``unsupported``."""
    if form == "quote":
        problem = "a quote isn't closed"
    elif form == "no_msgstr":
        problem = "msgstr is missing"
    elif form == "twice":
        problem = f'the key "{show(str(detail))}" is used twice'
    elif form == "long" and isinstance(detail, int):
        problem = f"the translation is longer than {detail:,} characters"
    else:
        problem = "this kind of entry isn't supported"
    return f"{problem}, so this entry is skipped."


def _w249(message: str = _E161["open"]) -> str:
    """A tag mistake in a translation (no place): ``message`` is the F05/F29/F07 message for
    the same mistake in a script line (``format_message`` of its code); its final ``.`` is
    dropped."""
    text = str(message)
    text = text[:-1] if text.endswith(".") else text
    return f"{text}, so the original text is shown."


def _w250(names: str | Sequence[str] = "score") -> str:
    """``{var}``/``{username}`` names the translation uses and the original doesn't (no place;
    names without braces)."""
    return (f"the translation uses {_var_names(names)}, which the original doesn't, so the "
            "original text is shown.")


def _w251(names: str | Sequence[str] = "name") -> str:
    """``{var}`` names the translation leaves out (dev note; no place)."""
    return f"the translation leaves out {_var_names(names)}, which the original shows."


def _w252(language: str = "Japanese", code: str = "ja", count: int = 37,
          chars: Sequence[str] = ("日", "本", "語")) -> str:
    """``count`` characters no font of the chain draws; ``chars`` the first ones in text order
    (three are shown, then "and N more")."""
    count = int(count)
    shown = [show(str(c)) for c in list(chars)[:_W252_SHOWN]]
    more = count - len(shown)
    listed = ", ".join(shown) + f" and {more:,} more" if more > 0 else _plain_and(shown)
    lang = show(str(language))
    what = ("1 character can't be drawn by any of the game's fonts" if count == 1 else
            f"{count:,} characters can't be drawn by any of the game's fonts")
    boxes = "it shows as a box" if count == 1 else "they show as boxes"
    return (f"{lang}: {what} ({listed}), so {boxes}. Give {lang} a font: "
            f"[translation.{show(str(code))}] font in config.toml, or Game settings ▸ "
            "Languages in Studio.")


def _w253(form: str = "bad_name", file: str = "japanese.po", name: str = "japanese") -> str:
    """A file in ``translations/`` that isn't used: ``bad_name`` (``name`` the file's stem);
    ``original`` (``name`` the original's code); ``too_many`` (past 32 languages). Anything
    else reads as ``bad_name``."""
    head = f"translations/{show(str(file))} isn't used:"
    if form == "original":
        return f"{head} {show(str(name))} is the original language."
    if form == "too_many":
        return f"{head} a game can have 32 languages."
    return (f'{head} "{show(str(name))}" isn\'t a language code such as ja, pt-BR or '
            "zh-Hans.")


def _w254(file: str = "ar.po") -> str:
    return (f"translations/{show(str(file))} has right-to-left or joined letters, which the "
            "engine can't draw correctly yet.")


def _w255(original: str = "English") -> str:
    """``original``: the original language's name."""
    return (f"the language in settings isn't in this game any more, so {show(str(original))} "
            "is used.")


def _w256(language: str = "Japanese", new: int = 12, changed: int = 3) -> str:
    """A language not fully Done: ``new`` texts with no translation, ``changed`` texts whose
    original changed since. A zero count leaves its part out."""
    new, changed = int(new), int(changed)
    parts = []
    if new or not changed:
        parts.append(f"{new:,} text{' isn' if new == 1 else 's aren'}'t translated yet "
                     "(players see the original)")
    if changed:
        since = "it was" if changed == 1 else "they were"
        noun = "" if new else (" text" if changed == 1 else " texts")
        parts.append(f"{changed:,}{noun} changed since {since} translated")
    return f"{show(str(language))}: {' and '.join(parts)}."


# --- F23 minigames (02-script.md §4.1; 04 §5.2, §5.3, §5.4) ---------------------------------
# Drafts for the narrative designer (06 G2). Names a plugin declares (minigame and argument
# names) and every piece of line text go through ``show_name``/``show``.

MINIGAME_LIST_ITEMS = 8          # E270's list form: 8 names, then "and N more" (SR-F23-03)
_MINIGAME_EXAMPLE = "minigame lantern_memory pairs=6 into turns"
_MINIGAME_ORDER = "minigame takes a name, skippable, arguments, and into, in that order."


def _series(items: Sequence[str]) -> str:
    """``a``; ``a and b``; ``a, b, and c``."""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return _and_list(items)


def _e270(form: str = "no_name", *args: object) -> str:
    """``no_name``; ``unknown`` (name, suggestion, listed names, more); ``top``;
    ``into_alone``; ``no_default`` (target, suggestion); ``define`` (target); ``engine``
    (target); ``not_plain`` (kind ``points``/``persistent``/``other``, written, attribute);
    ``as`` (target); ``left`` (left over, after what); ``dollar`` (the rebuilt line)."""
    if form == "unknown":
        name, suggestion, names, more = (args + ("stargaze", None, (), 0)[len(args):])[:4]
        text = f'there is no minigame named "{show_name(str(name))}".'
        if suggestion is not None:
            return text + " " + _did_you_mean(str(suggestion), str(name))
        shown = [show_name(str(n)) for n in names]  # type: ignore[union-attr]
        if not shown:
            return (text + " This game has no minigames. To add one, put its plugin in "
                    "game/minigames/.")
        if more:
            shown.append(f"{more:,} more")
        what = ("The minigame in this game is" if len(shown) == 1
                else "The minigames in this game are")
        return (f"{text} {what} {_series(shown)}. To add one, put its plugin in "
                "game/minigames/.")
    if form == "top":
        return "minigame goes inside a label, because it runs when the story reaches it."
    if form == "into_alone":
        return "into needs the name of a story variable, e.g. into turns."
    if form == "no_default":
        name, suggestion = (args + ("turn", None)[len(args):])[:2]
        if suggestion is not None:
            return (f'there is no default named "{show_name(str(name))}" for the result. '
                    + _did_you_mean(str(suggestion), str(name)))
        return (f"the result goes into a story variable with a default. Add default "
                f"{show_name(str(name))} = 0 at the top level of a file.")
    if form == "define":
        name = show_name(str(args[0])) if args else "hana"
        return (f'"{name}" is set by define, so the story can\'t change it. Keep the result in '
                "a variable that has a default.")
    if form == "engine":
        name = show_name(str(args[0])) if args else "dice"
        return (f'"{name}" is a name the engine uses. Keep the result in a variable that has '
                "a default.")
    if form == "not_plain":
        kind, written, attr = (args + ("other", "scores[0]", "")[len(args):])[:3]
        text = (f"into takes one story variable's name, such as into turns, but this has "
                f'"{show(str(written))}".')
        if kind == "points":
            return (text + f" To add the result to a meter, write points "
                    f"{show_name(str(attr))} += turns on the next line.")
        if kind == "persistent":
            return (text + f" To keep it across playthroughs, write $ {show(str(written))} = "
                    "turns on the next line.")
        return text + " Keep the result in a variable, then copy it with a $ line."
    if form == "as":
        name = show_name(str(args[0])) if args else "turns"
        return f"to keep the result, write into {name}, not as {name}."
    if form == "left":
        left, after = (args + ("found", "into turns")[len(args):])[:2]
        return (f'this line has "{show(str(left))}" left over after {show(str(after))}. '
                + _MINIGAME_ORDER)
    if form == "dollar":
        rebuilt = str(args[0]) if args and args[0] else _MINIGAME_EXAMPLE
        return (f"minigame is a statement, not Python, so it can't go in a $ line. Write "
                f"{show(rebuilt)}.")
    return f"minigame needs the name of a minigame, e.g. {_MINIGAME_EXAMPLE}."


def _e271(form: str = "unknown", *args: object) -> str:
    """``unknown`` (minigame, argument, suggestion, declared names, written ``name=value``);
    ``missing`` (minigame, names); ``twice`` (argument); ``space`` (name, value); ``bare``
    (text); ``double`` (name, value); ``empty`` (name); ``skippable_place`` (example line);
    ``skippable_none`` (minigame)."""
    if form == "missing":
        game, names = (args + ("lantern_memory", ("pairs",))[len(args):])[:2]
        names = [show_name(str(n)) for n in names]  # type: ignore[union-attr]
        if len(names) == 1:
            return (f"minigame {show_name(str(game))} needs a value for {names[0]}. Add "
                    f"{names[0]}=… to this line.")
        return (f"minigame {show_name(str(game))} needs values for {_series(names)}. Add "
                f"{_series([n + '=…' for n in names])} to this line.")
    if form == "twice":
        name = show_name(str(args[0])) if args else "pairs"
        return f"this line gives {name} twice. Keep one."
    if form == "space":
        name, value = (args + ("pairs", "6")[len(args):])[:2]
        return (f"write {show_name(str(name))}={show(str(value))}, with = between the argument "
                "and its value.")
    if form == "bare":
        text = str(args[0]) if args else "6"
        return f'arguments are written name=value, e.g. pairs=6, but this has "{show(text)}".'
    if form == "double":
        name, value = (args + ("pairs", "6")[len(args):])[:2]
        return f"write {show_name(str(name))}={show(str(value))}, with one =."
    if form == "empty":
        name = show_name(str(args[0])) if args else "pairs"
        return f"{name}= needs a value, e.g. {name}=6."
    if form == "skippable_place":
        example = str(args[0]) if args else "minigame lantern_memory skippable pairs=6"
        return f"skippable goes right after the minigame's name: {show(example)}."
    if form == "skippable_none":
        game = show_name(str(args[0])) if args else "lantern_memory"
        return (f"{game} has no skipped outcome, so it can't be skippable. Remove skippable, or "
                "give the plugin a skipped outcome.")
    game, name, suggestion, declared, written = (
        args + ("lantern_memory", "pair", "pairs", ("pairs", "hints"), "pair=6")[len(args):])[:5]
    game, shown = show_name(str(game)), show_name(str(name))
    if not declared:
        return f'{game} takes no arguments, so remove "{show(str(written))}".'
    text = f'{game} has no argument "{shown}".'
    if suggestion is not None:
        return text + " " + _did_you_mean(str(suggestion), str(name))
    listed = _series([show_name(str(n)) for n in declared])  # type: ignore[union-attr]
    return f"{text} It takes {listed}."


def _plugin_reason(reason: str) -> str:
    """A ``check_args`` refusal (cleaned and cut to 200 code points inside the guard,
    SEC-F23-07): redacted and escaped here, never cut again."""
    return escape_controls(redact(reason))


def _e272(form: str = "value", *args: object) -> str:
    """Run time (``runtime/minigame.py``, F23 s2). ``value`` (argument, then E85e's reason,
    path, kind, detail: ``the argument <name>`` is the subject); ``plugin`` (minigame,
    argument, its source text, reason: the line wrote exactly one argument); ``plugin_all``
    (minigame, reason) (F24 A2, 07 I-2)."""
    if form == "plugin":
        game, name, source, reason = (args + ("lantern_memory", "pairs", "40",
                                              "it takes 2 to 12 pairs.")[len(args):])[:4]
        return (f"{show_name(str(game))} can't use {show_name(str(name))}={echo(str(source))}: "
                f"{_plugin_reason(str(reason))}")
    if form == "plugin_all":
        game, reason = (args + ("lantern_memory", "it takes 2 to 12 pairs.")[len(args):])[:2]
        return (f"{show_name(str(game))} can't use these arguments: "
                f"{_plugin_reason(str(reason))}")
    name, reason, path, kind, detail = (args + ("words", "kind", None, "a set", "")[len(args):])[:5]
    subject = f"the argument {show_name(str(name)) if path is None else show(str(path))}"
    return _e85e(str(reason), str(name), subject, str(kind), str(detail))


_FIX_LOG = "Fix the plugin; the log has the details."
_STUCK_CHECK = "Check any while loop there."


def _plugin_place(file: object, line: object) -> str:
    """`` in minigames/x.py, line 88`` / `` in minigames/x.py`` / ``""`` (a bundled one:
    the script line's prefix names the place, 04 §7.6)."""
    if not file:
        return ""
    if type(line) is int:
        return f" in {show(str(file))}, line {line}"
    return f" in {show(str(file))}"


def _e275(form: str = "raised", *args: object) -> str:
    """Run time (F23 ``02`` §4.1; ``runtime/minigame.py``, s4's host). ``raised`` (minigame,
    plugin file or None for a bundled one, plugin line or None, Python's text or None);
    drafted here (``06`` G2): ``value`` (minigame, what was called, its value's kind words,
    file): a hook gave something it may not; ``stuck`` (minigame, what was called, seconds,
    file): the watchdog stopped ``check_args`` or ``outcome_for``, which E277 names only
    while the minigame plays."""
    if form == "value":
        game, what, kind, file = (args + ("lantern_memory", "check_args", "a whole number",
                                          "minigames/lantern_memory.py")[len(args):])[:4]
        fix = f" Fix {show(str(file))}." if file else ""
        return (f"minigame {show_name(str(game))}'s {show_name(str(what))} gave {kind}, which "
                f"it can't give.{fix}")
    if form == "stuck":
        game, what, seconds, file = (args + ("lantern_memory", "check_args", 5,
                                             "minigames/lantern_memory.py")[len(args):])[:4]
        return (f"minigame {show_name(str(game))}'s {show_name(str(what))} ran for "
                f"{seconds:g} seconds{_plugin_place(file, None)} without finishing, so it is "
                f"probably stuck in a loop. {_STUCK_CHECK}")
    # The ledger's request forms (F23 s4, ``runtime/minigame.py``; 06 G2 drafts): ``many``
    # (minigame, the most changes) and ``subclass`` (minigame, the refused name's kind).
    if form == "many":
        game, limit = (args + ("stargazing", 1_000)[len(args):])[:2]
        return (f"minigame {echo(str(game), 40)} asked for more than {int(limit):,} changes "
                "to meters and the codex, the most one minigame can make. Fix the plugin; the "
                "log has the details.")
    if form == "subclass":
        game, detail = (args + ("stargazing", "Name")[len(args):])[:2]
        return (f"minigame {echo(str(game), 40)} gave a name that isn't plain text ({detail}). "
                'Pass the name as text, e.g. "hana". Fix the plugin; the log has the details.')
    game, file, line, text = (args + ("stargazing", "minigames/stargazing.py", 88,
                                      "division by zero")[len(args):])[:4]
    head = f"minigame {show_name(str(game))} stopped with an error{_plugin_place(file, line)}"
    if text:
        text = str(text)
        text = text[:-1] if text.endswith(".") and not text.endswith("..") else text
        head = f"{head}: {text}"
    if not file:
        return f"{head}. The log has the details."
    return f"{head}. {_FIX_LOG}"


# E276's middle, by F03's Unsaveable reason (02 §4.1: "other E85e reasons swap the middle").
_RESULT_MIDDLES = {
    "key": "a dictionary with a key that isn't text",
    "nan": '"not a number" (nan)',
    "inf": "infinity (inf)",
    "big_int": "a whole number with more than 4,300 digits",
    "too_deep": "a result nested more than 100 levels deep",
}
_RESULT_KINDS = ("A result can be text, a number, True, False, None, a list, or a dictionary "
                 "with text keys.")


def _e277(game: str = "stargazing", seconds: float = 5, file: str | None = None,
          line: int | None = None) -> str:
    """Run time (F23 ``02`` §4.1; s4's host via ``runtime/minigame.e277_text``): the
    watchdog stopped a plugin call while the minigame played. A bundled minigame (``file``
    None) names no file."""
    if file is None:
        place = ""
    elif line is None:
        place = f" in {echo(file)}"
    else:
        place = f" in {echo(file)}, line {line},"
    return (f"minigame {echo(game, 40)} ran for {seconds:g} seconds{place} without finishing, "
            f"so it is probably stuck in a loop. {_STUCK_CHECK}")


def _e276(form: str = "result", *args: object) -> str:
    """Run time (F23 ``02`` §4.1; ``runtime/minigame.py``'s apply step, s4's host).
    ``result`` (minigame, ``Unsaveable`` reason, kind words, the ``into`` target or None,
    plugin file or None); drafted here (``06`` G2): ``change`` (minigame, the change's
    problem: ``amount`` with the meter and the value shown, ``name``, or ``kind``, file)."""
    if form == "change":
        game, problem, meter, shown, file = (args + ("probe", "amount", "hana", "True",
                                                     "minigames/probe.py")[len(args):])[:5]
        fix = f" Fix {show(str(file))}." if file else ""
        if problem == "amount":
            what = (f"a change to meter {show_name(str(meter))} by {show(str(shown))}, but a "
                    "change is a whole number from -1,000,000,000 to 1,000,000,000")
        elif problem == "name":
            what = "a change whose name isn't text"
        else:
            what = ("a change that wasn't made with add_points, set_points, give, take, or "
                    "unlock_tip")
        return f"{show_name(str(game))} finished with {what}.{fix}"
    game, reason, kind, target, file = (args + ("stargazing", "kind", "a set", "found",
                                                "minigames/stargazing.py")[len(args):])[:5]
    middle = kind if reason == "kind" else _RESULT_MIDDLES.get(str(reason), _RESULT_MIDDLES["too_deep"])
    head = f"{show_name(str(game))} finished with {middle}, which can't be saved"
    if target:
        head += f", so it can't go into {show_name(str(target))}"
    fix = f" Fix {show(str(file))}." if file else ""
    return f"{head}. {_RESULT_KINDS}{fix}"


# --- F20 flowchart (02-script.md §5; 04 §6.1, §6.2) ------------------------------------------
# Drafts for the narrative designer (06 §0.1). E260's ``place`` form (scene, omit, or forget
# after another word) is drafted here. F20 s2: E265 and W150–W153 (flowgraph.py); E265's
# name-count and "too complex" forms and W150's chapter, ending, and menu tails are drafted
# here (06 G7). PR-F02-31 bans "nodes" in messages, so E265 and W153 say "boxes" (the
# Flowchart page's word for them) where 02 §5 says "nodes".

_FLOWCHART_TAKES = ("A flowchart line takes a title in quotes, hidden, no jump, scene, omit, or "
                    "forget.")
_FLOWCHART_PLACE = {
    "scene": "flowchart scene \"Daichi's Stall\"",
    "omit": "flowchart omit",
    "forget": "flowchart forget stall",
}


def _e260(form: str = "unknown", *args: object) -> str:
    """``unknown`` (written, suggestion); ``scene_title``; ``order`` (scene: bool);
    ``two_titles``; ``twice`` (flag); ``omit_more``; ``forget_more`` (the rest); ``block``;
    ``place`` (word)."""
    if form == "scene_title":
        return ("flowchart scene needs the scene's title in quotes, e.g. flowchart scene "
                "\"Daichi's Stall\".")
    if form == "order":
        if args and args[0]:
            return ("the title goes right after flowchart scene, before hidden and no jump, "
                    "e.g. flowchart scene \"Daichi's Stall\" hidden.")
        return ("the title goes right after flowchart, before hidden and no jump, e.g. "
                'flowchart "Where should we go?" hidden.')
    if form == "two_titles":
        return "this flowchart line has two titles; give one."
    if form == "twice":
        flag = str(args[0]) if args else "hidden"
        return f"this line says {flag} twice. Keep one."
    if form == "omit_more":
        return ("flowchart omit takes nothing else. To put this menu on the flowchart with a "
                'title, write flowchart "Title" instead.')
    if form == "forget_more":
        rest = str(args[0]) if args else "now"
        return ("flowchart forget takes one label name or nothing, but this line goes on with "
                f'"{show(rest)}". Put anything else on its own line.')
    if form == "block":
        return ("flowchart doesn't take a block. Remove the \":\" and un-indent the lines "
                "under it.")
    if form == "place":
        word = str(args[0]) if args else "scene"
        return (f"{word} goes right after the word flowchart, e.g. "
                f"{_FLOWCHART_PLACE.get(word, _FLOWCHART_PLACE['scene'])}.")
    written, suggestion = (args + ("hiden", "hidden")[len(args):])[:2]
    text = f"\"{show(str(written))}\" isn't a flowchart word."
    if suggestion is not None:
        text += f' Did you mean "{show(str(suggestion))}"?'
    return f"{text} {_FLOWCHART_TAKES}"


def _e261(form: str = "first", *args: object) -> str:
    """``top`` (forget: bool); ``first`` (label, the line of its first statement)."""
    if form == "top":
        if args and args[0]:
            return ("flowchart forget goes inside a label, because it runs when the story "
                    "reaches it.")
        return ("flowchart lines go inside a label, next to the scene, menu, chapter, or ending "
                "they mark.")
    label, line = (args + ("stall", 12)[len(args):])[:2]
    return (f"flowchart scene must be the first line of label {show_name(str(label))}, so the "
            f"flowchart knows where the scene starts. Move it above line {line}.")


def _e262(form: str = "next", *args: object) -> str:
    """``next`` (E204's form of the next statement, its line); ``chapter`` (title);
    ``ending``; ``omit`` (chapter|ending); ``bare`` (chapter|ending); ``two`` (what is
    marked: menu, chapter, ending, or line; the two marks' lines)."""
    if form == "chapter":
        title = str(args[0]) if args else "Festival Night"
        return ("a flowchart line above a chapter takes only hidden and no jump, because the "
                f'chapter line gives the title. Remove "{show(title)}".')
    if form == "ending":
        return ("a flowchart line above an ending takes only hidden: the ending line gives the "
                "title, and endings are never jump targets.")
    if form == "omit":
        kind = str(args[0]) if args else "chapter"
        article = "an" if kind == "ending" else "a"
        return ("flowchart omit leaves a menu off the flowchart, so it goes right above a menu:, "
                f"not above {article} {kind}.")
    if form == "bare":
        if args and args[0] == "ending":
            return ("endings are always on the flowchart, so flowchart alone does nothing here. "
                    "Add hidden, or remove the line.")
        return ("chapters are always on the flowchart, so flowchart alone does nothing here. "
                "Add hidden or no jump, or remove the line.")
    if form == "two":
        kind, first, second = (args + ("menu", 30, 31)[len(args):])[:3]
        what = f"this {kind}" if kind != "line" else "the line below"
        return (f"{what} has two flowchart lines (lines {first} and {second}). Put them on one "
                'line, e.g. flowchart "Where to?" hidden.')
    next_form, line = (args + ("say", 31)[len(args):])[:2]
    if next_form == "nothing":
        what = "nothing comes after it here"
    else:
        kind = _NEXT_FORMS.get(str(next_form))
        if kind is None:
            kind = f"{'an' if str(next_form)[:1] in 'aeiou' else 'a'} {next_form} line"
        what = f"the next line here is {kind} (line {line})"
    return ("a flowchart line marks the menu, chapter, or ending right below it, but "
            f"{what}. Move it right above the menu:.")


def _e263(form: str = "long", *args: object) -> str:
    """``empty``; ``long`` (count, limit); ``tags``."""
    if form == "empty":
        return "the flowchart title is empty."
    if form == "tags":
        return ("flowchart titles are shown as written, so they can't use text tags such as {b} "
                'or {var}. Write {{ for a "{".')
    count, limit = (args + (140, 120)[len(args):])[:2]
    return f"the flowchart title has {count:,} characters; keep it to {limit:,}."


def _e264(name: str = "rivr", suggestion: str | None = "river") -> str:
    text = f'there is no label named "{show_name(name)}".'
    if suggestion is not None:
        text += " " + _did_you_mean(suggestion, name)
    return (f"{text} flowchart forget takes a label name, or nothing to forget the whole "
            "flowchart.")


_FLOWCHART_SMALLER = ('Leave small menus off with flowchart omit, or set [flowchart] menus = '
                      '"marked".')


def _e265(form: str = "nodes", count: int = 3204, limit: int = 3000) -> str:
    """``nodes``; ``paths``; ``names`` (persistent names); ``complex`` (work units)."""
    if form == "complex":
        return ("this story's flowchart is too complex to work out: following its jumps and "
                f"calls took more than {limit:,} steps. {_FLOWCHART_SMALLER} To play without "
                "the Flowchart page, set [flowchart] enabled = false.")
    what = {"paths": "paths between boxes",
            "names": "boxes and paths to remember in the persistent data"}.get(form, "boxes")
    return (f"this story's flowchart has {count:,} {what}; the engine allows {limit:,}. "
            f"{_FLOWCHART_SMALLER}")


def _w150(kind: str = "scene", name: str | None = "Old Ending", label: str = "old_ending",
          marked: bool = True) -> str:
    """``scene`` (title, label); ``chapter``/``ending`` (name); ``menu`` (label, marked)."""
    if kind == "scene":
        what = f'scene "{show(str(name))}" (label {show_name(label)})'
    elif kind == "menu":
        what = f"the menu in label {show_name(label)}"
    else:
        what = f"{kind} {show_name(str(name))}"
    if marked:
        fix = ", or remove its flowchart line."
    elif kind == "menu":
        fix = ", or put flowchart omit above it."
    else:
        fix = f", or remove its {kind} line."
    return (f"{what} can't be reached from the start of the story, so it stays ??? on the "
            f"flowchart for every player. Add a jump or call that leads to it{fix}")


def _w152(text: str = "{var=lantern_color}", name: str = "lantern_color") -> str:
    return (f"this choice's text is only {show(text)}, so its path on the flowchart reads "
            f'"…". Add a word or two, e.g. "Buy the {{var={show_name(name)}}} one".')


def _w153(label: str = "stall") -> str:
    shown = show_name(label)
    return (f"flowchart forget {shown} does nothing, because label {shown} has no flowchart "
            'boxes in it. Add flowchart scene "Title" as its first line, or name another '
            "label.")


def _e279(game: str = "stargazing") -> str:
    """Headless runs (F23 ``02`` §4.1; ``run_headless``)."""
    return (f"minigame {show_name(str(game))} has no outcome for this headless run. Give one "
            "in the inputs, e.g. finish 3, or give the plugin a test outcome.")


def _h_finish(form: str = "needs", number: int = 4, text: str = "finish", *args: object) -> str:
    """F23 ``02`` §4.2's headless ``finish`` forms (``HeadlessInputError``, uncoded):
    ``needs``, ``value``, ``change``, ``name`` (F22's or F21's own text after the input),
    ``elsewhere`` (where: ``line`` or ``menu``, file, line). Drafted here (``06`` G2):
    ``long`` (over 10,000 characters) and ``many`` (over 100 changes)."""
    shown = f'input {number} "{echo(str(text))}"'
    if form == "value":
        return (f"{shown} gives a result that isn't a plain value. Write text in quotes "
                '("red"), a number, True, False, None, a list, or a dictionary with text keys.')
    if form == "change":
        return (f"{shown} has a change that isn't points name += N, -= N, or = N, unlock tip "
                "name, unlock item name, or lock item name.")
    if form == "name":
        return f"{shown}: {args[0] if args else ''}"
    if form == "long":
        return f"{shown} is longer than 10,000 characters, the most one input can be."
    if form == "many":
        return f"{shown} has more than 100 changes, the most one input can have."
    if form == "elsewhere":
        where, ref, line = (args + ("line", "script/main.vns", 9)[len(args):])[:3]
        return (f"{echo(str(text))} at the {where} at {show(str(ref))}, line {line}, but there "
                "is no minigame there.")
    return f'{shown} needs a result, e.g. finish 3 or finish "red".'


def _h_input(number: int = 2, text: str = "chose 2", form: str = "unknown") -> str:
    """The headless runner's input that isn't one (``HeadlessInputError``, uncoded). F31
    (``04`` §6.6, ``07`` I-5): ``player deletes|restores <name>``; ``form`` ``meta_name`` is
    such an input naming a file no ``file`` line uses (drafted here)."""
    shown = f'input {number} "{echo(str(text))}"'
    if form == "meta_name":
        return (f"{shown} names a file no file line uses. The player can delete or restore "
                "only the files the story writes, such as hana.chr.")
    return (f"{shown} isn't advance, choose N, back N, forward N (N from 1 to 1000), jump and "
            "a box id, finish and a result, or player deletes or restores and a file name.")


def _h_jump(form: str = "needs", number: int = 3, node_id: str = "scene:stall",
            reason: str = "scheme_mismatch", limit: int = 1_200) -> str:
    """F20 ``04`` §7.6's headless ``jump <id>`` refusals (``HeadlessInputError``, uncoded;
    SEC-F20-13): ``needs`` (no id), ``long`` (over ``limit``, ``JUMP_ID_MAX``), ``unknown``,
    ``no_state``, ``refused`` (``reason``: the restore result's word). The id only through
    ``echo()``; "box", not "node" (PR-F02-31, as E265 and W153)."""
    shown = f'"{echo(str(node_id))}"'
    if form == "needs":
        return f'input {number} "jump" needs a box id, for example jump scene:stall.'
    if form == "long":
        return (f"input {number}: the box id after jump is longer than {limit:,} "
                "characters, so no flowchart box has it.")
    if form == "unknown":
        return (f"input {number}: the flowchart has no box {shown}. Box ids look like "
                "scene:<label>, chapter:<name>, menu:<id>, or ending:<name>.")
    if form == "no_state":
        return (f"input {number}: there is no state to jump to at {shown} yet. Reach it "
                "in an earlier run with the same flow holder first.")
    return f"input {number}: couldn't jump to {shown}: {reason}."


TEMPLATES: dict[str, Callable[..., str]] = {
    # 5.1 Files and characters
    "E01a": lambda: f"this file isn't saved as UTF-8. {_UTF8_FIX}",
    "E01b": lambda ref, enc: f"{show(ref)} is saved as {enc}. {_UTF8_FIX}",
    "E02": lambda ref: (f"{show(ref)} doesn't look like a text file. "
                        "Script files must be plain text."),
    "E03": lambda ch: (f"this line contains an invisible character ({codepoint(ch)}). "
                       "Delete it; it probably came from copied text."),
    "E03b": lambda ch, in_py_string=False: (
        f"this line contains a hidden text-direction character ({codepoint(ch)}), which can "
        "make code look different from what runs. Delete it; it is allowed only inside "
        "dialogue and narration."
        + (f" In a Python string, write \\u{ord(ch):04x} instead." if in_py_string else "")),
    "E04": lambda ch: (f"this line contains a hidden line-separator character "
                       f"({codepoint(ch)}). Delete it, and press Enter if you want a new "
                       "line there."),
    "E05": lambda ref: (f"{show(ref)} is larger than 16 MB. "
                        "Split it into several files and include them."),
    "E05b": lambda: ("The story's files add up to more than 256 MB, which is the limit. "
                     "Remove unneeded includes."),
    "E06": lambda: ("The story includes more than 1,000 .vns files, which is the limit. "
                    "Combine some of them."),
    "E06b": lambda: ("The story has more than 1,000,000 statements, which is the limit. "
                     "Remove unneeded includes."),
    "E06c": lambda: ("The story has more than 250,000 pieces of Python ($ lines, conditions, "
                     "define values), which is the limit. Combine repeated Python."),
    "E06d": lambda: ("The story's Python adds up to more than 4,000,000 characters, which is "
                     "the limit. Keep large data out of the script."),
    "E07": _e07,
    "E08": lambda written: (f'script/main.vns doesn\'t exist. Did you mean "{show(written)}"? '
                            "Rename it to main.vns; the story always begins there."),
    "E08b": lambda: f"script/main.vns {_CANT_READ}",
    "E08c": lambda: ("script/main.vns is a folder. The story must begin in a file named "
                     "main.vns."),
    "E08d": lambda ref="script/main.vns": (
        f"{show(ref)} points to a place outside the game folder, which is not allowed. "
        "Keep the story files in the game's script folder."),
    # I-11 (G5): drafted here; the narrative designer owns the final text.
    "E08e": lambda folder: (f"script/ overlaps the game's {show(folder)}/ folder, where the "
                            "engine keeps other files, which is not allowed. Keep the story "
                            "files in a script folder of their own."),
    "E09": _e09,
    "W02": lambda ref: (f"{show(ref)} is not included, so it is not part of the game. "
                        f'Add include "{show(ref.removeprefix("script/"))}" to a file that is.'),
    "W02s": lambda count: _summary(count, ".vns files are not included."),
    "W02b": lambda: ("script/ holds more than 10,000 files and folders, so only the first ones "
                     "were checked for files that aren't included."),
    # 5.2 Indentation
    "E10": _e10,
    "E10c": lambda: ("this line is indented with both tabs and spaces. "
                     "Use one or the other in each file."),
    "E11": lambda ch: (f"this line is indented with {_SPACE_NAMES.get(ch, 'an unusual space')} "
                       f"({codepoint(ch)}), which looks like a space but isn't one. Retype "
                       "the indentation with spaces or a tab."),
    "E12": _e12,
    "E13": lambda: ("this line is indented more than the line above, but the line above "
                    "doesn't start a block. Remove the extra indentation."),
    "E14": _e14,
    "E15": lambda: ("this line is inside more than 50 blocks, which is the limit. Move some "
                    "inner lines into their own label and call it."),
    "E16": lambda: ("this line is longer than 10,000 characters, which is the limit. "
                    "Split it over several lines."),
    # 5.3 Statements
    "E20": lambda: "this label has no name. Write a name before the colon, e.g. label rooftop:",
    "E21": _e21,
    "E22": lambda: ("nothing can follow the : on the same line. "
                    "Move the rest to the next line, indented."),
    "E23": lambda brackets: (f'labels can\'t take values in brackets. Remove "{show(brackets)}" '
                             "and set variables with $ lines."),
    "E23b": lambda: "a label name is one word. Join the words with _, e.g. label chapter_one:",
    "E24": lambda name: (f'label "{show(name)}" is indented, but labels start at the beginning '
                         "of the line. Remove its indentation."),
    "E25": _e25,
    "E26": _e26,
    "E26b": _e26b,
    "E26c": _e26c,
    "E30a": lambda word, suggestion: (f'"{show(word)}" is not a statement. '
                                      f'Did you mean "{show(suggestion)}"?'),
    "E30b": lambda word, line: (f'"{show(word)}" is not a statement, and this line has no text '
                                "in quotes. If it is narration or dialogue, put the text in "
                                f'straight quotes: "{show(line)}"'),
    "E30d": lambda start: (f'this line starts with "{show(start)}", which isn\'t a statement, '
                           "a name, or a quote. Put narration or dialogue in straight quotes."),
    "E31": lambda word: (f'"{show(word)}" is not a statement. Statement words are lower case: '
                         f"{word.lower()}."),
    "E31b": _e31b,
    "E32": lambda word: (f'"{word}" is not available yet in this engine version. Remove the '
                         "line or comment it out with # for now."),
    "E32b": lambda word: (f'"{word}" can\'t start a line. It goes after a statement, e.g. '
                          f"{_MODIFIER_EXAMPLES.get(word, 'show hana at left')}."),
    "E33": lambda: ("python: blocks aren't supported. Write each line of Python as its own "
                    "$ line."),
    "E34": lambda: ("this elif has no if directly above it at the same indentation. Line it "
                    "up under its if, or change it to if."),
    "E35": lambda: ("this else has no if directly above it at the same indentation. Line it "
                    "up under its if."),
    "E36": lambda line: (f"this if already has an else (line {line}). Remove one, or change "
                         "the first to elif with a condition."),
    "E37": lambda line: f"elif can't come after else (line {line}). Move it above the else.",
    "E38": lambda condition: (f"else doesn't take a condition. Use elif {show(condition)}: "
                              "instead."),
    "E38b": lambda: "write elif instead of else if.",
    "E39": lambda keyword: (f"{keyword} needs a condition before the colon, e.g. "
                            f"{keyword} trust >= 3:"),
    "E40": lambda: ("this line is outside any label, so the story can never reach it. Add "
                    "label <name>: above it and indent it."),
    "E41": lambda keyword: f"{keyword} needs the name of a label, e.g. {keyword} bridge.",
    "E41b": lambda keyword, name: (f"label names aren't written in quotes. "
                                   f"Write {keyword} {show(name)}."),
    "E42": _e42,
    "E43": _e43,
    "E44":lambda rest: f'return doesn\'t take anything after it. Remove "{show(rest)}".',
    # 5.4 Text
    "E50": _e50,
    "E51": lambda: ('text goes between double quotes, not single quotes. Write "like this"; '
                    "apostrophes inside need no change."),
    "E52": _e52,
    "E53": lambda rest: (f"this line has more after the closing quote: {show(rest)} "
                         'Write a quote inside the text as \\".'),
    "E54": lambda: 'this quote is never closed. Add " at the end of the text.',
    "E54b": lambda: ("this quote is never closed: the text ends with a curly quote ”. "
                     'End it with a straight quote " instead.'),
    # 5.5 Names and dialogue
    "E60": lambda name, role: (f'"{show(name)}" is a statement word, so it can\'t be {role}. '
                               f'Pick another name, such as "my_{show(name)}".'),
    "E61": lambda name: (f'"{show(name)}" is a word Python uses, so it can\'t be a name. '
                         f'Pick another name, such as "my_{show(name)}".'),
    "E62": lambda name: (f'"{show(name)}" is a name the engine uses. '
                         f'Pick another name, such as "my_{show(name)}".'),
    "E63": lambda name: (f'"{show(name)}" starts with _, and those names are kept for the '
                         "engine. Remove the _."),
    "E64": _e64,
    "E64b": lambda name, ch: (f'the name "{show(name)}" contains an invisible character '
                              f"({codepoint(ch)}), so it looks like a different name. "
                              "Retype the name without it."),
    "W04": lambda name, script: (f'the name "{show_name(name)}" mixes Latin and {script} letters, '
                                 "so it can look like another name. Type every letter in one "
                                 "alphabet."),
    # I-10's example text; the narrative designer owns the final wording.
    "W04s": lambda count: _summary(count, "names mix alphabets."),
    "E70": _e70,
    "E71":lambda name, rest: (f"{show(name)}'s line has no text in quotes. Put the text in "
                               f'straight quotes: {show(name)} "{show(rest)}"'),
    "E72": lambda chunk, speaker: (f'"{show(chunk)}" can\'t come before the text. Words there '
                                   "use letters, digits, and _ only, e.g. "
                                   f'{show(speaker)} sad "…".'),
    "E73": lambda count, speaker: (f"there are {count} words between {show(speaker)} and the "
                                   "text, but at most 4 are allowed. Check that the text "
                                   'starts with a straight quote ".'),
    "E74": lambda: ("this line of text ends with :, which only menu choices do. Remove the :, "
                    "or put the choice in a menu: block."),
    # 5.6 Python and define
    "E80": lambda text: _python("E80", text),
    "E81": lambda text, subject=None: _python("E81", text, subject),
    "E82": lambda text: _python("E82", text),
    "E83": lambda word: f'"{word}" is a statement, not Python. Remove the $.',
    "E84": lambda: ("this $ line is empty. Write Python after $, e.g. $ trust = 0, or remove "
                    "the line."),
    "E86": lambda role: _too_big("E86", role),
    "E86b": lambda role: _too_big("E86b", role),
    "W03": lambda text: f"Python warns: {_finish(text)}",
    "W03b": lambda count: f"…and {count} more Python warnings.",
    # E46 gets the line's assignment from ``misplaced_args``, as F03's E46b does; 02's
    # E46 text doesn't use it.
    "E46": lambda shown=None: ("define sets a name once, before the story begins, so it must "
                               "be at the top level. To change a value during the story, use "
                               "$ name = value."),
    "E47": _e47,
    "E48": _e48,
    "E48b": lambda name, word="define": (f"{word} {show_name(name)} uses itself, so it can't "
                                         "be set. Write its value without using "
                                         f"{show_name(name)}."),
    "E49": _e49,
    # F03 default (F03 02-script.md §5.1)
    "E46b": _e46b,
    "E47b": _e47b,
    "E47c": _e47c,
    # F03 $ bindings (F03 02-script.md §5.1; raised by bindings.py with E62 and E63 above)
    "E87": _e87,
    "E88": _e88,
    "W05": _w05,
    # F03 run (F03 02-script.md §5.3; raised through engine/runtime/errors.py)
    "E85": _e85,
    "E85b": _e85b,
    "E85c": _e85c,
    "E85d": _e85d,
    "E85e": _e85e,
    "E85f": _e85f,
    "E85g": lambda suffix="": (f"this divides by zero{suffix}. Check the number you divide by "
                               "first, e.g. if days > 0:."),
    "E85i": lambda suffix="": ("this Python ran helpers inside each other too deeply, so a "
                               f"helper may call itself without end{suffix}. Check the helpers "
                               "in define that this line uses."),
    "E85j": _e85j,
    "E85m": _e85m,
    "E85n": _e85n,
    "E45": _e45,
    "E45b": _e45b,
    # F03 launch (F03 02-script.md §5.2; raised through engine/runtime/launch.py,
    # character.py, modules.py) and E75h (§5.3, interpreter.py)
    "E75": _e75,
    "E75b": _e75b,
    "E75c": _e75c,
    "E75d": _e75d,
    "E75e": _e75e,
    "E75f": _e75f,
    "E75g": lambda: 'name_from takes the variable\'s name in quotes: name_from="hana_name".',
    "E75h": _e75h,
    "E85k": _e85k,
    "E85l": _e85l,
    "E89": _e89,
    "E89b": lambda: 'module takes the module\'s name in quotes, e.g. module("math").',
    "E89c": _e89c,
    # 5.7 Includes and totals
    "E90": lambda: ("include can't be inside a label or block, because a file belongs to the "
                    "game from the start. Move it to the top level."),
    "E91": _e91,
    "E92": _e92,
    "E93": _e93,
    "E94": lambda written: (f'can\'t include "{show(written)}": that is a folder. Include each '
                            ".vns file in it."),
    "E95": lambda written: (f'the file name goes in quotes. Write include "{show(written)}".'),
    "E96": lambda: ("include takes one file name, but this line has more after it. Put each "
                    "file on its own line."),
    "E97": lambda written, ref: (f'can\'t include "{show(written)}" because {show(ref)} '
                                 f"{_CANT_READ}"),
    "E99": lambda: ("Some checks (labels, characters) were skipped because a file couldn't be "
                    "read. Launch again after fixing it."),
    "E100": lambda count: f"…and {count} more problems. Fix these and launch again.",
    "W01": lambda: "No story found: script/main.vns doesn't exist.",
    # F05 (F05 02-script.md §5): text tags (load), {var} (load, run), the textbox (launch).
    "E160": _e160,
    "E161": _e161,
    "E162": _e162,
    "E163": _e163,
    "E164": _e164,
    "E165": _e165,
    "E166": _e166,
    "E167": _e167,
    # F29 text effects (01 §5.3): E297 (texttags.py), W185 (checks.py step 6e, dev)
    "E297": _e297,
    "W185": _w185,
    "E168": _e168,
    "E169": _e169,
    "E170": _e170,
    "E171": _e171,
    "W40": _w40,
    "W40b": lambda count: f"…and {count} more lines need more than one text box.",
    "W41": _w41,
    "W42": _w42,
    "W42s": lambda count: (f"…and {count} more {{var}} names that no default or define "
                           "sets."),
    "W43": _w43,
    "W44": _w44,
    "W45": _w45,
    "W46": _w46,
    # F04 load (F04 02-script.md §5.1)
    "E110": _e110,
    "E111": lambda word: (f"scene doesn't take {word}, because a background always fills the "
                          "screen. To place a picture, use show."),
    "E112": _e112,
    "E113": lambda word: f"{word} needs {_NEEDS.get(word, 'a value after it')}.",
    "E114": lambda word: f"this line has {word} twice. Keep one.",
    "E115": lambda part: f'with must come last on the line. Move "{show(part)}" to the end.',
    "E116": _e116,
    "E117": _e117,
    "E118": lambda: ("behind and layer can't be used together, because behind puts the sprite "
                     "on the other sprite's layer. Keep one of them."),
    "E119": _e119,
    "E120": _e120,
    "E121": _e121,
    "E122": _e122,
    "E123": lambda written, quoted=False: (
        f"layer takes a whole number from {LAYER_RANGE[0]} to {LAYER_RANGE[1]}, e.g. layer 10, "
        f"but this has {_has(written, quoted)}."),
    "E124": lambda written, quoted=False: (
        f"zoom takes a number from {ZOOM_RANGE[0]:g} to {ZOOM_RANGE[1]:g}, e.g. zoom 1.5 (1 is "
        f"normal size), but this has {_has(written, quoted)}."),
    "E125": lambda: "flip takes on or off: flip on mirrors the sprite, flip off undoes it.",
    "E126": _e126,
    "E127": _e127,
    "E130": lambda: ("image declares a picture once for the whole game, so it must be at the "
                     "top level. Move it out of the label."),
    "E131": _e131,
    "E132": _e132,
    "E133": _e133,
    # F04 launch (F04 02-script.md §5.3; raised through engine/runtime/character.py)
    "E135": _e135,
    # F04 launch warnings (§5.3; engine/runtime/stage_check.py). W10 here is cut at 1,000
    # characters like every template; stage_check uses ``w10_text``, which cuts each line.
    "W10": w10_text,
    "W10b": lambda limit=20_000: (f"Image scan stopped after {limit:,} files; image names "
                                  "beyond that were not checked."),
    "W10s": lambda count=50: (f"…and {count:,} more stage warning{'' if count == 1 else 's'} "
                              "not shown."),
    "W11": _w11,
    "W12": _w12,
    "W12b": _w12b,
    "W13": _w13,
    "W16": _w16,
    # F04 run (§5.4): the dev INFO line of PR-F04-12 (engine/runtime/stage.py)
    "I-stage-words": lambda tag="hana", words="pout": (
        f'{show_name(tag)}\'s words "{show(words)}" changed nothing, because {show_name(tag)} '
        "isn't on stage."),
    # F04 run (§5.4): a restored stage names a position config.toml no longer has
    # (engine/render/stage.py, through runtime/stage.py: position_gone_message)
    "W15": lambda tag="daichi", name="stall_spot": (
        f'A restored game puts {show_name(tag)} at the position "{show(name)}", which '
        f"config.toml no longer has, so {show_name(tag)} is shown at center."),
    # F08 load (F08 02-script.md §5.1; engine/script/audio.py and audio_checks.py)
    "E140": _e140,
    "E141": _e141,
    "E142": _e142,
    "E143": lambda file, reason: (f'can\'t use "{show(file)}": {reason}. Paths start in the '
                                  'audio folder and use /, e.g. "bgm/theme.ogg".'),
    "E144": lambda file: (f'paths start inside the audio folder, so write "{show(file[6:])}", '
                          f'not "{show(file)}".'),
    "E145": lambda file: (f'"{show(file)}" needs the file\'s extension, e.g. '
                          f'"{show(file)}.ogg".'),
    "E146": _e146,
    "E147": _e147,
    "E148": _e148,
    "E149": _e149,
    "E150": _e150,
    "E151": _e151,
    "W20": _w20,
    "W20s": lambda count=5: f"…and {count} more warnings about voices and audio files.",
    "W23": _w23,
    "W24": _w24,
    # F08 run (engine/runtime/audio.py; 04 §6.3): a 17th looping effect is refused. 02 leaves
    # the text open (06 G4); drafted from the nearest form for the narrative designer (I-14).
    "W-sound-loops": lambda file="sfx/rain.ogg", limit=16: (
        f'"{show(file)}" doesn\'t play, because {limit} sounds are already looping. Stop one '
        'with stop sound first.'),
    # F07 load (F07 01-design.md §5.3; engine/script/menu.py, texttags.py E175)
    "E172": lambda: ('this menu has no choices. Under the question, add choices like "Go left": '
                     "with that choice's lines indented under it."),
    "E173": lambda count=7: (f"this menu has {count} choices, but a menu shows at most 6. Move "
                             "the rarer ones into a second menu behind a choice such as "
                             '"Something else...":.'),
    "E174": _e174,
    "E175": _e175,
    "E176": lambda: ("this choice has no text, so the player couldn't see it. Write its words "
                     "between the quotes."),
    "E177": lambda: ("menu takes nothing else on its line. Put the question on the first line "
                     'inside the menu, e.g. hana "Where to?"'),
    # F51 timed choices (01 §5): load E368–E370 (menu.py); W257 (checks.py step 6f, dev)
    "E368": _e368,
    "E369": _e369,
    "E370": lambda: ("the timeout choice can't have an if: when time runs out, it must be "
                     "there to pick. Remove the if, or mark a choice without one as timeout."),
    "W257": _w257,
    # F59 checks on choices (SPEC §4): load E408, E409 (choicecheck.py)
    "E408": _e408,
    "E409": _e409,
    # F07 run (engine/runtime/menu.py)
    "E178": lambda locked=False: (
        f"every choice in this menu is {'locked' if locked else 'hidden'}, because all their "
        "conditions are false, so the player can't pick anything. Add a choice without if, "
        "such as \"That's all\":."),
    # F07 launch (F07 step 4: app/text_check.py W47, app/choices.py W48)
    "W47": _w47,
    "W48": _w48,
    # F06 (SPEC §3): E179 where Character(...) runs (launch for define, run for $;
    # engine/runtime/character.py); W49 (area audio) comes with F06 step 2.
    "E179": _e179,
    "W49": _w49,
    # F09 (01 §5.6): load E192–E198 (effects.py, checks.py), constructors E199, launch E190,
    # E191, E194's launch form, W60 (runtime/transitions.py); W61, W62 (presentation).
    "E190": _e190,
    "E191": _e191,
    "E192": _e192,
    "E193": _e193,
    "E194": _e194,
    "E195": _e195,
    "E196": _e196,
    "E197": _e197,
    "E198": _e198,
    "E199": _e199,
    "W60": _w60,
    "W61": _w61,
    "W62": _w62,
    # F28 glitch effects (01 §5.3; 07 I-14): load E294 (glitch.py); W182, W183 (stage) and
    # W184 (dev, run) through runtime/glitch.py from F28 s3. Drafts per the section comment.
    "E294": _e294,
    "W182": _w182,
    "W183": _w183,
    "W184": _w184,
    # F30 fourth-wall tricks (01 §5.4): load E300, E301 (fourthwall.py, texttags.py), E302
    # (chapter.py; launch, runtime/character.py); W188 (run), W189, W190 (dev launch, F30 s5).
    "E300": _e300,
    "E301": _e301,
    "E302": _e302,
    "W188": _w188,
    "W189": _w189,
    "W189s": lambda count=4: _summary(count, "lines use {username}."),
    "W190": lambda: _W190,
    "W190s": lambda count=2: _summary(count, "lines read identity."),
    # F32 dynamic UI (01 §5.2; 04 §12): load E319–E321 (ui.py); W204, W206, W207 (app/looks.py,
    # area ui, F32 s4); W205 (restore, area runtime, F32 s3). Drafts per the section comment.
    "E319": _e319,
    "E320": _e320,
    "E321": _e321,
    "W204": _w204,
    "W205": _w205,
    "W206": _w206,
    "W207": _w207,
    # F31 meta files (01 §5.2; 04 §11): load E309–E315 (metafiles.py, checks.py step 12; E314
    # whole game); run W196–W198 (app/metafiles.py, F31 s4), W199, W200 (runtime/metafiles.py,
    # F31 s3). Drafts per the section comment.
    "E309": _e309,
    "E310": _e310,
    "E311": _e311,
    "E312": _e312,
    "E313": _e313,
    "E314": _e314,
    "E315": _e315,
    "W196": lambda: (f"{_META_FOLDER} isn't a real folder (it is a link or a file), so file "
                     "lines do nothing this session and file exists gives False."),
    "W197": lambda: (f"{_META_FOLDER} can't be written (the game may be installed in a "
                     "read-only folder), so file write and file delete do nothing this "
                     "session."),
    "W198": _w198,
    "W199": lambda: (f"the story made {META_CHANGES_MAX} file changes this session, the most "
                     "allowed, so later file write and file delete lines do nothing until the "
                     "game restarts."),
    "W200": _w200,
    # F12 persistent data (01 §5.4): run E180–E183 (engine/runtime/errors.py), load E184
    # (default.py, checks.py), launch E185 and W56 (engine/runtime/launch.py).
    "E180": _e180,
    "E181": _e181,
    "E182": _e182,
    "E183": _e183,
    "E184": _e184,
    "E185": _e185,
    "W56": _w56,
    # F18 chapters (SPEC §3): load E220–E223, E224 (whole game).
    "E220": _e220,
    "E221": _e221,
    "E222": _e222,
    "E223": _e223,
    "E224": _e224,
    # F22 character stats (SPEC §3): load E230–E235, run E236, W120 (dev, area runtime).
    "E230": _e230,
    "E231": _e231,
    "E232": _e232,
    "E233": _e233,
    "E234": _e234,
    "E235": _e235,
    "E236": _e236,
    "W120": _w120,
    # F62 visible meters, round 1: load E411–E416, W290 (points.py, meterranks.py)
    "E411": _e411,
    "E412": _e412,
    "E413": _e413,
    "E414": _e414,
    "E415": _e415,
    "E416": _e416,
    "W290": _w290,
    # F62 round 2: load E417, E418 (showmeter.py), W291–W293 (showmeter.check_story)
    "E417": _e417,
    "E418": _e418,
    "W291": _w291,
    "W292": _w292,
    "W293": _w293,
    # F14 rollback (04 §6.2): load E200–E203 (rollback.py), E204 (attach_fixed). Drafts (G3).
    "E200": lambda: (f"rollback needs one word after it: {_ROLLBACK_WORDS}. Write "
                     '"rollback block" to stop rollback here.'),
    "E201": _e201,
    "E202": _e202,
    "E203": lambda: ("rollback doesn't take a block. Remove the \":\" and un-indent the lines "
                     "under it."),
    "E204": _e204,
    "W90": _w90,                        # run (runtime/rollback.py, area runtime). Draft (G3).
    # F17 NVL mode (01 §5.4): load E210, E211 (nvl.py); launch W100, W101, W101s
    # (app/text_check.py); run W102 (runtime/nvl.py, dev). Drafts for the narrative designer.
    "E210": _e210,
    "E211": _e211,
    "W100": _w100,
    "W101": _w101,
    "W101s": lambda count=5: (f"…and {count:,} more full-screen lines need more than one "
                              "page."),
    "W102": _w102,
    # F19 routes and endings (01 §5.5): load E240–E246, W130 (routes.py, checks.py,
    # bindings.py); launch W131 and run W132, raised in runtime/endings.py; E245's run
    # form, raised in runtime/errors.py (both built). Drafts per the section comment above.
    "E240": _e240,
    "E241": _e241,
    "E242": _e242,
    "E243": _e243,
    "E244": _e244,
    "E245": _e245,
    "E246": _e246,
    "W130": lambda: ("the lines after this ending never run, because ending ends the story. "
                     "Move them above the ending or into another label."),
    "W131": _w131,
    "W132": _w132,
    # F21 codex (01 §5.5): load E250–E255, W140, W142 (codex.py, checks.py, bindings.py).
    # Launch and run E256, run W141 (runtime/codex.py, F21 step 2). Drafts per the section
    # comment above.
    "E250": _e250,
    "E251": _e251,
    "E252": _e252,
    "E253": _e253,
    "E254": _e254,
    "E255": _e255,
    "E256": _e256,
    "W140": _w140,
    "W141": _w141,
    "W142": _w142,
    # F34 CG gallery (01 §5.3): load E342, E344 (gallery.py); E343, E345, W226 (checks.py).
    "E342": _e342,
    "E343": _e343,
    "E344": _e344,
    "E345": _e345,
    "W226": _w226,
    # F35 music room (SPEC §3): load E336 (musicroom.py); E337, E338, W220, W221 (checks.py).
    "E336": _e336,
    "E337": _e337,
    "E338": _e338,
    "W220": _w220,
    "W221": _w221,
    # F36 ending list & scene replay (01 §5.3): load E348, E350, E351, E352 (replay.py,
    # checks.py), E349 (checks.py); run W229 (runtime/replay.py).
    "E348": _e348,
    "E349": _e349,
    "E350": _e350,
    "E351": _e351,
    "E352": _e352,
    "W229": _w229,
    # F37 achievements (SPEC §3): load E339 (achievements.py), E340 (checks.py); run W223
    # (runtime/achievements.py); dev load W224 (checks.py). W225: minigames/messages.py.
    "E339": _e339,
    "E340": _e340,
    "W223": _w223,
    "W224": _w224,
    # F41 script linter (01 §4.1): lint W237–W242 (tools/lint.py findings; never the load).
    "W237": _w237,
    "W238": _w238,
    "W239": _w239,
    "W240": _w240,
    "W241": _w241,
    "W242": _w242,
    # F43 localization (01 §5.4): translation W247–W256 (po.py, translations.py,
    # translatecheck.py, the language setting, check/build; never the script load).
    "W247": _w247,
    "W248": _w248,
    "W249": _w249,
    "W250": _w250,
    "W251": _w251,
    "W252": _w252,
    "W253": _w253,
    "W254": _w254,
    "W255": _w255,
    "W256": _w256,
    # F23 minigames (02 §4.1): load E270, E271 (minigame.py, checks.py; E270's $ form
    # pycheck.py); run E272 (runtime/minigame.py, F23 s2). Drafts per the section comment.
    "E270": _e270,
    "E271": _e271,
    "E272": _e272,
    # Run E275, E276 (runtime/minigame.py, F23 s2; also s4's host) and the headless E279
    # (runtime/headless.py). Drafts per the section comment.
    "E275": _e275,
    "E276": _e276,
    "E277": _e277,                  # F23 s4 (moved from runtime/minigame.py)
    "E279": _e279,
    # F20 flowchart (02 §5): parse E260, E263, E261's top form (flowchart.py); load E261's
    # first form, E262, E264 (flowchart.iter_attach_marks). Drafts per the section comment.
    "E260": _e260,
    "E261": _e261,
    "E262": _e262,
    "E263": _e263,
    "E264": _e264,
    # F20 s2 (02 §5; 04 §7.1 step 10): the whole-game E265 and the dev load warnings
    # W150–W153 (flowgraph.py). Drafts per the section comment.
    "E265": _e265,
    "W150": _w150,
    "W151": lambda: ("the flowchart can't tell where this line goes, so it draws no path from "
                     "here. The story still plays; use jump or call with a label name to draw "
                     "the path."),
    "W152": _w152,
    "W153": _w153,
    # F20 s9 follow-up (04 §12): the dev run warnings W154, W155 (area save; app/flowchart.py
    # through runtime.errors). The node id only through echo(); W155's reason is a dev reason
    # word (persist/nodestates.py's NodeRead.reason or app/flowchart.py's), never file text.
    "W154": lambda node="scene:stall": (
        f"the flowchart state for {echo(node)} is too large to keep, so this point can't be "
        "jumped to."),
    "W155": lambda node="scene:stall", reason="no state is kept for it": (
        f"couldn't jump to {echo(node)}: {reason}"),
    "H-finish": _h_finish,
    "H-jump": _h_jump,                                      # F20 04 §7.6 (runtime/headless.py)
    # F07 headless runner (04 §5.4; HeadlessInputError, not game errors). Drafts (O4).
    "H-choose-range": lambda n=4, ref="script/main.vns", line=6, count=3: (
        f"choose {n} at the menu at {show(ref)}, line {line}, but only {count} "
        f"choice{'' if count == 1 else 's'} can be picked there."),
    "H-advance-menu": lambda ref="script/main.vns", line=6: (
        f"advance at the menu at {show(ref)}, line {line}, but a menu waits for a choice. "
        "Write choose N."),
    "H-choose-line": lambda n=2, ref="script/main.vns", line=5: (
        f"choose {n} at the line at {show(ref)}, line {line}, but there is no menu there."),
    # F09 headless runner (07 I-3): a loop of waits with no line or choice. Not a game error.
    "H-waits": lambda count=10_000, ref="script/main.vns", line=6: (
        f"the story waited {count:,} times in a row with no line or choice, last at "
        f"{show(ref)}, line {line}, so the headless run stopped. A loop of pauses and "
        "transitions only ends when a player leaves it."),
    "H-input": _h_input,                                    # F23, F20, F31
}


def format_message(code: str, args: tuple = ()) -> str:
    """The message text of ``code`` (no location prefix), cut to 1,000 characters."""
    return truncate(TEMPLATES[code](*args), SCRIPT_MESSAGE_MAX_CHARS)


# --- Report lines (§7.10) -------------------------------------------------------------------

def problems_head(count: int) -> str:
    """The error screen's first line (§7.10.2)."""
    return f"The script has {count:,} problem{'' if count == 1 else 's'}:"


def todo_line(ref: str, line: int, text: str) -> str:
    """SR-F02-13: ``<file>, line <N>: <comment text>``."""
    return truncate(f"{show(ref)}, line {line}: {show(text)}", SCRIPT_MESSAGE_MAX_CHARS)


def todo_more(count: int) -> str:
    """SR-F02-13's summary past the cap: ``…and 37 more TODO comments.``"""
    return _summary(count, "TODO comments.")


def loaded_line(files: int, labels: int, statements: int, words: int, seconds: float) -> str:
    """PR-F02-40's success line (wording drafted here; ``02`` leaves it open)."""
    def count(n: int, one: str, many: str) -> str:
        return f"{n:,} {one if n == 1 else many}"
    return (f"Loaded story: {count(files, 'file', 'files')}, {count(labels, 'label', 'labels')}, "
            f"{count(statements, 'statement', 'statements')}, {count(words, 'word', 'words')} "
            f"in {seconds:.2f} seconds.")


# A column past this is shown with the window starting _WINDOW_BEFORE characters before it.
_WINDOW_SHIFT_AT = 100
_WINDOW_BEFORE = 80


def _redacted_index(raw: str, text: str, index: int) -> int:
    """Where ``raw[index]`` is in ``text`` (= ``redact(raw)``): after the redacted prefix if
    redaction kept it a prefix, else before the redacted suffix; a column inside a redacted
    path lands at the start of its replacement."""
    before = redact(raw[:index])
    if text.startswith(before):
        return min(len(before), len(text))
    after = redact(raw[index:])
    if text.endswith(after):
        return max(0, len(text) - len(after))
    common = 0
    for a, b in zip(text, before):
        if a != b:
            break
        common += 1
    return common


def source_window(line: str, column: int | None = None) -> tuple[str, int | None]:
    """The display form of a source line and the caret's 0-based offset in it (§7.10.1,
    SEC-F02-09 (b)), in this order: ``redact`` the whole line; tabs become one space; take a
    120-character window holding the column (past column 100 it starts 80 characters before
    it, after a leading ``…``; a cut end gets a trailing ``…``); then ``escape_controls``.
    The caret is recomputed on the redacted, escaped text. ``None`` when there is no column."""
    raw = line.rstrip("\r\n")
    text = redact(raw)
    index: int | None = None
    if column is not None:
        index = _redacted_index(raw, text, max(column - 1, 0))
    text = text.replace("\t", " ")
    start, lead = 0, ""
    if index is not None and index + 1 > _WINDOW_SHIFT_AT:
        start, lead = index - _WINDOW_BEFORE, "…"
    budget = SCRIPT_SOURCE_WINDOW - len(lead)
    body = text[start:]
    if len(body) > budget:
        body = body[:budget - 1] + "…"
    shown = lead + body
    if index is None:
        return escape_controls(shown), None
    offset = len(lead) + index - start
    return escape_controls(shown), len(escape_controls(shown[:offset]))
