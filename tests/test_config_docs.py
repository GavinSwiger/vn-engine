"""Every config key is described (2026-11-02, AC-F45-63): Studio's config Help shows
``key_doc``, so a key added with no ``spec(…, doc=…)`` (and no ``THEME_DOCS``/``WORD_DOCS``
row for its name) fails here, as does a description row that no key uses. F32's look tables
(``[style.<name>]``, ``[playthrough.N]``) are walked under a sample name."""

import re

from engine.core import config_schema as cs
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)


def _keys(sections):
    def walk(path, cls):
        for key, found in cs.config_fields(cls).items():
            yield path, key
            validator = found.metadata["validator"]
            if isinstance(validator, cs.Table):
                yield from walk(f"{path}.{key}", validator.cls)

    for name, cls in sections.items():
        yield from walk(name, cls)


def test_ac63_every_config_key_and_section_has_a_description():
    keys = list(_keys(cs.SECTIONS))
    assert len(keys) > 400
    looks = list(_keys({f"{name}.x": cls for name, cls in cs.LOOK_SECTIONS.items()}))
    assert [f"[{s}] {k}" for s, k in keys + looks if not cs.key_doc(s, k).strip()] == []
    assert [s for s in [*cs.SECTIONS, *cs.LOOK_SECTIONS] if not cs.key_doc(s, "")] == []
    assert set(cs.SECTION_DOCS) == set(cs.SECTIONS) | set(cs.LOOK_SECTIONS)
    theme_names = {k for s, k in keys if s.startswith("theme")} \
        | {f"{s}.{k}" for s, k in keys if s.startswith("theme")}
    assert set(cs.THEME_DOCS) - theme_names == set()          # no stale rows
    assert set(cs.WORD_DOCS) - {k for s, k in keys if s == "words"} == set()


# Studio's Game settings shows each description as a field's hint, so it must read as plain
# author-facing English (2026-11-02, the user: "Studio must not take a programmer to use"):
# no Python or TOML words, no section paths or key syntax, nothing but ``{username}`` in braces.
# The pattern of tests/tools/editor/test_scriptedit.py's AC-F46-34 test, for config words.
JARGON = re.compile(
    r"(?<!\w)(true|false|none|null|dict|list|lists|regex|tuple|graphemes?|toml|tokens?|"
    r"strings?|bool|boolean|int|float|unset|cps|ms|ui|nvl|sprites?|nine-slice|opaque|"
    r"rollback|gradient|textbox|per-character|thumbnail|keys?)(?!\w)|[\[\]<>=_]",
    re.IGNORECASE)


def test_descriptions_use_plain_words():
    keys = list(_keys(cs.SECTIONS))
    looks = list(_keys({f"{name}.x": cls for name, cls in cs.LOOK_SECTIONS.items()}))
    texts = {f"[{s}] {k}": cs.key_doc(s, k) for s, k in keys + looks}
    texts |= {f"[{s}]": cs.key_doc(s, "") for s in [*cs.SECTIONS, *cs.LOOK_SECTIONS]}
    texts |= {f"THEME_DOCS {k}": v for k, v in cs.THEME_DOCS.items()}
    texts |= {f"WORD_DOCS {k}": v for k, v in cs.WORD_DOCS.items()}
    assert len(texts) > 400
    bad = {where: text for where, text in texts.items()
           if JARGON.search(text.replace("{username}", "")) or "{" in
           text.replace("{username}", "")}
    assert bad == {}
