"""``ask_text``'s pure rules (F52 ``01`` §5, ``04`` §11 P6).

Why this module exists: the argument checks (E272's reason texts, final), the test and
skipped outcomes, and the trimmed result are decided without a window, so they are tested
directly and shared by the hooks (``check_args``, ``outcome_for``) and the session
(``ask_text``).

Characters are counted as the field counts them: graphemes after F11's cleaning, through
``api.TextField``'s own model (the bundled import rule allows only the API and the kit), so
``default`` is refused exactly when the field would cut it.
"""

from typing import Final

from engine.minigames.api import Outcome, TextField, closest
from engine.minigames.bundled.rule_text import kind_words, quoted, value_echo

PRESETS: Final = ("any", "name", "letters", "digits", "letters_digits")
PROMPT_MAX: Final = 300
LENGTH: Final = range(1, 201)
DEFAULTS: Final = {"prompt": None, "default": None, "max_length": 20, "allowed": "any",
                   "hide": False, "can_be_empty": False}
TEST_TEXT: Final = "Test"
_LISTED: Final = 5
_PREFIX: Final = "minigame ask_text: "


def _graphemes(text: str) -> list[str]:
    """``text`` as the field holds it (cleaned, in graphemes), not cut."""
    out: list[str] = []
    probe = TextField(max_length=200)
    rest = text
    while rest:
        chunk, rest = rest[:200], rest[200:]
        probe.set_text(chunk)
        out.extend(probe.model.graphemes())
    return out


def problem(args: dict) -> str | None:
    """The first refused argument's reason (01 §5's texts, in their order), or None."""
    prompt = args.get("prompt", DEFAULTS["prompt"])
    if prompt is not None:
        if type(prompt) is not str:
            return f"prompt must be text of 1 to 300 characters, but it is {kind_words(prompt)}."
        if prompt == "":
            return "prompt must be text of 1 to 300 characters, but it is empty."
        if len(prompt) > PROMPT_MAX:
            return f"prompt must be text of 1 to 300 characters, but it has {len(prompt)}."
    max_length = args.get("max_length", DEFAULTS["max_length"])
    if type(max_length) is not int or max_length not in LENGTH:
        return f"max_length must be a whole number from 1 to 200, not {value_echo(max_length)}."
    allowed = args.get("allowed", DEFAULTS["allowed"])
    if type(allowed) is not str or allowed not in PRESETS:
        text = ('allowed must be "any", "name", "letters", "digits" or "letters_digits", '
                f"not {value_echo(allowed)}.")
        near = closest(allowed, PRESETS) if type(allowed) is str else None
        return text + (f' Did you mean "{near}"?' if near is not None else "")
    default = args.get("default", DEFAULTS["default"])
    if default is not None:
        if type(default) is not str:
            return f"default must be text or None, not {kind_words(default)}."
        found = _graphemes(default)
        if len(found) > max_length:
            return (f"default can hold at most {max_length} characters (max_length), but it "
                    f"has {len(found)}.")
        probe = TextField(allowed=allowed)
        refused: list[str] = []
        for g in found:
            if not probe.allowed.accepts(g) and g not in refused:
                refused.append(g)
        if refused:
            shown = ", ".join(quoted(g) for g in refused[:_LISTED])
            more = ", …" if len(refused) > _LISTED else ""
            return (f'default has characters allowed="{allowed}" doesn\'t let the player '
                    f"type: {shown}{more}.")
    for arg in ("hide", "can_be_empty"):
        value = args.get(arg, DEFAULTS[arg])
        if type(value) is not bool:
            return f"{arg} must be True or False, not {value_echo(value)}."
    return None


def result_of(text: str) -> str:
    """The story's result: the answer trimmed at both ends."""
    return text.strip()


def fixed_outcome(kind: str, args: dict) -> Outcome | None:
    """The test outcome: ``default`` (trimmed), else "Test". ``ask_text`` is never skipped
    (the story needs the answer), so the skipped outcome is None (``skippable`` is E271)."""
    if kind != "test":
        return None
    default = args.get("default")
    return Outcome(result_of(default) if type(default) is str else TEST_TEXT)


__all__ = ["DEFAULTS", "PRESETS", "PROMPT_MAX", "TEST_TEXT", "fixed_outcome", "problem",
           "result_of"]
