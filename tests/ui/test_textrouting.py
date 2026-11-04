"""F52 step P5: the router and the keyboard (``ui/textrouting.py``, ``ui/osk.py``): AC-F52-12
(paste with a fake clipboard) and AC-F52-21 (keys no font draws, W267)."""

import pygame
import pytest

from engine.ui.input import UiEvent
from engine.ui.kbpages import w267_text
from engine.ui.osk import KeyboardServices, OnScreenKeyboard
from engine.ui.textedit import Note
from engine.ui.textfield import TextField
from engine.ui.textrouting import Routed, TextRouter


def key(k: int, mod: int = 0) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod, unicode=""), None, False)


class Clipboard:
    def __init__(self, text: str) -> None:
        self.text = text
        self.reads = 0

    def read(self) -> str:
        self.reads += 1
        return self.text


# --- AC-F52-12: paste ----------------------------------------------------------------------------

@pytest.mark.parametrize(("k", "mod", "pastes"), [
    (pygame.K_v, pygame.KMOD_LCTRL, True),
    (pygame.K_v, pygame.KMOD_LGUI, True),                     # Cmd+V
    (pygame.K_INSERT, pygame.KMOD_LSHIFT, True),
    (pygame.K_v, 0, False),
    (pygame.K_v, pygame.KMOD_LCTRL | pygame.KMOD_LALT, False),  # AltGr+V types, never pastes
    (pygame.K_INSERT, 0, False),
    (pygame.K_c, pygame.KMOD_LCTRL, False),                   # copy: nothing reads or writes
])
def test_ac_f52_12_paste(k, mod, pastes):
    clip = Clipboard("Sayo\nsecond line")
    field = TextField()
    router = TextRouter(read_clipboard=clip.read, open_keyboard=lambda f: None)
    routed = router.route(key(k, mod), None, field, None, minigame=False)
    assert clip.reads == (1 if pastes else 0)
    assert field.text == ("Sayo" if pastes else "")            # the first line only
    assert routed is (Routed.USED if pastes else (Routed.USED if k == pygame.K_v and not mod
                                                 else Routed.PASS))


def test_ac_f52_12_paste_limits_and_notes():
    field = TextField(max_length=200)
    clip = Clipboard("x" * 3_999 + "yz")                       # the first 4,000 code points
    router = TextRouter(read_clipboard=clip.read, open_keyboard=lambda f: None)
    field.paste(clip.read())
    assert field.text == "x" * 200 and field.note is Note.FULL
    field = TextField(allowed="digits")
    field.paste("12a34")
    assert field.text == "1234" and field.note is Note.REFUSED
    big = TextField(max_length=200)
    big.model.paste("ab" * 2_000 + "c")
    assert "c" not in big.text
    # Only on the paste key, and only into the focused field the router got.
    other = TextField()
    router.route(key(pygame.K_v, pygame.KMOD_LCTRL), None, other, None, minigame=False)
    assert clip.reads == 2 and other.text == "x" * 40


# --- AC-F52-21: undrawable allowed characters, W267 ---------------------------------------------

def test_ac_f52_21_undrawable_keys_and_w267():
    warned: list[str] = []
    no_cyrillic = lambda ch: not "Ѐ" <= ch <= "ӿ"     # noqa: E731
    services = KeyboardServices(language=lambda: "en", can_draw=no_cyrillic, warn=warned.append)
    kb = OnScreenKeyboard(services)
    field = TextField(allowed="ABжшщ")
    kb.open_for(field)
    assert [p.keys for p in kb.pages] == [("A", "B")]          # left out of the keyboard
    assert warned == [w267_text(["ж", "ш", "щ"])]
    assert warned[0] == ("this text field allows 3 characters no font of the game can draw "
                         "(ж, ш, щ), so the on-screen keyboard leaves them out. Add a font "
                         "that has them to [theme] ui.text_font, or allow other characters.")
    kb.close()
    kb.open_for(field)                                         # once per field and set
    assert len(warned) == 1
    kb.open_for(TextField(allowed="ABжшщ"))                    # another field: again
    assert len(warned) == 2
    quiet = OnScreenKeyboard(KeyboardServices(can_draw=no_cyrillic, warn=None))   # release
    quiet.open_for(TextField(allowed="ABж"))
    assert [p.keys for p in quiet.pages] == [("A", "B")]
