"""The committed config fixtures match their definitions in config_fixtures.py.

One test per folder, listing every mismatch at once: these check test data, not the engine,
so a row per file (127 rows before the 2026-11-01 test review) added count without signal.
"""

from tests.fixtures.F01 import config_fixtures


def test_committed_fixtures_match_definitions():
    wrong = [name for name, data in sorted(config_fixtures.FILES.items())
             if (config_fixtures.CONFIG_DIR / name).read_bytes() != data]
    assert wrong == [], "regenerate with: python tests/fixtures/F01/config_fixtures.py"


def test_committed_value_fixtures_match_definitions_and_none_are_stray():
    on_disk = {path.name for path in config_fixtures.VALUES_DIR.glob("*.toml")}
    assert on_disk == set(config_fixtures.VALUE_LINES)
    wrong = [name for name in sorted(config_fixtures.VALUE_LINES)
             if (config_fixtures.VALUES_DIR / name).read_bytes()
             != config_fixtures.value_file(name)]
    assert wrong == [], "regenerate with: python tests/fixtures/F01/config_fixtures.py"


def test_generated_huge_has_exact_sizes():
    for size in (1_048_576, 1_048_577, 2_097_152):
        assert len(config_fixtures.generated_huge(size)) == size
