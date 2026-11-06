"""F50 Timing assist, step 2: AC-F50-06, minigame API 1.3 (ADR-0009's minor bump)."""

from engine.core.minigame_types import API_VERSION
from engine.minigames import api, messages
from tests.minigames.conftest import plugin, write


def test_ac_f50_06_api_1_3_loads_and_1_4_is_e278(game, load):
    # F64 round 2 bumped the API to 1.5: 1.3 still loads, and the next minor (1.6) is E278.
    assert API_VERSION == (1, 5) and api.API_VERSION == (1, 5)
    assert messages.ENGINE_API == "1.5" and "version 1.5" in api.__doc__.splitlines()[0]
    write(game, "minigames/x.py", plugin("x", body="    api = '1.3'\n"))
    write(game, "minigames/y.py", plugin("y", body="    api = '1.6'\n"))
    loaded = load(game)
    assert loaded.result.registry.get("x").api == "1.3"
    assert loaded.codes == ["E278"]
    assert loaded.errors == ["minigames/y.py needs minigame API 1.6, but this engine has 1.5. "
                             "Update the engine, or use a version of the plugin made for 1.5."]
