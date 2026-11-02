"""F26's chats for Host C (``06-acceptance.md`` §5): Template C's ``late_chat`` as a value, the
session chats (``flow``, ``first``, ``three``, ``long``, ``group``, ``quiet``), the overflow and
Unicode chats of AC-F26-18, the W176 chats, and builders for the bound rows.

Every chat passes ``phone_rules.problem`` with ``args(…)``'s contact and time."""

LATE_CHAT = [
    "you awake?",
    "i can't sleep...",
    {"ask": "awake",
        "yes": ["Yeah, what's up?", "nothing really"],
        "sleep": ["Go to sleep, Sayori.", "ok ok... one more thing!!"],
        "ignore": True},
    {"time": "11:51 PM"},
    "can we walk to school together tomorrow?",
    {"ask": "walk", "sure": "Sure. Same corner as always?", "busy": "I have to go early."},
    "yay!! see you then",
]

FLOW = ["hi", {"me": "On my way."}, {"time": "1 AM"}, {"time": "2 AM"}, "x" * 64,
        {"ask": "q", "a": "A"}]

FIRST = [{"ask": "a", "x": "X", "y": "Y", "ignore": True}, "after"]

THREE = [{"ask": "a", "x": "X", "ignore": True}, "one",
         {"ask": "b", "x": "X", "ignore": True}, "two",
         {"ask": "c", "x": "X", "ignore": True}]

QUIET = ["hi"]

# 30 one-line messages in the thread, then a 31st still to come (so no rows show).
LONG = [f"message {n}" for n in range(1, 32)]

GROUP = [{"Sayori": "a"}, {"Natsuki": "b"}, {"Natsuki": "c"}, {"Sayori": "d"}]


def args(chat, contact="Sayori", time="11:42 PM") -> dict:
    return {"chat": chat, "contact": contact, "time": time}


LATE = args(LATE_CHAT)


def overflow(n: int, label_cp: int, ignore: bool) -> list:
    """One ask with ``n`` replies of ``label_cp`` code points (words of 4 letters), with or
    without the ignore row."""
    def label(i: int) -> str:
        text = " ".join([f"w{i}xy"] * 40)[:label_cp]
        return text.rstrip() + "z" * (label_cp - len(text.rstrip()))

    ask: dict = {"ask": "q"}
    for i in range(n):
        ask[f"r{i}"] = label(i)
    if ignore:
        ask["ignore"] = True
    return [ask]


CJK_300 = "中文字" * 100
UNICODE_MESSAGES = (CJK_300, "שלום עולם", "\U0001F60A",
                    "\n".join(["line one", "line two", "line three", "line four", "end"]),
                    "https://example.com/" + "a" * 20)


def w176_chat(step: int, text: str) -> list:
    """Plain messages with ``text`` at top-level ``step`` (from 1)."""
    return [text if i == step else f"line {i}" for i in range(1, max(step, 2) + 1)]


def w176_follow_up() -> list:
    """``中`` in the second follow-up of reply ``yes``."""
    return ["hi", {"ask": "awake", "yes": ["sure", "fine", "a 中 b"], "no": "no"}]


def many_missing(n: int, start: int = 0x4E00) -> list[list]:
    """``n`` chats, each with one distinct missing CJK character (one W176 text each)."""
    return [[f"x {chr(start + i)}"] for i in range(n)]


def distinct_chars(n: int) -> list:
    """Messages holding ``n`` distinct non-space characters (CJK, from U+4E00), ≤ 300 each."""
    chars = [chr(0x4E00 + i) for i in range(n)]
    return ["".join(chars[i:i + 300]) for i in range(0, n, 300)]


__all__ = ["CJK_300", "FIRST", "FLOW", "GROUP", "LATE", "LATE_CHAT", "LONG", "QUIET", "THREE",
           "UNICODE_MESSAGES", "args", "distinct_chars", "many_missing", "overflow",
           "w176_chat", "w176_follow_up"]
