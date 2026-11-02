"""F33 step 1 — AC-F33-01: ``[content_warning]`` and the two warning words (F33 ``SPEC.md``
§3, PR-F33-01, SR-F33-01..03; ``07`` I-4, I-8). A bad value is one F01 ``ConfigError`` with
config's form and the default is kept; the cross-key "text required" check reports at
``show``'s line. AC-F33-11's automated part and AC-F33-12 (the example game and Studio's
starter config) are at the end."""

from pathlib import Path

from engine.core.config_schema import SECTIONS, Config, ContentWarningConfig, WordsConfig, \
    config_fields

LINE2 = "config.toml, line 2: "
LINE3 = "config.toml, line 3: "
TEXT_MUST = ("[content_warning] text must be text of at most 2000 characters with no control "
             "characters other than line breaks, but found the text ")


def test_ac_f33_01_config_table(load):
    # Defaults, and a valid section with every key.
    assert Config().content_warning == ContentWarningConfig("never", "", 1, 2.0)
    assert SECTIONS["content_warning"] is ContentWarningConfig
    result = load('[content_warning]\nshow = "once"\nversion = 1000\nmin_seconds = 1.5\n'
                  'text = """\nFirst {b}line\n[still] first\n\n\nSecond."""\n')
    assert result.errors == []
    assert result.config.content_warning == ContentWarningConfig(
        "once", "First {b}line\n[still] first\n\n\nSecond.", 1000, 1.5)
    for show in ("never", "always"):
        result = load(f'[content_warning]\nshow = "{show}"\ntext = "x"\nmin_seconds = 0\n')
        assert result.errors == [] and result.config.content_warning.show == show
    assert len(load('[content_warning]\ntext = "' + "é" * 2000 + '"\n').config
               .content_warning.text) == 2000

    # One ConfigError each, exact text, the default kept (rows of AC-F33-01).
    rows = [
        ('show = "sometimes"', LINE2 + '[content_warning] show must be "never", "once", or '
                                       '"always", but found the text "sometimes"'),
        ("version = 0", LINE2 + "[content_warning] version must be a whole number from 1 to "
                                "1000, but found 0"),
        ("version = 1001", LINE2 + "[content_warning] version must be a whole number from 1 "
                                   "to 1000, but found 1001"),
        ("min_seconds = 10.5", LINE2 + "[content_warning] min_seconds must be seconds from 0 "
                                       "to 10, but found 10.5"),
        ('text = "' + "x" * 2001 + '"', LINE2 + TEXT_MUST + '"' + "x" * 39 + '…"'),
        ('text = "bell\\u0007"', LINE2 + TEXT_MUST + '"bell\\x07"'),
        ('text = "tab\\there"', LINE2 + TEXT_MUST + '"tab\\there"'),
    ]
    for line, message in rows:
        result = load(f"[content_warning]\n{line}\n")
        assert [e.format() for e in result.errors] == [message], line
        assert result.config.content_warning == ContentWarningConfig(), line

    # The cross-key check (SR-F33-03), at show's line; none with a text refused on its own.
    for text in ("", 'text = ""\n', 'text = """\n\n   \n"""\n'):
        result = load(f'[content_warning]\nshow = "once"\n{text}')
        assert [e.format() for e in result.errors] == [
            LINE2 + '[content_warning] text must be set when show is "once", but found '
                    "nothing"], text
    result = load('[content_warning]\nversion = 2\nshow = "always"\n')
    assert [e.format() for e in result.errors] == [
        LINE3 + '[content_warning] text must be set when show is "always", but found nothing']
    result = load('[content_warning]\nshow = "once"\ntext = "bad\\u0007"\n')
    assert [e.format() for e in result.errors] == [LINE3 + TEXT_MUST + '"bad\\x07"']
    assert load('[content_warning]\nshow = "never"\n').errors == []

    # A CRLF file: tomllib gives "\n" line ends, so the text is valid (07 I-4).
    result = load(b'[content_warning]\r\nshow = "once"\r\ntext = """\r\nOne.\r\n\r\nTwo."""\r\n')
    assert result.errors == [] and result.config.content_warning.text == "One.\n\nTwo."

    # The two words: English defaults, settable; every key has a one-line doc (I-8).
    assert (WordsConfig().warning_heading, WordsConfig().warning_continue) == \
        ("Content warning", "I understand")
    result = load('[words]\nwarning_heading = "Heads up"\nwarning_continue = "Go on"\n')
    assert result.errors == []
    assert (result.config.words.warning_heading, result.config.words.warning_continue) == \
        ("Heads up", "Go on")
    words = config_fields(WordsConfig)
    docs = [f.metadata["doc"] for f in config_fields(ContentWarningConfig).values()]
    docs += [words[key].metadata["doc"] for key in ("warning_heading", "warning_continue")]
    assert len(docs) == 6 and all(doc and "\n" not in doc for doc in docs)


# --- AC-F33-11 (the automated part) and AC-F33-12 -------------------------------------------

REPO = Path(__file__).resolve().parents[2]


def _uncommented_warning(text: str) -> str:
    """The commented ``[content_warning]`` block of a config, with its "# " removed."""
    lines = text.splitlines()
    start = lines.index("# [content_warning]")
    block = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        block.append(line[2:] if line.startswith("# ") else line[1:])
        if line.endswith('"""') and len(block) > 1 and block[-1] != 'text = """':
            break
    return "\n".join(block) + "\n"


def test_ac_f33_11_example_game_config(load):
    """The shipped example stays warning-free at launch (the block is commented out, the
    user's decision); uncommented, it is a valid "once" warning that fits without scrolling
    at 100%. The playtest rows (keyboard, mouse, gamepad, 150%, reduce motion) are manual."""
    text = (REPO / "game" / "config.toml").read_text(encoding="utf-8")
    shipped = load(text)
    assert shipped.errors == [] and shipped.config.content_warning.show == "never"
    block = _uncommented_warning(text)
    result = load(block)
    assert result.errors == [] and result.warnings == []
    warning = result.config.content_warning
    assert (warning.show, warning.version, warning.min_seconds) == ("once", 1, 2.0)
    assert warning.text.startswith("This story") and len(warning.text) <= 220


def test_ac_f33_12_studio_starter(tmp_path):
    """The starter ``config.toml.in`` has the commented example, which is valid when
    uncommented, and a new Studio game made from it still loads cleanly (F45 AC-F45-62)."""
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.tools.editor import files

    starter = files.starter_config("Night Shift").decode("utf-8")
    assert "# [content_warning]" in starter and '# show = "once"' in starter
    folder = tmp_path / "Night Shift"
    assert files.new_game(folder) == folder.absolute()
    loaded = load_config(GamePaths.for_game(folder))
    assert not loaded.errors and not loaded.warnings
    assert loaded.config.content_warning.show == "never"
    block = _uncommented_warning(starter)
    (folder / "config.toml").write_text(starter + "\n" + block, encoding="utf-8")
    loaded = load_config(GamePaths.for_game(folder))
    assert not loaded.errors and not loaded.warnings
    assert loaded.config.content_warning.show == "once"
