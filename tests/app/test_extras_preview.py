"""F34 W3: ``run --extras [PAGE]`` (AC-F34-28; ``04`` §7.3; ``07`` I-4).

App A (F12's in-process launch, ``scripted_app``): the CLI parsed and the game started in
this process. The preview opens persistent data in MEMORY, unlocks every gallery picture
there, and shows the title with Extras open on the Gallery; the persistent file is left as
it was. ``--release``, ``--start`` and ``--try-stdin`` refuse it; an unknown page is a usage
error naming the pages.
"""

import os

import pytest

from engine.app import cli
from engine.persist.location import FILE_NAME
from engine.persist.sync import MEMORY
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.menus import DEFAULT_ORDER
from tests.app.test_persistence_app import _festivals_file, game_of
from tests.fixtures.F04 import gen_images as gen

pytestmark = pytest.mark.display

GALLERY = ('lock gallery cg river "By the River":\n    cg river_smile\n'
           'lock gallery cg festival "Festival Night"\n'
           'label start:\n    scene cg festival\n    "Start."\n    return\n')


def test_ac_f34_28_run_extras_gallery(tmp_path, user_roots, scripted_app, capsys):
    game = game_of(tmp_path, GALLERY)
    gen.write(game, {f"images/cg/{n}.png": gen.block(64, 36, (200, 30, 30))
                     for n in ("river", "river_smile", "festival")})
    data = _festivals_file(game)
    path = game / "persistent" / FILE_NAME
    stamp = os.stat(path).st_mtime_ns
    found = {}

    def look(app):
        top = app.screens.top
        if found or app.loading or app.persist is None or not isinstance(top, GameMenuScreen):
            return
        found.update(mode=app.persist.mode, menu=top.menu, page=top.page_id,
                     stack=[type(s) for s in app.screens],
                     unlocked=app.persist.store.unlocked("gallery"),
                     preview=app.extras_page)

    for frame in range(2, 60):
        scripted_app.at(frame, look)
    scripted_app.quit_frame = 60
    assert cli.main(["run", str(game), "--extras"]) == 0
    assert found == {"mode": MEMORY, "menu": "extras", "page": "gallery",
                     "stack": [TitleScreen, GameMenuScreen],
                     "unlocked": ("cg river", "cg river_smile", "cg festival"),
                     "preview": "gallery"}
    assert path.read_bytes() == data and os.stat(path).st_mtime_ns == stamp
    assert cli.EXTRAS_PAGES == DEFAULT_ORDER["extras"]

    for extra, message in ((["--release"], "--extras is only available in dev runs"),
                           (["--start", "start"], cli.EXTRAS_WITH_START),
                           (["--try-stdin"], cli.EXTRAS_WITH_START),
                           (["--extras=bogus"], cli.EXTRAS_NEEDS_PAGE)):
        with pytest.raises(SystemExit) as refused:
            cli.main(["run", str(game), "--extras", "gallery", *extra])
        assert refused.value.code == 2, extra
        assert capsys.readouterr().err.strip().splitlines()[-1].endswith(message), extra
