"""Engine error types: ``UserFacingError.format()`` and the asset errors' texts.

Implementation note I-2: a formatted error never names the file twice.
"""

from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
    ConfigError,
    EngineError,
    UserFacingError,
)


def test_format_with_line_and_column():
    error = ConfigError("bad", file="config.toml", line=4, column=9)
    assert error.format() == "config.toml, line 4, column 9: bad"


def test_format_with_line_only():
    assert ConfigError("bad", file="config.toml", line=4).format() == "config.toml, line 4: bad"


def test_format_without_file():
    assert UserFacingError("bad", line=3).format() == "line 3: bad"
    assert UserFacingError("bad").format() == "bad"


def test_file_without_line_is_named_once():
    message = "config.toml is larger than 1 MB. Check that you opened the right file."
    assert ConfigError(message, file="config.toml").format() == message
    assert UserFacingError("unexpected end", file="script/a.vns").format() == \
        "script/a.vns: unexpected end"


def test_hierarchy():
    assert issubclass(ConfigError, UserFacingError)
    assert issubclass(AssetRefError, UserFacingError)
    for cls in (UserFacingError, AssetMissing, AssetNotFile, AssetTooLarge, AssetUnreadable):
        assert issubclass(cls, EngineError)


def test_asset_error_texts_name_only_the_ref():
    assert str(AssetMissing("images/a.png", None)) == "images/a.png not found"
    assert str(AssetMissing("images/A.png", "images/a.png")) == \
        "images/A.png not found — did you mean images/a.png?"
    assert str(AssetNotFile("images/dir.png")) == "images/dir.png is not a file"
    assert str(AssetTooLarge("images/big.png", 256 * 1_048_576)) == \
        "images/big.png is larger than 256 MB"
    assert str(AssetUnreadable("images/a.png")) == "could not read images/a.png"
    error = AssetRefError("../x.png", "reason")
    assert str(error) == error.format() == 'Asset path "../x.png" is not allowed: reason'


def test_asset_error_texts_are_escaped_and_cut():
    assert str(AssetMissing("a\nb", None)) == "a\\nb not found"
    assert str(AssetMissing("x" * 500, None)) == "x" * 119 + "… not found"
