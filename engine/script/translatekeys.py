"""Translation keys: every player-visible text of a story and its config, keyed by ids the
engine already has (F43 ``01-design.md`` §5.1, §5.2; ``04-technical.md`` §3, §7.2).

Why this module exists: the game (``translations.TextTable``), ``check``, build, and Studio's
Translate tab must agree on which texts a story has and what each one's key is, so one pure
function builds them. Studio imports it too, so it is standard library plus ``core`` and
``script`` only: no pygame, no runtime, no Tk.

**Keys** (``01`` §5.1). Script texts use ADR-0006 sids: a ``Say`` (narration, dialogue, NVL)
is its sid; a menu's question is the menu sid; a choice is ``<menu sid>#<choice key>``
(ADR-0006 Addendum 1); an ``effect window_title "…"`` is its sid. Everything else is a
prefixed key: ``name:<define>``, ``word:<key>``, ``word:<key>@<style>``,
``word:<key>@playthrough.<N>``, ``value:<text>``, the title keys (``chapter:<n>:heading``,
``ending:<n>:title``, ``route:<n>``, ``tip:<n>:title``, ``tip:<n>:<k>`` (paragraph *k*,
from 1), ``item:…`` likewise, ``codex:category:<text>``, ``gallery:<picture>``,
``track:<n>``, ``replay:<label>``, ``achievement:<n>:title``/``:description``,
``flowchart:<target sid>``), and ``game:title``, ``warning:text``. The builders below are the
only place a key is spelled, so lookups (W3, W5, W6) and the PO file agree.

**Scene and who** (``04`` §7.2 rule 3). A script key's scene is its label (the sid's part
before ``/``); any other key's scene is its prefix (``word``, ``chapter``, ...). Who is the
speaker's define name (``hana``), or ``""``.

**Order** (``01`` §5.2): script order (labels in reading order, statements in pre-order, a
menu's question then its choices), then names (define order) and ``default`` text values,
then words, then titles, then the game's texts. A key appears once (the first wins).

**Originals** are the text as written (tags as written). Codex paragraphs are an exception:
the parser keeps only their parsed body, so the original is the paragraph's plain text.
``effect crash "…"`` keeps only a parsed body too and is not listed (F43 Should; needs the
parser to keep the source).
"""

import ast
import enum
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.constants import MESSAGE_WORD_MAX_CHARS, WINDOW_TITLE_MAX, WORD_MAX_CHARS
from engine.script.fourthwall import TitleEffect
from engine.script.identity import walk_block
from engine.script.limits import CHAPTER_HEADING_MAX, CHAPTER_TITLE_MAX, SCRIPT_MAX_LINE_CHARS
from engine.script.menu import Menu
from engine.script.nodes import Chapter, Define, PythonLine, Say
from engine.script.routes import Ending

if TYPE_CHECKING:
    from engine.core.config_schema import Config
    from engine.script.program import Program

CONFIG_REF: Final = "config.toml"
SCRIPT_SCENE_SEP: Final = "/"
CHOICE_SEP: Final = "#"
STYLE_SEP: Final = "@"
# Every non-script key starts with one of these and ":" (a label never holds ":").
PREFIXES: Final = frozenset({
    "name", "word", "value", "chapter", "ending", "route", "tip", "item", "codex", "gallery",
    "track", "replay", "achievement", "flowchart", "game", "warning"})
TITLE_PLAIN_MAX: Final = 60          # codex, gallery, track, replay, achievement titles
LONG_TEXT_MAX: Final = 2000          # codex paragraphs, achievement descriptions, warning
MESSAGE_WORDS: Final = frozenset({"confirm_main_menu", "confirm_quit"})


class TextKind(enum.Enum):
    """Studio's Kind filter (``01`` §5.1) and the check a translation gets (P5)."""

    LINE = "line"            # story lines, narration, NVL
    QUESTION = "question"    # a menu's question
    CHOICE = "choice"
    NAME = "name"            # Character("…")
    WORD = "word"            # button words
    TITLE = "title"          # chapters, endings, routes, codex, extras, flowchart
    GAME = "game"            # game:title, warning:text
    EFFECT = "effect"        # effect window_title
    VALUE = "value"          # variable texts


SCRIPT_KINDS: Final = frozenset({TextKind.LINE, TextKind.QUESTION, TextKind.CHOICE,
                                 TextKind.EFFECT})


@dataclass(frozen=True, slots=True)
class SourceText:
    """One translatable text of the current story. ``ref`` is ``script/a.vns:42`` (or
    ``config.toml``; None when unknown); ``limit`` the kind's length cap in code points
    (None: no cap of its own)."""

    key: str
    kind: TextKind
    original: str
    scene: str
    who: str = ""
    ref: str | None = None
    limit: int | None = None


# --- Key builders (the only spellings) -----------------------------------------------------------

def line_key(sid: str) -> str:
    """A ``Say``, a menu's question, or an effect: the statement's sid."""
    return sid


def choice_key(menu_sid: str, key: str) -> str:
    return f"{menu_sid}{CHOICE_SEP}{key}"


def name_key(define: str) -> str:
    return f"name:{define}"


def word_key(key: str, *, style: str | None = None, playthrough: int | None = None) -> str:
    """``word:<key>``, a style's ``word:<key>@<style>``, or a playthrough look's
    ``word:<key>@playthrough.<N>`` (``04`` §7.6)."""
    if style is not None:
        return f"word:{key}{STYLE_SEP}{style}"
    if playthrough is not None:
        return f"word:{key}{STYLE_SEP}playthrough.{playthrough}"
    return f"word:{key}"


def value_key(text: str) -> str:
    return f"value:{text}"


def chapter_key(name: str, part: str) -> str:
    """``part`` is ``heading`` or ``title`` (endings likewise with ``ending_key``)."""
    return f"chapter:{name}:{part}"


def ending_key(name: str, part: str) -> str:
    return f"ending:{name}:{part}"


def route_key(name: str) -> str:
    return f"route:{name}"


def codex_key(kind: str, name: str, part: str | int) -> str:
    """``tip:<n>:title`` or ``tip:<n>:<k>`` for paragraph *k* (from 1); items likewise."""
    return f"{kind}:{name}:{part}"


def category_key(text: str) -> str:
    return f"codex:category:{text}"


def gallery_key(picture: str) -> str:
    return f"gallery:{picture}"


def track_key(name: str) -> str:
    return f"track:{name}"


def replay_key(label: str) -> str:
    return f"replay:{label}"


def achievement_key(name: str, part: str) -> str:
    return f"achievement:{name}:{part}"


def flowchart_key(target_sid: str) -> str:
    return f"flowchart:{target_sid}"


GAME_TITLE: Final = "game:title"
WARNING_TEXT: Final = "warning:text"


def key_scene(key: str) -> str:
    """The scene rule 3 groups by: a script key's label, else the key's prefix."""
    head, colon, _ = key.partition(":")
    if colon and head in PREFIXES:
        return head
    return key.partition(CHOICE_SEP)[0].partition(SCRIPT_SCENE_SEP)[0]


def is_script_key(key: str) -> bool:
    head, colon, _ = key.partition(":")
    return not (colon and head in PREFIXES)


# --- Building the list ---------------------------------------------------------------------------

def _ref(file_ref: str, line: int) -> str:
    return f"{file_ref}:{line}"


def _string_value(source: str) -> str | None:
    """The text of a value written as one string literal, else None."""
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    body = tree.body
    if isinstance(body, ast.Constant) and type(body.value) is str:
        return body.value
    return None


def _assigned_strings(source: str) -> Iterator[str]:
    """The texts a ``$`` line assigns as plain string literals (``$ name = "…"``)."""
    if "=" not in source or ('"' not in source and "'" not in source):
        return
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Constant) and type(value.value) is str:
            yield value.value


def _character_name(define: Define) -> str | None:
    """The name a ``Character("…")`` define shows, when written as one string literal."""
    source = define.value.source
    if "Character" not in source:
        return None
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    call = tree.body
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "Character"):
        return None
    arg: ast.expr | None = call.args[0] if call.args else None
    for keyword in call.keywords:
        if keyword.arg == "name":
            arg = keyword.value
    if isinstance(arg, ast.Constant) and type(arg.value) is str and arg.value:
        return arg.value
    return None


def _plain(body: object) -> str:
    """A parsed body's plain text (codex paragraphs keep no source)."""
    spans = body.plain()                                   # type: ignore[attr-defined]
    return "".join(span.text for span in spans)


def _script(program: "Program") -> Iterator[SourceText]:
    for label in program.labels.values():
        scene = label.name
        for stmt, _ in walk_block(label.block):
            ref = _ref(stmt.file.ref, stmt.line)
            if isinstance(stmt, Say):
                yield SourceText(line_key(stmt.sid), TextKind.LINE, stmt.text, scene,
                                 stmt.speaker or "", ref, SCRIPT_MAX_LINE_CHARS)
            elif isinstance(stmt, Menu):
                question = stmt.question
                if question is not None:
                    yield SourceText(line_key(stmt.sid), TextKind.QUESTION, question.text,
                                     scene, question.speaker or "",
                                     _ref(stmt.file.ref, question.line), SCRIPT_MAX_LINE_CHARS)
                for choice in stmt.choices:
                    yield SourceText(choice_key(stmt.sid, choice.key), TextKind.CHOICE,
                                     choice.text, scene, "", _ref(stmt.file.ref, choice.line),
                                     SCRIPT_MAX_LINE_CHARS)
            elif isinstance(stmt, TitleEffect) and stmt.text is not None:
                yield SourceText(line_key(stmt.sid), TextKind.EFFECT, stmt.text, scene, "",
                                 ref, WINDOW_TITLE_MAX)
            elif isinstance(stmt, PythonLine):
                for text in _assigned_strings(stmt.py.source):
                    yield SourceText(value_key(text), TextKind.VALUE, text, "value", "", ref)


def _names_and_values(program: "Program") -> Iterator[SourceText]:
    for define in program.defines:
        name = _character_name(define)
        if name is not None:
            yield SourceText(name_key(define.name), TextKind.NAME, name, "name", define.name,
                             _ref(define.file.ref, define.line), WORD_MAX_CHARS)
    for default in program.defaults:
        text = _string_value(default.value.source)
        if text is not None:
            yield SourceText(value_key(text), TextKind.VALUE, text, "value", "",
                             _ref(default.file.ref, default.line))


def _words(config: "Config") -> Iterator[SourceText]:
    from engine.core.config_schema import word_fields
    fields = word_fields()

    def limit(key: str) -> int:
        return MESSAGE_WORD_MAX_CHARS if key in MESSAGE_WORDS else WORD_MAX_CHARS

    for key, field in fields.items():
        text = getattr(config.words, field.name, None)
        if type(text) is str and text:                  # v1: money is empty until set
            yield SourceText(word_key(key), TextKind.WORD, text, "word", "", CONFIG_REF,
                             limit(key))
    for style, table in config.style.items():
        for key, text in table.words.items():
            yield SourceText(word_key(key, style=style), TextKind.WORD, text, "word", "",
                             CONFIG_REF, limit(key))
    for number, table in sorted(config.playthrough.items()):
        for key, text in table.words.items():
            yield SourceText(word_key(key, playthrough=number), TextKind.WORD, text, "word",
                             "", CONFIG_REF, limit(key))


def _titles(program: "Program") -> Iterator[SourceText]:
    title = TextKind.TITLE
    for stmt in program.iter_statements():
        ref = _ref(stmt.file.ref, stmt.line)
        if isinstance(stmt, Chapter):
            if stmt.heading is not None:
                yield SourceText(chapter_key(stmt.name, "heading"), title, stmt.heading,
                                 "chapter", "", ref, CHAPTER_HEADING_MAX)
            yield SourceText(chapter_key(stmt.name, "title"), title, stmt.title, "chapter",
                             "", ref, CHAPTER_TITLE_MAX)
        elif isinstance(stmt, Ending):
            if stmt.heading is not None:
                yield SourceText(ending_key(stmt.name, "heading"), title, stmt.heading,
                                 "ending", "", ref, CHAPTER_HEADING_MAX)
            yield SourceText(ending_key(stmt.name, "title"), title, stmt.title, "ending", "",
                             ref, CHAPTER_TITLE_MAX)
    for route in program.routes:
        yield SourceText(route_key(route.name), title, route.title, "route", "",
                         _ref(route.file.ref, route.line), CHAPTER_TITLE_MAX)
    for entry in program.codex:
        ref = _ref(entry.file, entry.line)
        yield SourceText(codex_key(entry.kind, entry.name, "title"), title, entry.title,
                         entry.kind, "", ref, TITLE_PLAIN_MAX)
        for k, paragraph in enumerate(entry.paragraphs, start=1):
            yield SourceText(codex_key(entry.kind, entry.name, k), title, _plain(paragraph),
                             entry.kind, "", ref, LONG_TEXT_MAX)
    for category in program.codex_categories:
        if category.text is not None:
            yield SourceText(category_key(category.text), title, category.text, "codex", "",
                             None, TITLE_PLAIN_MAX)
    for picture in program.gallery:
        yield SourceText(gallery_key(picture.picture), title, picture.title, "gallery", "",
                         _ref(picture.file, picture.line), TITLE_PLAIN_MAX)
    for track in program.tracks:
        yield SourceText(track_key(track.name), title, track.title, "track", "",
                         _ref(track.script, track.line), TITLE_PLAIN_MAX)
    for replay in program.replays:
        yield SourceText(replay_key(replay.label), title, replay.title, "replay", "",
                         _ref(replay.file, replay.line), TITLE_PLAIN_MAX)
    for achievement in program.achievements:
        ref = _ref(achievement.file.ref, achievement.line)
        yield SourceText(achievement_key(achievement.name, "title"), title, achievement.title,
                         "achievement", "", ref, TITLE_PLAIN_MAX)
        if achievement.description:
            yield SourceText(achievement_key(achievement.name, "description"), title,
                             achievement.description, "achievement", "", ref, LONG_TEXT_MAX)
    for sid, mark in program.flow_marks.items():
        if mark.title is not None:
            yield SourceText(flowchart_key(sid), title, mark.title, "flowchart", "", None,
                             CHAPTER_TITLE_MAX)


def _game(config: "Config") -> Iterator[SourceText]:
    yield SourceText(GAME_TITLE, TextKind.GAME, config.game.title, "game", "", CONFIG_REF)
    warning = config.content_warning.text
    if warning:
        yield SourceText(WARNING_TEXT, TextKind.GAME, warning, "warning", "", CONFIG_REF,
                         LONG_TEXT_MAX)


def source_texts(program: "Program", config: "Config | None" = None) -> tuple[SourceText, ...]:
    """Every translatable text in ``01`` §5.2 order, each key once (the first wins).
    ``config`` None (a tool that read no config): no words and no game texts."""
    seen: set[str] = set()
    out: list[SourceText] = []
    parts: list[Iterator[SourceText]] = [_script(program), _names_and_values(program)]
    if config is not None:
        parts.append(_words(config))
    parts.append(_titles(program))
    if config is not None:
        parts.append(_game(config))
    for part in parts:
        for text in part:
            if text.key not in seen:
                seen.add(text.key)
                out.append(text)
    return tuple(out)


def by_key(texts: "tuple[SourceText, ...]") -> Mapping[str, SourceText]:
    return {text.key: text for text in texts}


__all__ = ["CONFIG_REF", "GAME_TITLE", "PREFIXES", "SCRIPT_KINDS", "SourceText", "TextKind",
           "WARNING_TEXT", "achievement_key", "by_key", "category_key", "chapter_key",
           "choice_key", "codex_key", "ending_key", "flowchart_key", "gallery_key",
           "is_script_key", "key_scene", "line_key", "name_key", "replay_key", "route_key",
           "source_texts", "track_key", "value_key", "word_key"]
