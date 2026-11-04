"""F53 step P0: ``rule_text``'s shared refusal forms N, B, C, T and ``fill`` (F53 ``01`` §3.4),
which the three quick games and F54 use."""

from engine.minigames.bundled import rule_text as rt


def test_shared_forms_n_b_c_t_and_fill():
    # N: exactly an int in range; True is refused; lo_words replaces the written low end.
    assert rt.whole_problem("rounds", 3, 1, 9) is None
    assert rt.whole_problem("rounds", 10, 1, 9) == (
        "rounds must be a whole number from 1 to 9, but it is 10.")
    assert rt.whole_problem("rounds", True, 1, 9) == (
        "rounds must be a whole number from 1 to 9, but it is True.")
    assert rt.whole_problem("tries", 2.0, 0, 99, lo_words="0 (no limit)") == (
        "tries must be a whole number from 0 (no limit) to 99, but it is 2.0.")
    # B
    assert rt.flag_problem("leave", False) is None
    assert rt.flag_problem("leave", 1) == "leave must be True or False, but it is 1."
    assert rt.flag_problem("leave", "yes") == 'leave must be True or False, but it is "yes".'
    # C: two choices, then a list with "or"; the caller's suggestion.
    assert rt.choice_problem("kind", "dial", ("keypad", "dial")) is None
    assert rt.choice_problem("kind", "dail", ("keypad", "dial"), closest="dial") == (
        'kind must be "keypad" or "dial", but it is "dail". Did you mean "dial"?')
    assert rt.choice_problem("mode", 3, ("fair", "kind", "cheat", "sly")) == (
        'mode must be "fair", "kind", "cheat", or "sly", but it is 3.')
    # T: every line_problem key, optional and required.
    assert rt.text_problem("hint", None, 120) is None
    assert rt.text_problem("hint", "Fine.", 120) is None
    assert rt.text_problem("hint", 5, 120) == (
        "hint must be text in quotes, or None, but it is a whole number.")
    assert rt.text_problem("opponent", None, 24, required=True) == (
        "opponent must be text in quotes, but it is None.")
    assert rt.text_problem("hint", "", 120) == (
        "hint is empty; it is 1 to 120 characters on one line.")
    assert rt.text_problem("speaker", "x" * 25, 24) == (
        "speaker is 25 characters long; it is 1 to 24 characters on one line.")
    for bad in ("a\nb", "a​b"):
        assert rt.text_problem("line", bad, 160) == (
            "line has a line break or hidden character; it is 1 to 160 characters on one "
            "line.")
    assert rt.text_problem("line", " hi", 160) == (
        "line starts or ends with a space. Remove the space.")
    # fill: literal {key}s only; other braces stay.
    assert rt.fill("{n} tries left. {x}", n=2) == "2 tries left. {x}"
    assert rt.fill("You {you} – {them} {name}", you=1, them=0, name="Hana") == (
        "You 1 – 0 Hana")
