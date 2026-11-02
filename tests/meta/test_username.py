"""F30 step 1: the login-name reader (``meta/username.py``): AC-F30-01 (cleaning, group A of
``05``) and AC-F30-02 (``UsernameSource`` reads once per opt-in). No window; every read is
a fake (the name guard makes a real ``getpass.getuser`` call fail the test)."""

import getpass
import logging
import unicodedata

import pytest

from engine.core.graphemes import graphemes
from engine.meta.username import UsernameSource, clean, read_login_name
from tests.fakes.username import Z, no_real_username, reader  # noqa: F401  (name guard)

COMBINING = "́"
FLOOD = ("a" + COMBINING * 50) * 32

# Group A (05 §5, AC-F30-01): raw value -> cleaned value.
CLEAN_ROWS = [
    ("CORP\\aiko", "aiko"),
    ("a\\b\\c", "c"),
    ("aiko‮", "aiko"),
    ("ai\nko", "aiko"),
    ("ai ko", "aiko"),
    ("\udcffaiko", "aiko"),
    ("\ud800", ""),
    ("e" + COMBINING, "é"),
    ("  aiko  ", "aiko"),
    ("a" * 80, "a" * 32),
    ("a" * 33_000, "a" * 32),
    ("x" * 1024 + "\\aiko", "x" * 32),          # the 1,024-code-point raw cut comes first
    ("   ", ""),
    ("\x01\x02", ""),
    ("", ""),
    ("{b}Zq9Name{/b}", "{b}Zq9Name{/b}"),
    ("{{", "{{"),
    ("<user>", "<user>"),
    ("عائشة", "عائشة"),
    ("friend", "friend"),
    ("\U0001f469‍\U0001f4bb", "\U0001f469\U0001f4bb"),   # ZWJ removed (D4)
]


def test_ac_f30_01_cleaning_the_raw_name(monkeypatch):
    for raw, expected in CLEAN_ROWS:
        assert clean(raw) == expected, ascii(raw[:40])

    # 32 x (a + 50 marks): bounded both ways, a prefix of the grapheme cut.
    flood = clean(FLOOD)
    assert len(graphemes(flood)) <= 32 and len(flood) <= 64
    grapheme_cut = "".join(graphemes(unicodedata.normalize("NFC", FLOOD))[:32])
    assert flood and grapheme_cut.startswith(flood)

    # read_login_name: clean(getpass.getuser()); Exception -> None; others propagate.
    monkeypatch.setattr(getpass, "getuser", lambda: "CORP\\aiko‮")
    assert read_login_name() == "aiko"
    for error in (ImportError("no pwd"), OSError("no tty"), KeyError("USERNAME")):
        def raise_it(error=error):
            raise error
        monkeypatch.setattr(getpass, "getuser", raise_it)
        assert read_login_name() is None, error
    for error in (KeyboardInterrupt(), SystemExit(1)):
        def raise_it(error=error):
            raise error
        monkeypatch.setattr(getpass, "getuser", raise_it)
        with pytest.raises(type(error)):
            read_login_name()


def test_ac_f30_02_username_source_reads_once_per_opt_in(caplog):
    caplog.set_level(logging.DEBUG)

    def source(read, allowed=lambda: True):
        failures = []
        made = UsernameSource(allowed=allowed, read=read,
                              on_failure=lambda: failures.append(1))
        return made, failures

    # Not allowed: never reads.
    read = reader()
    made, _ = source(read, allowed=lambda: False)
    assert [made.name() for _ in range(3)] == [None] * 3 and read.calls == 0

    # Allowed: one read, the same name every time.
    read = reader()
    made, _ = source(read)
    assert {made.name() for _ in range(100)} == {Z} and read.calls == 1

    # Unreadable (None, "", blank after cleaning, or an Exception): one read, on_failure once.
    for value in (None, "", " \x01 ", OSError("unreadable")):
        read = reader(value)
        made, failures = source(read)
        assert [made.name() for _ in range(5)] == [None] * 5, value
        assert read.calls == 1 and failures == [1], value

    # A BaseException from the reader is not "unreadable": it propagates.
    made, failures = source(reader(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        made.name()
    assert failures == []

    # D1: the row off and on again reads once more; forget() drops the name.
    allowed = [True]
    read = reader()
    made, _ = source(read, allowed=lambda: allowed[0])
    assert made.name() == Z
    allowed[0] = False
    assert made.name() is None
    made.forget()
    assert Z not in [v for v in vars(made).values() if isinstance(v, str)]
    allowed[0] = True
    assert made.name() == Z and read.calls == 2

    # A failure, forget(), a second failure: on_failure still once in the session.
    read = reader(None)
    made, failures = source(read)
    assert made.name() is None
    made.forget()
    assert made.name() is None
    assert read.calls == 2 and failures == [1]

    assert caplog.records == []                 # the module logs nothing
