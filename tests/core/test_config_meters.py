"""F62 round 2: ``[meter.<name>]`` in config.toml (look, place, label) and how
``kits.meter_look`` reads it (specs/F62-visible-meters/SPEC.md "Round 2")."""

from types import MappingProxyType

from engine.core import config_schema as cs
from engine.core.kits import meter_look


def test_a_meter_table_is_read(load):
    result = load('[meter.hana]\nlook = "hearts"\nplace = "top_right"\nlabel = "Hana"\n\n'
                  '[meter.trust]\nlook = "dial"\n')
    assert result.errors == [] and result.warnings == []
    tables = result.config.meter
    assert isinstance(tables, MappingProxyType) and list(tables) == ["hana", "trust"]
    hana = tables["hana"]
    assert (hana.look, hana.place, hana.label, hana.line) == ("hearts", "top_right", "Hana", 1)
    assert (tables["trust"].look, tables["trust"].place, tables["trust"].label) == \
        ("dial", None, None)


def test_meter_look_reads_the_table_over_the_kit(load):
    config = load('[theme]\nkit = "romance"\n\n[meter.affection]\nplace = "bottom_left"\n'
                  'label = "Her heart"\n').config
    assert meter_look(config, "affection") == ("hearts", "bottom_left", "Her heart")
    assert meter_look(config, "courage") == ("hearts", "top_right", "Courage")
    assert meter_look(load("").config, "hana") == ("bar", "top_left", "Hana")


def test_bad_values_are_errors_and_unknown_keys_warn(load):
    result = load('[meter.hana]\nlook = "heart"\nplace = "top"\nlabel = "a\\nb"\ncolor = 1\n')
    messages = [e.message for e in result.errors]
    assert len(messages) == 3
    assert messages[0].startswith('[meter.hana] look must be one of "bar", "number", "hearts"')
    assert "place must be one of" in messages[1] and "it has 2 lines" in messages[2]
    assert result.warnings == ["config.toml, line 5: unknown key [meter.hana] color"]
    # The table is kept with its good keys unset.
    assert result.config.meter["hana"].look is None


def test_bad_names_and_shapes(load):
    result = load('[meter]\nhana = 3\n\n[meter."two words"]\nlook = "bar"\n')
    messages = [e.message for e in result.errors]
    assert messages == ['[meter] hana must be a section, such as [meter.hana], but found 3',
                        '[meter."two words"] isn\'t a meter name. Use the name from the '
                        "points line, such as [meter.hana]."]
    assert dict(result.config.meter) == {}
    many = "".join(f"[meter.m{i}]\n" for i in range(cs.METER_TABLES_MAX + 1))
    assert "at most 200 are allowed" in load(many).errors[0].message


def test_a_near_miss_section_suggests_meter(load):
    assert "did you mean [meter]?" in load('[meters.hana]\nlook = "bar"\n').warnings[0]


def test_docs_and_section_class():
    assert cs.section_class("meter.hana") is cs.MeterTable
    assert cs.section_class("meter") is None
    assert cs.key_doc("meter", "") and cs.key_doc("meter.hana", "look")
    assert set(cs.config_fields(cs.MeterTable)) == {"look", "place", "label"}
    assert cs.config_fields(cs.MeterTable)["look"].metadata["validator"].labels["dial"] == "Dial"
