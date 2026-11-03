"""F36 W3 — the Endings and Scenes pages join Extras: AC-F36-11.

The title is test_title's ``Rig`` (``install_ui`` over a small fake App) with
``install_extras`` (test_extras' ``rig_with``); ``install_replays`` (``app/replays.py``) is
called on it as ``install_story`` does, over a real ``Interpreter`` of a loaded story (its
``ending`` and ``replay`` kinds registered by ``Interpreter.__init__``)."""

from engine.app.replays import install_replays
from engine.runtime.endings import ENDING_KIND
from engine.runtime.replay import REPLAY_KIND
from engine.ui.nav import InputKind
from tests.runtime.stage_story import launched, load_game, write_game
from tests.ui.test_extras import retitle, rig_with

STORY = ('lock replay festival "The Festival"\n'
         'label start:\n    "Start."\n    jump festival\n'
         'label festival:\n    "Festival."\n    ending good "Good End" "Lanterns"\n'
         'label sad:\n    ending sad "Sad End" "Paper Ashes"\n')


def shown(rig) -> list[str]:
    return [e.id for e in rig.shell.menus.shown("extras")]


def title_labels(rig) -> list[str]:
    return [b.label() for b in rig.title.buttons]


def test_ac_f36_11_endings_page_shows_once_an_ending_is_reached_and_with_list(tmp_path):
    """No ending reached: no Endings page and (nothing else unlocked) no Extras button. One
    reached: the Endings page and the Extras button show. ``[endings] list = false``: never
    the Endings page, so Extras shows only once a scene unlocks (the Scenes page)."""
    program = load_game(write_game(tmp_path / "story", {"main.vns": STORY}))
    rows = []
    for name, config in (("on", ""), ("off", "[endings]\nlist = false\n")):
        interp = launched(program)
        store = interp.persistent
        rig = rig_with(tmp_path / name, config)
        install_replays(rig.app, interp)
        retitle(rig)
        row = [(shown(rig), title_labels(rig))]
        store.unlock(ENDING_KIND, "good")
        retitle(rig)
        row.append((shown(rig), title_labels(rig)))
        store.unlock(REPLAY_KIND, "festival")
        retitle(rig)
        row.append((shown(rig), title_labels(rig)))
        screen = rig.shell.open_extras(by=InputKind.KEYS)
        row.append(screen.page_id)
        rows.append(row)
    assert rows[0] == [([], ["New Game", "Quit"]),
                       (["endings"], ["New Game", "Extras", "Quit"]),
                       (["endings", "replays"], ["New Game", "Extras", "Quit"]),
                       "endings"]
    assert rows[1] == [([], ["New Game", "Quit"]),
                       ([], ["New Game", "Quit"]),
                       (["replays"], ["New Game", "Extras", "Quit"]),
                       "replays"]
