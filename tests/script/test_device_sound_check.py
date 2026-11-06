"""F65 round 3: W317, a ``[device.<look>] arrive_sound`` naming no file in ``audio/``, found
by the load (so ``engine check`` and Studio's Problems list it), not only by the run's W26."""

from engine.core.config import load_config
from engine.script.loader import LoadOptions, load_story
from tests.runtime.menu_story import write_game

CONFIG = ('\n[device.pigeon]\narrive_sound = "sfx/wngs.ogg"\n\n'
          '[device.radio]\narrive_sound = "sfx/hiss.ogg"\n')


def _check(root, dev=True):
    paths = write_game(root, 'label start:\n    "End."\n', CONFIG)
    (root / "audio" / "sfx").mkdir(parents=True)
    (root / "audio" / "sfx" / "wings.ogg").write_bytes(b"")
    (root / "audio" / "sfx" / "hiss.ogg").write_bytes(b"")
    config = load_config(paths)
    assert not config.errors
    return load_story(paths, LoadOptions(meter_config=config.config, dev=dev)).warnings


def test_missing_arrive_sound_is_a_load_warning(tmp_path):
    (warning,) = [w for w in _check(tmp_path) if w.code == "W317"]
    assert (warning.file, warning.line) == ("config.toml", 2)
    assert warning.message.startswith('[device.pigeon] arrive_sound "sfx/wngs.ogg" names no '
                                      "such file in audio/")
    assert 'Did you mean "sfx/wings.ogg"?' in warning.message
    assert warning.message.endswith("Add audio/sfx/wngs.ogg or check the spelling.")


def test_release_load_lists_no_files(tmp_path):
    assert not [w for w in _check(tmp_path, dev=False) if w.code == "W317"]
