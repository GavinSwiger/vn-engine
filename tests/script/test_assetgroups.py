"""AC-F45-05 (TR-F45-06): the asset-group table is the engine's constants, and the lifted
helpers are the same objects under their old import paths (F45 ``04`` §4.1, Q5, Q8;
``07`` I-3, I-6)."""

from engine.audio import limits as audio_limits
from engine.audio import sniff as audio_sniff
from engine.core import audiosniff
from engine.core.constants import ASSET_MAX_BYTES, FONT_SUFFIXES, IMAGE_SUFFIXES
from engine.minigames import loader as minigame_loader
from engine.runtime import images
from engine.runtime.audio_check import AUDIO_DIR
from engine.script import imagenames, words
from engine.script.assetgroups import ASSET_GROUPS, CONFIG_REF
from engine.script.audio import PLAYABLE_EXTS
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.script.loader import SCRIPT_DIR, SCRIPT_SUFFIX


def test_ac_f45_05_groups_are_the_engine_constants():
    # key → (folder, suffixes, cap); `is` where the row holds the constant itself, `==` for
    # values built from one, and the two I-3 literals against their packages' constants.
    expected = {
        "script": (SCRIPT_DIR, (SCRIPT_SUFFIX,), SCRIPT_FILE_MAX_BYTES),
        "images": (images.IMAGES_DIR, IMAGE_SUFFIXES, ASSET_MAX_BYTES),
        "audio": (AUDIO_DIR, tuple(sorted(PLAYABLE_EXTS)), audio_limits.MUSIC_MAX_BYTES),
        "gui": ("gui", IMAGE_SUFFIXES, ASSET_MAX_BYTES),
        "fonts": ("fonts", FONT_SUFFIXES, ASSET_MAX_BYTES),
        "minigames": (minigame_loader.FOLDER, (".py",), minigame_loader.MAX_FILE_BYTES),
    }
    assert [g.key for g in ASSET_GROUPS] == list(expected)
    for group in ASSET_GROUPS:
        folder, suffixes, cap = expected[group.key]
        assert (group.folder, group.suffixes, group.max_bytes) == (folder, suffixes, cap), group
    by_key = {g.key: g for g in ASSET_GROUPS}
    for key, constant in [("images", IMAGE_SUFFIXES), ("gui", IMAGE_SUFFIXES),
                          ("fonts", FONT_SUFFIXES)]:
        assert by_key[key].suffixes is constant, key
    assert set(audiosniff.FORMAT_NAMES) == set(by_key["audio"].suffixes)
    assert CONFIG_REF == "config.toml"


def test_ac_f45_05_lifted_helpers_are_the_same_objects():
    lifted = [(images, imagenames, name) for name in imagenames.__all__]
    lifted += [(audio_sniff, audiosniff, name) for name in audiosniff.__all__]
    assert [f"{old.__name__}.{name}" for old, new, name in lifted
            if getattr(old, name) is not getattr(new, name)] == []
    assert set(audio_sniff.__all__) == set(audiosniff.__all__)
    assert imagenames.is_image_word is words.is_image_word          # I-6: one object
