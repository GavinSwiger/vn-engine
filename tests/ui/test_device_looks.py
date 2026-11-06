"""F65 round 3: the six device looks in the game. Their colors in every color scheme
(``core/devicelooks``, ``ui/devicelook``), how the Inbox draws each look
(``ui/builtin/inbox_view``), the arrival notice's skin, and the arrival sound."""

from types import SimpleNamespace

import pygame
import pytest

from engine.app.inbox import AppInboxPort, install_inbox, thread_parts
from engine.core.config import load_config
from engine.core.config_schema import Config, DeviceTable, ThemeConfig
from engine.core.constants import CANVAS_SIZE
from engine.core.devicelooks import device_palette, pair_ratios
from engine.core.geometry import Viewport
from engine.core.kits import DEVICE_LOOKS
from engine.core.paths import GamePaths
from engine.core.schemes import SCHEMES
from engine.render.canvas import Canvas, RenderQuality
from engine.runtime.commands import MessageArrived
from engine.runtime.inbox import build_delivery, group_threads
from engine.ui.builtin.inbox_view import InboxView, ParaLook, spec_for
from engine.ui.builtin.kind_page import KindPage
from engine.ui.devicelook import notice_skin, palette, rgb, theme_token
from engine.ui.focus import Box, FocusScope
from engine.ui.notice import NoticeLayer, notice_style
from engine.ui.paint import Painter
from engine.ui.theme import Words, measure_with, plain_theme
from engine.ui.widgets import Look
from tests.render.conftest import make_assets

SLOT = Box(416, 112, 808, 552)
LINES = {"phone": [("them", "Ren", "Running late!"), ("me", "", "Front row.")],
         "letters": [("them", "Hana", "The river froze.")],
         "pigeon": [("them", "Hana", "Meet me at the bridge.")],
         "radio": [("them", "Kade", "Do you read?"), ("me", "", "Loud and clear.")],
         "terminal": [("them", "VEGA", "Hull breach."), ("me", "", "Crew?")],
         "mind": [("them", "Voice", "Don't open the door.")]}


@pytest.fixture
def load(tmp_path):
    count = iter(range(1000))

    def load_text(text: str):
        root = tmp_path / f"game{next(count)}"
        root.mkdir()
        (root / "config.toml").write_text(text, encoding="utf-8")
        return load_config(GamePaths.for_game(root))
    return load_text


class FakeCodex:
    def __init__(self, deliveries, contacts):
        self._d = tuple(deliveries)
        self.contacts = contacts

    def deliveries(self):
        return self._d

    def inbox(self):
        return group_threads(self._d, self.contacts)

    def listed(self, kind):
        return tuple(t.key for t in self.inbox()) if kind == "chat" else ()

    def thread_unread(self, key):
        return 0

    def unread(self):
        return 0

    def mark_delivery_read(self, key):
        return True


def delivery(look, time="Day 3"):
    name = LINES[look][0][1]
    return build_delivery("start/0123456789ab", (), name, time, look, LINES[look],
                          sender="sender", message="m")


# --- Colors --------------------------------------------------------------------------------

@pytest.mark.parametrize("scheme", sorted(SCHEMES))
def test_every_look_is_readable_in_every_scheme(load, scheme):
    cfg = load(f'[theme]\npreset = "{scheme}"\n').config.theme
    for look in DEVICE_LOOKS:
        for name, ratio, minimum in pair_ratios(palette(cfg, look)):
            assert ratio >= minimum, (scheme, look, name, round(ratio, 2))


def test_a_pale_author_color_still_gets_readable_text():
    token = theme_token(ThemeConfig())
    pale = device_palette("phone", lambda path: "#FFE0F0" if path == "button.text_color"
                          else token(path))
    assert all(ratio >= minimum for _, ratio, minimum in pair_ratios(pale))
    assert pale.text != "#FFE0F0"


def test_the_looks_differ_where_they_should():
    cfg = ThemeConfig()
    phone, letters, terminal, mind = (palette(cfg, k) for k in
                                      ("phone", "letters", "terminal", "mind"))
    assert phone.card != phone.me_card                    # two kinds of bubble
    assert letters.card != letters.page                   # paper on the panel
    assert terminal.card == "#3D2B36"                     # Sakura's dark text: the screen
    assert mind.card is None and palette(cfg, "radio").card is None   # no frame


# --- The Inbox ------------------------------------------------------------------------------

def test_each_paragraph_says_its_look_and_role_and_a_thought_reads_in_italics():
    letter = delivery("letters")
    (thread,) = group_threads((letter,), {"sender": "Sender"})
    entry, looks = thread_parts(thread, "You")
    assert [(k.look, k.role, k.first, k.last) for k in looks] == [
        ("letters", "via", True, False), ("letters", "them", False, False),
        ("letters", "sign", False, True)]
    assert len(entry.paragraphs) == len(looks)
    (thread,) = group_threads((delivery("mind", ""),), {"sender": "Sender"})
    entry, looks = thread_parts(thread, "You")
    assert [k.role for k in looks] == ["via", "them", "sign"]
    assert all(span.style.italic for span in entry.paragraphs[1].plain())
    # [device.x] reading = "chat" turns a letter look into chat lines.
    config = SimpleNamespace(device={"letters": DeviceTable(reading="chat",
                                                            header_text="Post")})
    (thread,) = group_threads((letter,), {"sender": "Sender"})
    entry, looks = thread_parts(thread, "You", config=config)
    assert [k.role for k in looks] == ["via", "them"]
    assert entry.paragraphs[0].plain()[0].text == "Post · Day 3"


def test_places_follow_the_look():
    width = 600
    them = spec_for(ParaLook("phone", "them"), width)
    me = spec_for(ParaLook("phone", "me"), width)
    assert them.left < me.left and me.align == "end"       # bubbles on two sides
    assert spec_for(ParaLook("letters", "sign"), width).align == "right"
    assert spec_for(ParaLook("letters", "via", first=True), width).align == "center"
    assert spec_for(ParaLook("terminal", "them"), width).mono
    assert spec_for(ParaLook("pigeon", "them"), width).left > \
        spec_for(ParaLook("letters", "them"), width).left  # a smaller note


def _drawn(look, *, reduce=False, config=None):
    config = config or Config()
    theme = plain_theme(config.theme)
    assets = make_assets(None)
    ui = SimpleNamespace(theme=theme, words=Words(), assets=assets, reduce_motion=reduce)
    codex = FakeCodex((delivery(look),), {"sender": "Sender"})
    port = AppInboxPort(lambda: codex, lambda: "You", config=config)
    host = SimpleNamespace(shell=ui, scope=FocusScope(),
                           painter=SimpleNamespace(text_scale=lambda: 1.0))
    page = KindPage(port, "inbox", view=InboxView)
    host.scope.set_groups(page.build(host, SLOT))
    view = page.view
    for _ in range(20):
        view.update(0.05)
    return view, render(view, theme, assets)


def render(view, theme, assets):
    canvas = Canvas(assets)
    frame = pygame.Surface(CANVAS_SIZE)
    canvas.bind(frame, Viewport.compute(CANVAS_SIZE, CANVAS_SIZE), RenderQuality.FINAL)
    painter = Painter(theme)
    painter.bind(canvas)
    canvas.fill((0, 0, 0))
    view.draw(canvas, painter)
    view.body.draw(painter, Look("normal"))
    return frame


def _has(frame, box, color, tol=3):
    for x in range(int(box.x), int(box.right), 3):
        for y in range(int(box.y), int(box.bottom), 3):
            got = frame.get_at((x, y))[:3]
            if all(abs(a - b) <= tol for a, b in zip(got, color)):
                return True
    return False


@pytest.mark.parametrize("look", DEVICE_LOOKS)
def test_the_inbox_draws_each_look_in_its_colors(look):
    view, frame = _drawn(look)
    assert isinstance(view, InboxView)
    body = view.body.box
    c = palette(ThemeConfig(), look)
    if c.card is not None:
        assert _has(frame, body, rgb(c.card)), look
    if look == "phone":                       # the player's bubble is on the right half
        right = Box(body.x + body.w / 2, body.y, body.w / 2, body.h)
        assert _has(frame, right, rgb(c.me_card))
        assert not _has(frame, Box(body.x, body.y, body.w / 4, body.h), rgb(c.me_card))
    if look == "terminal":
        assert _has(frame, body, rgb(c.text))


def test_reduced_motion_holds_the_static_and_the_cursor_still():
    view, _ = _drawn("radio", reduce=True)
    assert view._frame() == 0
    view.update(1.0)
    assert view._frame() == 0
    moving, _ = _drawn("radio")
    before = moving._frame()
    moving.update(0.5)
    assert moving._frame() != before
    # The cursor blinks, except under reduced motion: draws half a blink apart.
    for reduce, same in ((True, True), (False, False)):
        view, first = _drawn("terminal", reduce=reduce)
        view.update(0.55)
        later = render(view, view.ui.theme, view.ui.assets)
        assert (pygame.image.tobytes(first, "RGB") ==
                pygame.image.tobytes(later, "RGB")) is same


# --- The notice and its sound ------------------------------------------------------------------

@pytest.mark.parametrize("look", DEVICE_LOOKS)
def test_the_arrival_notice_wears_the_look(look):
    cfg = ThemeConfig()
    theme = plain_theme(cfg)
    assets = make_assets(None)
    layer = NoticeLayer(notice_style(theme), measure_with(assets, theme.font(
        cfg.notice.text_size)))
    layer.notify("Hello from Hana.", skin=notice_skin(cfg, look))
    layer.update(1.0)
    canvas = Canvas(assets)
    frame = pygame.Surface(CANVAS_SIZE)
    canvas.bind(frame, Viewport.compute(CANVAS_SIZE, CANVAS_SIZE), RenderQuality.FINAL)
    painter = Painter(theme)
    canvas.fill((0, 0, 0))
    layer.draw(canvas, painter)
    (view,) = layer.views()
    c = palette(cfg, look)
    fill = c.card if look in ("phone", "letters", "pigeon", "terminal") else c.page
    inside = Box(view.box.x + 4, view.box.y + 4, view.box.w - 8, view.box.h - 8)
    see_through = look in ("radio", "mind")                    # the panel's opacity
    assert _has(frame, inside, rgb(fill), tol=24 if see_through else 6), look
    assert _has(frame, inside, rgb(c.text), tol=40), look      # text in the look's color
    assert view.lines == ("Hello from Hana.",)                 # same layout as any notice


def _app(*, sound="sfx/wings.ogg", skipping=False):
    played, notices = [], []
    shell = SimpleNamespace(
        words=Words(), replay=None, theme=plain_theme(),
        menus=SimpleNamespace(add=lambda menu, entry: None),
        notify=lambda text, icon=None, skin=None: notices.append((text, skin)),
        open_game_menu=lambda *a, **k: object())
    routes = {}
    program = SimpleNamespace(contacts=(), iter_statements=lambda: iter(()))
    config = SimpleNamespace(theme=ThemeConfig(), device={
        "pigeon": DeviceTable(arrive_sound=sound, arrive_text="A grey bird lands.")})
    app = SimpleNamespace(
        shell=shell, config=config, assets=None,
        router=SimpleNamespace(register=lambda kind, fn: routes.__setitem__(kind, fn)),
        stage_screen=None, skip_auto=SimpleNamespace(skipping=skipping),
        audio=SimpleNamespace(play_ui=played.append),
        story=SimpleNamespace(interp=SimpleNamespace(codex=FakeCodex((), {}),
                                                     program=program), post=lambda e: None))
    install_inbox(app, app.story.interp)
    return SimpleNamespace(arrive=routes[MessageArrived], played=played, notices=notices,
                           app=app)


def test_the_arrival_sound_plays_once_on_arrival_only():
    got = _app()
    got.arrive(MessageArrived("hana", "Hana", "pigeon"))
    assert got.played == ["sfx/wings.ogg"]
    assert got.notices[0][0] == "A grey bird lands."
    assert got.notices[0][1].look == "pigeon"
    got.arrive(MessageArrived("ren", "Ren", "phone"))          # no sound set: silence
    assert got.played == ["sfx/wings.ogg"]
    got.app.shell.replay = object()                            # a scene replay: nothing
    got.arrive(MessageArrived("hana", "Hana", "pigeon"))
    assert got.played == ["sfx/wings.ogg"] and len(got.notices) == 2
    skipping = _app(skipping=True)                             # skipping: the notice only
    skipping.arrive(MessageArrived("hana", "Hana", "pigeon"))
    assert skipping.played == [] and len(skipping.notices) == 1
