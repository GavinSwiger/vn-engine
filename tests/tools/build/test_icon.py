"""F42 P3: PNG → ICO (AC-F42-13)."""

import io
import struct

import pygame
import pytest

from engine.core.paths import engine_data_dir
from engine.tools.build.icon import BAD_ICON, IconError, icon_png, make_ico


def _png(width, height, color=(255, 0, 0, 255)):
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill(color)
    buffer = io.BytesIO()
    pygame.image.save(surface, buffer, "x.png")
    return buffer.getvalue()


def _entries(ico):
    reserved, kind, count = struct.unpack_from("<HHH", ico, 0)
    assert (reserved, kind) == (0, 1)
    found = []
    for index in range(count):
        w, h, _, _, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", ico,
                                                                     6 + 16 * index)
        assert (planes, bits) == (1, 32)
        data = ico[offset:offset + size]
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        found.append((w or 256, h or 256, data))
    return found


def test_ac_f42_13_icon_png_to_ico(tmp_path):
    entries = _entries(make_ico(_png(64, 32)))
    assert [(w, h) for w, h, _ in entries] == [(16, 16), (32, 32), (48, 48), (256, 256)]
    big = pygame.image.load(io.BytesIO(entries[-1][2]), "x.png")
    assert big.get_size() == (256, 256)
    assert big.get_at((128, 4)).a == 0                    # padded above, transparent
    assert tuple(big.get_at((128, 128))) == (255, 0, 0, 255)

    engine_icon = (engine_data_dir() / "icon.png").read_bytes()
    assert icon_png(tmp_path, None) == engine_icon         # unset → the engine icon
    assert len(_entries(make_ico(engine_icon))) == 4

    game = tmp_path / "game"
    (game / "gui").mkdir(parents=True)
    (game / "gui" / "lantern.png").write_bytes(_png(20, 20))
    assert icon_png(game, "gui/lantern.png") == _png(20, 20)

    for bad in (b"GIF89a" + bytes(40), _png(15, 40), b"\x89PNG\r\n\x1a\n" + b"junk"):
        with pytest.raises(IconError) as caught:
            make_ico(bad)
        assert caught.value.key == BAD_ICON
    for ref in ("gui/missing.png", "../outside.png", "gui"):
        with pytest.raises(IconError):
            icon_png(game, ref)
