"""F06 step 3 — blips on F05's textbox in App A (``tests/fakes/text_app.py``) with a real
``AudioService`` on ``tests/audio``'s ``BlipMixer``: ``install_textbox`` wires one
``BlipPlayer`` (``app.blips``), the count over click-waits and pauses (AC-F06-04), instant text
gives one blip (AC-F06-05), the lines and states that never blip (AC-F06-09), and broken blip
files leave the story playing to its end (AC-F06-12's App half; the service half is
``tests/audio/test_blips.py``). A blip is a play on channel 1."""

import logging

import pygame
import pytest

from engine.audio.limits import BLIP_CHANNEL
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from engine.render.typewriter import TypeState
from engine.ui.blips import BlipPlayer
from engine.ui.screen import Screen
from tests.audio.conftest import BlipMixer
from tests.fakes.fake_mixer import mp3_bytes, ogg_bytes
from tests.fakes.text_app import Session, make_text_game

pytestmark = pytest.mark.display

LINE = "a" * 20                                   # 0.5 s at 40 cps
BLIP = {"blips/a.ogg": ogg_bytes(0.1, salt=b"a")}


class Cover(Screen):
    """An opaque test screen (not in_game: the story holds under it)."""

    opaque = True


def blip_session(tmp_path, script: str, files: dict[str, bytes]
                 ) -> tuple[Session, BlipMixer, list]:
    """App A with ``files`` in ``audio/`` and a service; the list gets every grapheme the
    player sees as ``(frame, grapheme, blipped)`` (``play``)."""
    root = make_text_game(tmp_path / "game", script=script)
    s = Session(root)
    mixer = BlipMixer(clock=s.clock)
    for name, data in files.items():
        path = root / "audio" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if data[:4] == b"OggS":
            mixer.register(data, name, 0.1)
    s.app.audio = AudioService(GamePaths(root.resolve()), SizedLru(1 << 24), AudioConfig(),
                               backend=mixer, clock=s.clock)
    return s, mixer, []


def blips(mixer: BlipMixer) -> int:
    return sum(1 for _, _, args in mixer.actions("channel_play") if args[0] == BLIP_CHANNEL)


def play(s: Session, mixer: BlipMixer, log: list, script) -> None:
    real = BlipPlayer.glyph_shown

    def spy(self, index, grapheme):
        before = blips(mixer)
        real(self, index, grapheme)
        log.append((s.frame, grapheme, blips(mixer) > before))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(BlipPlayer, "glyph_shown", spy)
        s.play(script)


def complete(s: Session):
    yield from s.until(lambda: s.textbox.typer is not None
                       and s.textbox.typer.state is TypeState.COMPLETE)


def next_line(s: Session):
    """Wait until the line is complete, press, and wait for the next ``Say``."""
    count = len(s.said)
    yield from complete(s)
    s.key(pygame.K_SPACE)
    yield from s.until(lambda: len(s.said) > count)


def blipped(log: list, since: int = 0) -> list[str]:
    return [g for _, g, hit in log[since:] if hit]


def test_ac_f06_04_09_the_count_over_waits_and_lines_that_never_blip(tmp_path):
    s, mixer, log = blip_session(tmp_path, (
        'define hana = Character("Hana", blip="blips/a.ogg")\n'
        'define v = Character("V", blip="blips/a.ogg", blip_every=1, blip_pitch=0.2)\n'
        'label start:\n'
        '    hana "You{pause}\'re {pause=0.3}late!"\n'
        '    "Narration here."\n'
        '    voice "voice/v.ogg"\n'
        '    v "Voiced here."\n'
        f'    v "{LINE}"\n'
        '    "End."\n'), {**BLIP, "voice/v.ogg": ogg_bytes(1.0, salt=b"v")})
    seen: dict = {}

    def script(s):
        yield from s.until(lambda: s.textbox is not None and s.said)
        seen["wired"] = (type(s.app.blips) is BlipPlayer, s.app.blips in s.textbox._listeners)
        state = s.app.story.checkpoint()
        yield from s.until(lambda: s.textbox.typer.state is TypeState.WAIT_CLICK)
        for _ in range(10):                            # a click-wait: nothing shows
            yield
        s.key(pygame.K_SPACE)
        yield from next_line(s)                        # narration
        seen["line1"] = blipped(log)
        mark = len(log)
        yield from next_line(s)                        # the voiced line
        yield from complete(s)
        seen["silent"] = blipped(log, mark)
        mark = len(log)
        yield from next_line(s)
        yield from complete(s)
        seen["pitched"] = blipped(log, mark)
        s.app.story.restore(state)
        yield from s.until(lambda: s.textbox.line is not None and s.textbox.line.restored)
        yield

    play(s, mixer, log, script)
    assert seen["wired"] == (True, True)
    assert seen["line1"] == list("Yueae")              # the count goes on over the waits
    assert seen["silent"] == []                         # narration and the voiced line
    assert 5 <= len(seen["pitched"]) <= 13              # 0.5 s, at most one per 40 ms
    assert blipped(log) == list("Yueae") + seen["pitched"]   # the restored line is silent


def test_ac_f06_09_states_that_stop_blips(tmp_path):
    lines = [c * 20 for c in "bcdef"]
    s, mixer, log = blip_session(tmp_path, (
        'define hana = Character("Hana", blip="blips/a.ogg", blip_every=1)\nlabel start:\n'
        + "".join(f'    hana "{text}"\n' for text in lines) + '    "End."\n'), BLIP)
    during: dict = {}

    def held(name: str, start, stop):
        mark = len(log)
        start(s)
        for _ in range(12):
            yield
        during[name] = blipped(log, mark)
        stop(s)

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        s.key(pygame.K_SPACE)                          # a completing press
        mark = len(log)
        for _ in range(12):
            yield
        during["pressed"] = blipped(log, mark)
        yield from next_line(s)
        yield from held("hidden", lambda s: s.textbox.set_hidden(True),
                        lambda s: s.textbox.set_hidden(False))
        yield from next_line(s)
        cover = Cover()
        yield from held("covered", lambda s: s.app.screens.push(cover),
                        lambda s: s.app.screens.remove(cover))
        yield from next_line(s)
        yield from held("skipping", lambda s: s.app.audio.set_skipping(True),
                        lambda s: s.app.audio.set_skipping(False))
        yield from next_line(s)
        yield from held("off", lambda s: s.app.blips.set_enabled(False),
                        lambda s: s.app.blips.set_enabled(True))
        mark = len(log)
        yield from s.until(lambda: len(log) > mark)
        during["on_again"] = [(g, hit) for _, g, hit in log[mark:]][:1]
        yield from complete(s)

    play(s, mixer, log, script)
    assert during["pressed"] == [] and during["hidden"] == [] and during["covered"] == []
    assert during["skipping"] == [] and during["off"] == []
    assert sum(g == "e" for _, g, _hit in log) >= 5      # skipping: typed, but silent
    assert during["on_again"] == [("f", True)]          # the next eligible grapheme


def test_ac_f06_05_instant_text_gives_one_blip(tmp_path):
    text = "Hello there, you."
    s, mixer, log = blip_session(tmp_path, (
        'define hana = Character("Hana", blip="blips/a.ogg", blip_every=1)\nlabel start:\n'
        f'    hana "{{speed=instant}}{text}{{/speed}}"\n    hana "{text}"\n    hana "{text}"\n'
        '    "End."\n'), BLIP)
    counts = []

    def script(s):
        yield from s.until(lambda: s.said)
        counts.append(len(blipped(log)))                # a {speed=instant} span
        s.textbox.settings.instant = True               # the player's instant text
        for _ in range(5):                              # past the 40 ms gap
            yield
        yield from next_line(s)
        counts.append(len(blipped(log)))
        s.textbox.settings.instant = False
        s.textbox.settings.cps = 0                      # cps 0
        for _ in range(5):
            yield
        yield from next_line(s)
        counts.append(len(blipped(log)))

    play(s, mixer, log, script)
    assert counts == [1, 2, 3]


def test_ac_f06_12_broken_blip_files_are_silent_and_the_story_ends(tmp_path, caplog):
    names = {"missing": "blips/gone.ogg", "renamed": "blips/mp3.ogg", "empty": "blips/zero.ogg"}
    script = "".join(f'define {who} = Character("{who}", blip="{file}", blip_every=1)\n'
                     for who, file in names.items()) + "label start:\n"
    script += "".join(f'    {who} "{LINE}"\n    {who} "{LINE}"\n' for who in names)
    script += '    "End."\n'
    s, mixer, log = blip_session(tmp_path, script, {"blips/mp3.ogg": mp3_bytes(),
                                                    "blips/zero.ogg": b""})

    def run(s):
        yield from s.until(lambda: s.said)
        for _ in range(6):
            yield from next_line(s)
        yield from complete(s)
        s.key(pygame.K_SPACE)
        for _ in range(3):
            yield

    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        play(s, mixer, log, run)
    assert s.app.story.status.name == "ENDED"
    assert blips(mixer) == 0 and sum(g == "a" for _, g, _hit in log) == 6 * len(LINE)
    audio = [r.getMessage() for r in caplog.records if r.name == "vn.audio"]
    for file in names.values():
        assert sum(f"audio/{file}" in m for m in audio) == 1, (file, audio)
