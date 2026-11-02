"""Every config key is described (2026-11-02, AC-F45-63): Studio's config Help shows
``key_doc``, so a key added with no ``spec(…, doc=…)`` (and no ``THEME_DOCS``/``WORD_DOCS``
row for its name) fails here, as does a description row that no key uses. F32's look tables
(``[style.<name>]``, ``[playthrough.N]``) are walked under a sample name."""

from engine.core import config_schema as cs


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
