"""F25 fixtures (``06`` §5): Story S, Template E's codex and meter, the base args, and the
large-argument builders, as plain values for the rules, headless, and session tests."""

from engine.core.minigame_types import StoryNames
from engine.runtime.codex import CodexIndex
from engine.script.codex import CodexCategory, CodexEntry

STORY_S = StoryNames(meters=("credibility",),
                     items=("brass_key", "festival_map", "shrine_photo"), tips=("lanterns",),
                     item_categories=(("Evidence", ("brass_key", "festival_map")),
                                      ("codex_items", ("shrine_photo",))))
DAICHI_SAYS = {
    "after_dark": "Nobody went near the shrine after dark.",
    "gate": "The gate was locked all night. I checked it myself.",
    "priest": "Only the priest has a key to that gate.",
}
# Template E's line 19, defaults filled (06 §0.2's base args).
BASE = {"testimony": DAICHI_SAYS, "answer": {"gate": "brass_key"}, "at": None,
        "speaker": "Daichi", "press": True, "evidence": None, "penalty": "credibility",
        "penalty_max": 5, "cost": 1}
WIN = {"action": "present", "statement": "gate", "evidence": "brass_key", "correct": True}
WRONG = {"action": "present", "statement": "gate", "evidence": "festival_map",
         "correct": False}
PRESS = {"action": "press", "statement": "after_dark", "evidence": None, "correct": False}

EVIDENCE = CodexCategory("item", "Evidence", None)
ITEMS = CodexCategory("item", None, "codex_items")
TIPS = CodexCategory("tip", None, "codex_tips")
HELD = ("brass_key", "festival_map", "shrine_photo")


def entry(name: str, title: str, category: CodexCategory) -> CodexEntry:
    return CodexEntry(name, category.kind, title, category, None, (), "s", "script/main.vns", 1)


def index(extra_evidence: int = 0) -> CodexIndex:
    """Template E's codex; ``extra_evidence`` more Evidence items ``clue_1`` … (the scrolling
    list row)."""
    entries = [entry("brass_key", "Brass Key", EVIDENCE),
               entry("festival_map", "Festival Map", EVIDENCE)]
    entries += [entry(f"clue_{i}", f"Clue {i}", EVIDENCE) for i in range(1, extra_evidence + 1)]
    entries += [entry("shrine_photo", "Shrine Photo", ITEMS),
                entry("lanterns", "Paper Lanterns", TIPS)]
    return CodexIndex(tuple(entries), (EVIDENCE, ITEMS, TIPS))


def args(**changes) -> dict:
    """The base args with ``changes``."""
    out = dict(BASE)
    out.update(changes)
    return out


def big_args() -> dict:
    """The largest args (AC-F25-23, 24): 12 × 120-code-point statements, 12 answers of 8
    names, 24 categories, ``penalty_max`` 20."""
    keys = [f"s{i}" for i in range(12)]
    testimony = {k: ("W" * 59 + " " + "W" * 60) for k in keys}
    names = [f"item_{i}" for i in range(8)]
    return {"testimony": testimony, "answer": {k: list(names) for k in keys}, "at": None,
            "speaker": "W" * 24, "press": True,
            "evidence": [f"Category {i}" for i in range(24)], "penalty": "credibility",
            "penalty_max": 20, "cost": 20}


__all__ = ["BASE", "DAICHI_SAYS", "EVIDENCE", "HELD", "ITEMS", "PRESS", "STORY_S", "TIPS",
           "WIN", "WRONG", "args", "big_args", "entry", "index"]
