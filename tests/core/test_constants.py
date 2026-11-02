"""Engine limits (§12.2). The constant half of AC-F01-161 (1 MB = 1,048,576 bytes); the
AssetManager budget half needs Step 7."""

from engine.core import constants as c


def test_megabyte_is_a_mebibyte():
    assert c.MB == 1_048_576
    assert c.KIB == 1024
    assert c.LOG_CAP_BYTES == 10_485_760
    assert c.CONFIG_MAX_BYTES == 1_048_576
    assert c.ASSET_MAX_BYTES == 256 * 1_048_576
    assert c.EARLY_LOG_MAX_BYTES == 262_144
    assert c.CLIPBOARD_MAX_BYTES == 65_536


def test_canvas_and_window_sizes():
    assert c.CANVAS_SIZE == (1280, 720)
    assert c.DEFAULT_WINDOW_SIZE == c.CANVAS_SIZE
    assert c.MIN_WINDOW_SIZE == (640, 360)


def test_echo_and_reference_limits():
    assert (c.ECHO_MAX_CHARS, c.VALUE_ECHO_MAX_CHARS, c.ERROR_MESSAGE_MAX_CHARS) == (120, 40, 4000)
    assert (c.REF_MAX_CHARS, c.SEGMENT_MAX_CHARS, c.LOCATE_MAX_LINE_CHARS) == (1024, 255, 4096)
    assert (c.IMAGE_MAX_SIDE, c.IMAGE_MAX_PIXELS) == (16_384, 64_000_000)


def test_game_folder_names():
    assert c.GAME_SUBFOLDERS == ("script", "images", "audio", "fonts", "gui")
    assert c.LOGS_DIRNAME == "logs"
    assert c.RESERVED_DIRNAMES == ("characters",)
