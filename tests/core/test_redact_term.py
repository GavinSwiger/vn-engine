"""F30 step 1: ``core/redact.set_session_term`` (SEC-F30-04, ``04`` §6.3, ``07`` I-10). The
login name, once read, is redacted from every output channel as a whole word in any case,
after the installed redactor, and the term survives ``install()``. (AC-F30-33 drives it
end to end in step 5.)"""

from engine.core import redact as r
from tests.fakes.username import no_real_username  # noqa: F401  (name guard, AC-F30-07)


def test_session_term_is_redacted_after_the_installed_redactor():
    r.install(r.Redactor((r.RedactRoot("<game>", "C:\\Games\\Lantern"),), home_name=None,
                         case_insensitive=True))
    r.set_session_term("Zq9Name")
    rows = [
        ("hello Zq9Name.", "hello <user>."),
        ("ZQ9NAME and zq9name", "<user> and <user>"),
        ("ValueError('Zq9Name')", "ValueError('<user>')"),
        ("Zq9Namex xZq9Name Zq9Name_1", "Zq9Namex xZq9Name Zq9Name_1"),     # whole words only
        ("C:\\Games\\Lantern\\Zq9Name.txt", "<game>\\<user>.txt"),          # roots first
        ("", ""),
    ]
    for text, expected in rows:
        assert r.redact(text) == expected, text
    assert r.echo("at Zq9Name") == "at <user>"

    # It survives a new install(), and None or "" clears it.
    r.install(r.Redactor((), home_name=None, case_insensitive=False))
    assert r.redact("Zq9Name") == "<user>"
    for cleared in (None, ""):
        r.set_session_term(cleared)
        assert r.redact("Zq9Name") == "Zq9Name"

    # Regex characters in a name are literal.
    r.set_session_term("a.b+(c)")
    assert r.redact("x a.b+(c) y axb+(c)") == "x <user> y axb+(c)"
    r.set_session_term(None)
