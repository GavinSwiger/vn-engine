"""F15 steps 1–3 in the App: skip and auto over the real ports (``specs/F15-skip-auto/
SPEC.md`` §7). AC-F15-01 to 06, 09, 11, 12.

Every run is App A (``tests/fakes/text_app.py``: the real ``App`` loop on a ``FakeWindow``,
1/60 s frames, ``install_story``), so ``SkipAuto`` drives the real ``TextboxScreen``,
``StageScreen``, ``ChoiceController``, and F12 store that ``install_skip_auto`` wired. Where
audio matters, the App gets a real ``AudioService`` on a ``FakeMixer``. ``Probe`` spies on
the ports inside a ``MonkeyPatch.context()`` and replaces ``pygame.key.get_mods``
(``SkipAuto.get_mods``), which a dummy display never sets.
"""

import shutil
from dataclasses import replace
from pathlib import Path

import pygame
import pytest

from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.render.typewriter import TypeState
from engine.runtime.commands import StoryEnded
from engine.runtime.headless import run_headless
from engine.ui.builtin.skip_auto import SkipAuto, SkipAutoSettings
from engine.ui.menus import DEFAULT_ORDER
from tests.app.test_windowed_equals_headless import game as f09_game
from tests.fakes.fake_mixer import FakeMixer, ogg_bytes
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen
from tests.runtime.corpus import canon
from tests.runtime.effects_story import IMG9, load_game

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]
SKIP_ALL = "[skip]\nall = true\n"
INSTANT = "[textbox]\ncps = 0\n"
CTRL = pygame.KMOD_LCTRL
MENU = '    menu:\n        "Stay":\n            "Stayed."\n'
SKIP_ACTIONS = ("tb.complete_now", "tb.press", "st.finish_now")


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def says(n: int) -> str:
    return "".join(f'    "Line {i}."\n' for i in range(n))


def story(tmp_path: Path, body: str, config: str = "", files: dict | None = None, *,
          size: tuple[int, int] = (640, 360)) -> Session:
    """App A on ``label start:`` + ``body``; ``files`` (game-folder path → bytes) are written
    before the launch lists the folder. The window is half size (cheaper frames) unless a
    test clicks at canvas positions."""
    root = make_text_game(tmp_path / "game", script="label start:\n" + body, config=config)
    for rel, data in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return Session(root, size=size)


def with_audio(s: Session) -> FakeMixer:
    """A real ``AudioService`` on a ``FakeMixer`` (no sound device), before the launch."""
    mixer = FakeMixer(clock=s.app.clock)
    s.app.audio = AudioService(s.paths, SizedLru(1 << 20), AudioConfig(), backend=mixer,
                               clock=s.app.clock)
    return mixer


class Probe:
    """Spies on the launch's ports once ``App.skip_auto`` exists and the first line shows:
    ``log`` holds ``(frame, "tb.complete_now" | "tb.press" | "st.finish_now" | "st.press")``,
    ``drawn`` each textbox draw as ``(frame, sid, page, complete)``, ``skipping`` each
    ``set_skipping`` call. ``mods`` is what ``SkipAuto.get_mods`` returns."""

    def __init__(self, s: Session, mp: pytest.MonkeyPatch) -> None:
        self.s, self.mp = s, mp
        self.log: list[tuple[int, str]] = []
        self.drawn: list[tuple[int, str | None, int, bool]] = []
        self.skipping: list[tuple[bool, str | None]] = []
        self.mods = 0
        self.sa: SkipAuto

    def ready(self):
        s = self.s
        yield from s.until(lambda: s.app.skip_auto is not None and s.line_text() is not None)
        app, mp = s.app, self.mp
        self.sa = app.skip_auto
        mp.setattr(self.sa, "get_mods", lambda: self.mods)
        tb, st = app.textbox, app.stage_screen
        for obj, tag, name in ((tb, "tb", "complete_now"), (tb, "tb", "press"),
                               (st, "st", "finish_now")):
            self._wrap(obj, name, f"{tag}.{name}")
        real_draw = tb.draw

        def draw(canvas):
            typer = tb.typer
            self.drawn.append((s.frame, tb.line.sid if tb.line else None,
                               typer.page if typer else 0,
                               typer is not None and typer.state is TypeState.COMPLETE))
            real_draw(canvas)

        mp.setattr(tb, "draw", draw)
        audio = app.audio
        if audio is not None:
            real_set = audio.set_skipping

            def set_skipping(on, *, resume=None):
                self.skipping.append((on, resume))
                real_set(on, resume=resume)

            mp.setattr(audio, "set_skipping", set_skipping)

    def _wrap(self, obj, name: str, tag: str) -> None:
        real = getattr(obj, name)

        def wrapped(*args, **kw):
            self.log.append((self.s.frame, tag))
            return real(*args, **kw)

        self.mp.setattr(obj, name, wrapped)

    def actions(self, since: int = 0) -> list[tuple[int, str]]:
        return [a for a in self.log if a[0] >= since and a[1] in SKIP_ACTIONS]


def entry(s: Session, entry_id: str):
    return next(e for e in s.app.shell.menus.shown("quick") if e.id == entry_id)


def click_entry(s: Session, entry_id: str) -> None:
    """A real click (down and up) on the quick menu's ``entry_id``."""
    qm = s.app.shell.quick_menu
    found = qm.shown()
    index = [e.id for e in found.entries].index(entry_id)
    pos = tuple(round(v) for v in found.layout.items[index].box.center)
    s.mouse(pos)
    s.mouse(pos, up=True)


# --- AC-F15-01, TR-F15-01 — skip-all pacing on the real textbox -----------------------------------

def test_ac01_skip_all_paces_one_advance_per_line(tmp_path):
    special = {3: "ab {pause}cd", 7: "ab {pause=2}cd", 11: "lantern " * 70,
               15: "next line{next}"}
    body = "".join(f'    "{special.get(i, f"Line {i}.")}"\n' for i in range(30)) + MENU
    s = story(tmp_path, body, SKIP_ALL)
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def script(s):
            yield from p.ready()
            s.key(pygame.K_TAB)
            yield from s.until(lambda: s.app.choices.screen is not None, limit=600)
            yield

        s.play(script)
    sids = [cmd.sid for _, cmd in s.said]
    advances = [(f, e.sid) for f, e in s.posted]
    assert [sid for _, sid in advances] == sids[:30] and len(set(sids[:30])) == 30
    frames = [f for f, _ in advances]
    assert min(b - a for a, b in zip(frames, frames[1:])) >= 3        # ≥ 50 ms at 60 fps
    per_frame = [f for f, _ in p.actions()]
    assert len(per_frame) == len(set(per_frame))                        # ≤ 1 action a frame
    for frame, sid in advances:                    # the complete line drawn before it went
        assert any(f < frame and d == sid and done for f, d, _, done in p.drawn), sid
    assert any(d == sids[11] and page >= 1 for _, d, page, _ in p.drawn)   # two pages
    assert not p.sa.skipping                       # stopped at the menu


# --- AC-F15-02 — seen mode stops at the first unseen line; skip-all marks it --------------------

def test_ac02_seen_mode_stops_on_unseen_and_skip_all_marks(tmp_path):
    for n, (config, stop) in enumerate((("", 2), (SKIP_ALL, None))):
        s = story(tmp_path / str(n), says(5) + MENU, config)
        with_audio(s)
        out = {}
        with pytest.MonkeyPatch.context() as mp:
            p = Probe(s, mp)

            def script(s):
                yield from p.ready()
                store = s.app.story.interp.persistent
                sids = [st.sid for st in s.app.program.statements_in("start")][:5]
                for i in (0, 1, 3):
                    store.mark_seen(sids[i])
                store.mark_seen(sids[2] + "x")       # L2 as it read before an edit (ADR-0006)
                s.key(pygame.K_TAB)
                for _ in range(60):
                    yield
                out.update(sids=sids, l2=store.is_seen(sids[2]), skipping=p.sa.skipping,
                           enabled=entry(s, "skip").enabled(), line=s.textbox.line.sid)

            s.play(script)
        sids, posted = out["sids"], [e.sid for _, e in s.posted]
        if stop is None:
            assert posted == sids and out["l2"]          # F12 marks it on the Advance
            continue
        assert posted == sids[:2] and not out["l2"] and not out["skipping"]
        assert out["line"] == sids[2] and not out["enabled"]
        assert p.skipping == [(True, None), (False, sids[2])]   # I-3: L2 keeps its voice
        assert [a for _, a in p.actions()].count("tb.complete_now") <= 2   # L2 typed itself


# --- AC-F15-03 — every way skip ends -----------------------------------------------------------

def test_ac03_each_ender_stops_skip_once_and_posts_nothing_after(tmp_path):
    s = story(tmp_path, says(90) + MENU, SKIP_ALL)
    with_audio(s)
    rounds: list[tuple[str, bool, list, int, int]] = []

    def pad_a(s):
        s.event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_A, instance_id=0)

    def restored(s):
        s.app.router.dispatch(replace(s.textbox.line, restored=True))

    def focus(gained: bool):
        return lambda s: s.event(pygame.WINDOWFOCUSGAINED if gained else
                                 pygame.WINDOWFOCUSLOST, window=None)

    enders = [
        ("click", lambda s: s.mouse((320, 150)), None),     # the scene, not the pill
        ("space", lambda s: s.key(pygame.K_SPACE), None),
        ("enter", lambda s: s.key(pygame.K_RETURN), None),
        ("pad A", pad_a, None),
        ("tab", lambda s: s.key(pygame.K_TAB), None),
        ("ctrl up", lambda s: s.key_up(pygame.K_LCTRL), None),
        ("restored", restored, None),
        ("game menu", lambda s: s.key(pygame.K_ESCAPE), lambda s: s.key(pygame.K_ESCAPE)),
        ("H", lambda s: s.key(pygame.K_h), lambda s: s.key(pygame.K_h)),
        ("focus lost", focus(False), focus(True)),
        ("reset", lambda s: p.sa.reset(), restored),     # a reset waits for the next Say
    ]
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def script(s):
            yield from p.ready()
            s.event(pygame.CONTROLLERDEVICEADDED, device_index=0, guid="")
            yield
            for name, end, undo in enders:
                yield from s.until(lambda: s.app.screens.top is s.textbox)
                held = name == "ctrl up"
                p.mods = CTRL if held else 0
                calls = len(p.skipping)
                if held:
                    s.key(pygame.K_LCTRL, CTRL)
                else:
                    s.key(pygame.K_TAB)
                for _ in range(4):
                    yield
                on = p.sa.skipping
                end(s)
                frame, posted = s.frame, len(s.posted)
                for _ in range(5):
                    yield
                rounds.append((name, on, p.skipping[calls:], len(s.posted) - posted,
                               len(p.actions(frame))))
                if undo is not None:
                    undo(s)
                    yield
                p.mods = 0
            # menu_shown: skip runs into the menu and stops there.
            s.key(pygame.K_TAB)
            yield from s.until(lambda: s.app.choices.screen is not None, limit=900)
            for _ in range(5):
                yield
            rounds.append(("menu", True, p.skipping[-1:], 0, 0))

        s.play(script, last=3000)
    for name, on, calls, posted, actions in rounds:
        assert on, name
        assert [c[0] for c in calls] in ([True, False], [False]), (name, calls)
        assert (posted, actions) == (0, 0), name
        assert not p.sa.skipping


# --- AC-F15-04 — keys and the quick menu's Skip and Auto ---------------------------------------

def test_ac04_keys_and_quick_menu_entries(tmp_path):
    s = story(tmp_path, says(40) + MENU, INSTANT, size=(1280, 720))
    seen: dict[str, object] = {}
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def state():
            return p.sa.skip, p.sa.auto, entry(s, "skip").on(), entry(s, "auto").on()

        def script(s):
            yield from p.ready()
            ids = [e.id for e in s.app.shell.menus.shown("quick")]
            seen["order"] = ids == [i for i in DEFAULT_ORDER["quick"] if i in ids]
            seen["ids"] = ids
            # Seen mode on an unseen line: Ctrl and Tab leave skip off; Skip is disabled.
            p.mods = CTRL
            s.key(pygame.K_LCTRL, CTRL)
            yield
            s.key(pygame.K_TAB)
            yield
            seen["unseen"] = (p.sa.skip, entry(s, "skip").enabled())
            p.mods = 0
            s.key_up(pygame.K_LCTRL)
            # A toggles auto; Ctrl+A, Alt+A, and a repeat do nothing.
            s.key(pygame.K_a)
            yield
            seen["a_on"] = state()
            for mod in (CTRL, pygame.KMOD_LALT):
                s.key(pygame.K_a, mod)
                yield
            s.event(pygame.KEYDOWN, key=pygame.K_a, mod=0, unicode="a", scancode=0,
                    repeat=True)
            yield
            seen["a_mods"] = state()
            s.key(pygame.K_a)
            yield
            seen["a_off"] = state()
            # Skip-all (F16's setting): Skip enabled; Tab toggles, Ctrl holds.
            p.sa.settings = SkipAutoSettings(skip_all=True)
            yield
            seen["all_enabled"] = entry(s, "skip").enabled()
            s.key(pygame.K_TAB)
            yield
            seen["tab_on"] = state()
            s.key(pygame.K_TAB)
            yield
            seen["tab_off"] = state()
            p.mods = CTRL
            s.key(pygame.K_LCTRL, CTRL)
            yield
            seen["ctrl_down"] = p.sa.skip
            p.mods = 0                              # released under a menu: get_mods says so
            yield
            seen["ctrl_gone"] = p.sa.skip
            # A real click on each quick-menu entry toggles it.
            clicks = []
            for entry_id in ("auto", "auto", "skip", "skip"):
                click_entry(s, entry_id)
                yield
                clicks.append(state())
            seen["clicks"] = clicks
            # At a menu: Ctrl and Tab leave skip off and Skip is disabled, even under skip-all.
            s.key(pygame.K_TAB)
            yield from s.until(lambda: s.app.choices.screen is not None, limit=900)
            yield
            p.mods = CTRL
            s.key(pygame.K_LCTRL, CTRL)
            yield
            s.key(pygame.K_TAB)
            yield
            seen["menu"] = (p.sa.skip, entry(s, "skip").enabled())

        s.play(script)
    assert seen["order"] and {"skip", "auto"} <= set(seen["ids"])
    assert seen["unseen"] == ("off", False)
    assert seen["a_on"] == ("off", True, False, True)
    assert seen["a_mods"] == ("off", True, False, True)
    assert seen["a_off"] == ("off", False, False, False)
    assert seen["all_enabled"] is True
    assert seen["tab_on"] == ("toggled", False, True, False)
    assert seen["tab_off"] == ("off", False, False, False)
    assert (seen["ctrl_down"], seen["ctrl_gone"]) == ("held", "off")
    assert seen["clicks"] == [("off", True, False, True), ("off", False, False, False),
                              ("toggled", False, True, False), ("off", False, False, False)]
    assert seen["menu"] == ("off", False)


# --- AC-F15-05 — waits end at once; the story equals a click-through ----------------------------

def test_ac05_skip_finishes_waits_and_the_commands_equal_headless(tmp_path):
    root = f09_game(tmp_path / "g", SKIP_ALL)
    s = Session(root, size=(640, 360))
    commands: list = []
    waits: list[tuple[int, str | None, bool]] = []
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def script(s):
            router = s.app.router
            dispatch = router.dispatch

            def spy(command):
                commands.append(command)
                if not isinstance(command, StoryEnded):  # the shell would quit at once
                    dispatch(command)

            mp.setattr(router, "dispatch", spy)
            yield from p.ready()
            s.key(pygame.K_TAB)
            for _ in range(900):
                yield
                st = s.app.stage_screen
                waits.append((s.frame, st.wait_kind, st.effects.active))
                if commands and isinstance(commands[-1], StoryEnded):
                    return
            raise AssertionError("the story did not end")

        s.play(script, last=1000)
    assert canon(commands) == canon(run_headless(load_game(root), seed=7, image_files=IMG9))
    # Each wait (transition, timed and untimed pause) lasts at most two frames under skip;
    # no shake or flash is left to draw at the end of any frame.
    run = 0
    for _, kind, _ in waits:
        run = run + 1 if kind is not None else 0
        assert run <= 2
    assert not any(active for _, _, active in waits)
    assert any(a == "st.finish_now" for _, a in p.log)


# --- AC-F15-06 — set_skipping and the voice ----------------------------------------------------

def test_ac06_skip_stops_the_voice_and_skipped_voices_never_play(tmp_path):
    lines = "".join(f'    voice "voice/v{i}.ogg"\n    "Line {i}."\n' for i in range(4))
    voices = {f"voice/v{i}.ogg": ogg_bytes(30.0, salt=bytes([i])) for i in range(4)}
    s = story(tmp_path, lines + MENU, SKIP_ALL,
              files={f"audio/{name}": data for name, data in voices.items()})
    mixer = with_audio(s)
    for name, data in voices.items():
        mixer.register(data, name, 30.0)
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def script(s):
            yield from p.ready()
            s.app.audio.set_voice_sustain(True)
            for _ in range(3):
                yield
            out["before"] = s.app.audio.voice_playing()
            mark = len(mixer.actions())
            s.key(pygame.K_TAB)
            yield
            out["after"] = s.app.audio.voice_playing()
            out["stop"] = [a for a in mixer.actions()[mark:] if a[1] == "channel_stop"
                           and a[2][0] == 0]
            mark = len(mixer.actions())
            yield from s.until(lambda: s.app.choices.screen is not None, limit=600)
            out["plays"] = [a for a in mixer.actions()[mark:] if a[1] == "channel_play"
                            and a[2][0] == 0]

        s.play(script)
    assert out["before"] and not out["after"] and out["stop"]
    assert out["plays"] == []                     # lines 1–3: never reached the backend
    assert p.skipping[0] == (True, None) and [c[0] for c in p.skipping].count(True) == 1


# --- AC-F15-09 — auto over lines, a menu, clicks, restores, and skip -------------------------------

def test_ac09_auto_stays_on_waits_at_menus_and_yields_to_skip(tmp_path):
    after = "".join(f'    "After {i}."\n' for i in range(12))
    fast = "[auto]\ndelay = 0.2\nper_char = 0\n"         # 12 frames a line (config, I-5)
    s = story(tmp_path, says(10) + MENU + after, INSTANT + fast)
    seen: dict[str, object] = {}
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def posted_now() -> int:
            return len(s.posted)

        def script(s):
            yield from p.ready()
            s.key(pygame.K_a)
            yield from s.until(lambda: s.app.choices.screen is not None, limit=400)
            seen["lines"] = (posted_now(), p.sa.auto)
            for _ in range(120):                     # 2 s at the menu: nothing posted
                yield
            seen["menu"] = (posted_now(), p.sa.auto)
            s.key(pygame.K_1)
            yield from s.until_line("After 0.")
            seen["after_pick"] = p.sa.auto
            n = posted_now()
            yield
            s.key(pygame.K_SPACE)                    # the player's click advances at once
            yield
            seen["click"] = (posted_now() - n, p.sa.auto)
            p.sa.settings = SkipAutoSettings(skip_all=True)
            s.key(pygame.K_TAB)                      # skip acts, auto waits
            for _ in range(8):
                yield
            seen["both"] = (p.sa.skip, p.sa.auto, [a for _, a in p.actions()][-1])
            s.key(pygame.K_TAB)
            yield
            n, frame = posted_now(), s.frame
            yield from s.until(lambda: posted_now() > n, limit=60)
            seen["auto_after_skip"] = (p.sa.skip, p.sa.auto, s.frame > frame)
            s.app.router.dispatch(replace(s.textbox.line, restored=True))
            yield
            seen["restored"] = p.sa.auto
            s.key(pygame.K_a)
            yield
            seen["again"] = p.sa.auto
            p.sa.reset()
            seen["reset"] = p.sa.auto

        s.play(script)
    assert seen["lines"] == (10, True) and seen["menu"] == (10, True)
    assert seen["after_pick"] is True and seen["click"] == (1, True)
    assert seen["both"][:2] == ("toggled", True) and seen["both"][2] in SKIP_ACTIONS
    assert seen["auto_after_skip"] == ("off", True, True)
    assert (seen["restored"], seen["again"], seen["reset"]) == (False, True, False)


# --- AC-F15-12, I-2 — reduced effects space every stage change under skip ---------------------------

def test_ac12_stage_changes_spaced_under_reduce(tmp_path):
    images = {gen.ref_of(f"bg {n}"): gen.png_bytes(gen.block(64, 36, c))
              for n, c in (("ember", (200, 40, 0)), ("sea", (0, 80, 240)))}
    lines = "".join(f'    scene bg {("ember", "sea")[i % 2]}\n    "Line {i}."\n'
                    for i in range(10))
    chain = "".join(f'    scene bg {n} with dissolve\n' for n in ("ember", "sea", "ember"))
    # Reduce on: every change (lines and the ``with`` chain) ≥ 333 ms apart; off: the lines'
    # changes follow skip's line pace (≥ 50 ms), and the chain may cut frame by frame.
    for reduce, gap, spaced in ((True, 20, 12), (False, 3, 9)):
        config = SKIP_ALL + f"[effects]\nreduce = {str(reduce).lower()}\n"
        s = story(tmp_path / str(reduce), lines + chain + MENU, config, files=images)
        shows: list[int] = []
        with pytest.MonkeyPatch.context() as mp:
            p = Probe(s, mp)

            def script(s):
                router = s.app.router
                dispatch = router.dispatch

                def spy(command):
                    if type(command).__name__ == "ShowStage":
                        shows.append(s.frame)
                    dispatch(command)

                mp.setattr(router, "dispatch", spy)
                yield from p.ready()
                del shows[:]                          # line 0's scene came before skip
                s.key(pygame.K_TAB)
                yield from s.until(lambda: s.app.choices.screen is not None, limit=900)

            s.play(script)
        assert len(shows) == 12, shows                # lines 1–9 and the three-``with`` chain
        kept = shows[:spaced]
        assert min(b - a for a, b in zip(kept, kept[1:])) >= gap, (reduce, shows)


# --- AC-F15-11 — the example game: skip-all equals clicking through -----------------------------

def example_run(tmp_path: Path, *, skip: bool) -> dict:
    root = tmp_path / ("skip" if skip else "click")
    shutil.copytree(REPO / "game", root,
                    ignore=shutil.ignore_patterns("logs", "saves", "persistent", "settings",
                                                  "characters"))
    with (root / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[title]\nenabled = false\n")
    s = Session(root, size=(640, 360))
    s.app.seed = 7
    out: dict = {}
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def script(s):
            yield from p.ready()
            choices = s.app.choices
            if skip:
                p.sa.settings = SkipAutoSettings(skip_all=True)
                s.key(pygame.K_TAB)
            for n in range(3000):
                if choices.screen is not None:
                    break
                if not skip:
                    s.key(pygame.K_SPACE)
                yield
            else:
                raise AssertionError("no menu")
            interp = s.app.story.interp
            store = interp.persistent
            out["state"] = s.app.story.checkpoint().to_json()
            out["history"] = interp.history.entries
            out["seen"] = {st.sid for st in s.app.program.iter_statements()
                           if store.is_seen(st.sid)}

        s.play(script, last=3200)
    return out


def test_ac11_example_game_skip_all_equals_clicking_through(tmp_path):
    skipped, clicked = example_run(tmp_path, skip=True), example_run(tmp_path, skip=False)
    assert skipped == clicked
    assert skipped["seen"] and skipped["history"]
    assert not {"skip", "auto"} & set(skipped["state"])       # nothing of F15 is saved
