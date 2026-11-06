# UI system

The single reference for vn-engine's UI conventions: coordinates, layers, theme token
names, fixed engine colors, standard timings, input, text, and widgets. Owned by
`vn-ui-designer`. Feature `03-ui.md` documents follow this file and list only what differs.

Entries marked **(proposed, Fxx)** become plain entries when that feature is approved.
F10 owns the widget toolkit, focus, navigation, and "back"; its conventions are §9, and
[F10 03-ui](../specs/F10-ui-framework/03-ui.md) is the full reference.

## 1. Canvas and coordinates

- All UI is laid out on a fixed **1280×720 canvas**, scaled uniformly into the window and
  letterboxed (PR-F01-21, 22; ADR-0001). The bars use `[window] letterbox_color`; only
  the engine paints them. Nothing a feature draws reaches the bars.
- **Units.** "px" and "units" in every spec mean **canvas units**, never device pixels.
  Sizes, positions, font sizes, line widths, and padding are all in canvas units.
- **Axes.** Origin (0, 0) is the top-left corner. x grows right to 1280, y grows down
  to 720. Mouse positions are reported the same way (PR-F01-24).
- **Off-canvas.** A position may lie outside the canvas (F04 allows −1,280 to 2,560).
  Whatever falls outside is cut at the canvas edge.
- **Sharpness.** Art and text are drawn at the window's real resolution, so a layout
  never changes with window size, and text line breaks never depend on it (ADR-0001).
  After a resize, the first 200 ms may be drawn softer (see §5), never misplaced.
- **Rounding.** Edges land within 1 device pixel of their exact scaled position. A shape
  that must cover the whole canvas (a background) rounds its size up so no edge is left
  unpainted.

### Anchors

An element's **anchor** is the point of its box that sits on its position. Names follow
pygame's `Rect` attributes:

```
topleft ──── midtop ──── topright
   │                        │
midleft      center      midright
   │                        │
bottomleft ─ midbottom ─ bottomright
```

Specs give each element's anchor and position in a layout table (element, anchor,
position/size, theme tokens). Example: a sprite is anchored `midbottom` (F04).

### Standard stage positions

| Name | Anchor point | Notes |
|---|---|---|
| `left` | (320, 720) | Authors may redefine all three (PR-F04-14). |
| `center` | (640, 720) | Default for a sprite shown with no position. |
| `right` | (960, 720) | |

Spacing is 320 units, so 320-unit-wide sprites at these positions touch without
overlapping.

### In-game screen regions

| Region | Rectangle (default theme) | Owner |
|---|---|---|
| Say window (ADV textbox) | 1000 wide, `midbottom` at (640, 688); 184–216 tall, plus a 44-tall name tab above its left end | F05 |
| Say window (NVL, full-screen text) | Panel: the whole canvas. Text column: `nvl.width` (920) wide, centered at x 640 (x 180–1100), from `nvl.top_gap` (y 64) to 720 − `nvl.bottom_gap` (y 648); 14 rows at size 28, 9 at 42. A name takes its own row above its line; lines are `nvl.line_gap` (20) apart. In a menu the choices stack from just under the page's last row (24 below it) down to the column's bottom | F17 |
| Quick-menu strip | y 688–720, full width (`textbox.bottom_gap`, 32). The quick-menu pill is centered at x 640 and stays inside the strip: height h = text size + 8, bottom at 720 − min(`quick_menu.bottom_gap`, max(0, strip − h)). Default: y 690–718 at 100% text (choice floor 686), y 688–720 at 150% (floor 684). A strip shorter than 28 lets the pill overlap the box (F10 I-4) | F10 |
| Skip / auto indicator | One pill, `topleft` (24, 24), quick-menu `on` look (proposed, F15) | F15 |
| Rewind tag | `topleft` (24, 24), or 8 right of the F15 pill while it shows; 28 tall | F14 |
| Limit mark | 56×28, centered on the say window's top edge at x 640 + `textbox.width` / 2 − 52 (1088, 504) | F14 |
| Notice area | Top-right corner: `topright` (1256, 24), up to `notice.max_width` (560) wide, ending by y 400 | F11 (shared, §9) |
| Status corner | Four stacks `corner.margin` (24) in from each canvas corner, growing inward; never over the say window and its tab (ADV), the NVL text column, the quick-menu pill, or the indicator row at (24, 24). Top stacks end by y 360 (§9 "Status corner") | F61 |

Faces of sprites belong above y = 400; nothing F05 draws reaches above that at any text
size (box top ≥ 472, tab top ≥ 410 at name size 48). F07's choice area must end above the
quick-menu pill while it shows (F10 03-ui, Conflict C1). Notices may lie over choices and
sprites; they never take input, so clicks reach what is below.

### Minigame screen regions

The frame every minigame plugin gets
([F23 03-ui](../specs/F23-minigame-api/03-ui.md)). The heading and hint are optional, and
the plugin turns them on.

| Region | Rectangle (default theme) | Use |
|---|---|---|
| Heading | `topleft` (24, 24); pitch + 16 tall (61); text + 40 wide, 160–560 | Display title, `panel.heading.*` on `panel.*` |
| Hint bar | `midbottom` (640, 696); 320–1000 wide; lines × pitch + 24 tall (58), ≤ 2 lines | Instructions, `minigame.hint.text_size` on `panel.*` |
| Content area | x 24–1256; y from 24 (or heading bottom + 16) to 696 (or hint top − 16) | The plugin's widgets; given to the plugin after every relayout |
| Cue point | The hint bar's top edge, 52 in from its right end; else (1088, 668); or the plugin's own point | F14's limit mark, no bump |

F11's notice area stays top right over a minigame and never overlaps the heading.

### Menu screen regions

| Region | Rectangle | Use |
|---|---|---|
| Game-menu sidebar | (24, 24), 336×672 | Navigation column, centered at (192, 360) |
| Game-menu content panel | (384, 24), 872×672 | Later pages (F11, F13, F16, Help) |
| Page heading | topleft (416, 56) | Page name |
| Page body slot | (416, 112), 808×552 | Each page's widgets |
| Confirm dialog | centered at (640, 360), 640 wide | Every yes/no question |
| Title logo box / button column | (80, 48) 560×200 / from (80, 288), 320 wide | Title screen |
| Content warning panel | x 120–1160 (1040 wide), ≤ 624 tall (y 48–672), centered on y 360; text wrapped at 924 | F33's warning before the title, over the title gradient |
| Flowchart viewport / detail panel | (416, 112) 808 × H_c / (416, 124 + H_c) 808 × H_d, ending y 664; H_d 150 (208 at 150%), H_c = 540 − H_d | F20's chart and its node details ([F20 03-ui](../specs/F20-flowchart/03-ui.md)) |

A page opened from the title (F11 Load, F16 Settings) uses the game-menu layout over the
title background; its sidebar is Return, then the title's entries that have pages, in
title order (F10 G2, confirmed by F11).

**Sidebar fit.** When the navigation column doesn't fit in 640, these
steps apply in order, each only if still needed:
1. Gaps become 4 (F10).
2. Button height becomes max(48, pitch + 8).
3. The label size steps down by 2, not below 24.

Nine entries (Codex, Skip Game) fit at 150% at step 2. With Codex and Flowchart
the in-game sidebar has 9 entries and fits at step 2 (635 of 640); a 10th (Skip Game or
Help) fits at step 3 with labels at 36. With F65's Inbox all twelve entries can show: at
100% they fit at step 2 (48 tall), at 150% at step 3 with labels at 28.

**Title fit (F20).** F10's title column fit gains a third step: button height
becomes max(48, pitch + 8), as sidebar step 2. With Flowchart, 7 title entries fit at 150%
with a 123-tall logo box (F10's minimum is 80).

## 2. Layers (z-order)

Within the in-game screen, from back to front. A higher row is always drawn over a lower
one, whatever numbers are used inside a row (a sprite at layer 100 is still under the
textbox).

| # | Layer | Owner | Contents |
|---|---|---|---|
| 1 | Stage | F04 | Background, then sprites by layer number (−100 to 100) and stage order. Paints every canvas pixel. |
| 2 | Stage effects | F09; F28 | Effects that act on the stage picture. **Shake** (proposed, F09): the whole stage picture drawn offset in whole canvas units; the uncovered edge band, at most the shake's size wide (≤ 24 units), shows `stage.empty_color`. **Flash** (proposed, F09): a color over the whole stage area, never over layers 3–6. **Glitches** (F28), in this order over the shaken picture: color shift (the stage picture itself filtered, transitions included: a red copy offset left and a blue copy right, green in place), jitter (one sprite's picture drawn again at a small offset over itself, clipped to the stage), tear (2–6 bands of the picture slide sideways and wrap within the canvas width), and static (gray noise over the stage area); flash goes on top. Glitches never draw over layers 3–6; they keep running behind choices, menus, and the hidden textbox, and their clock freezes with the effect clock. Tint: reserved. A transition (proposed, F09) isn't a layer: it replaces layer 1's picture while it runs, and layers 3–6 never move or fade with it. |
| 3 | Say window | F05, F17 | Textbox, name tab, continue indicator; or, in full-screen text (F17), the NVL panel: `nvl.fill_color` at `nvl.fill_opacity` over the whole canvas, with the page's lines in the text column. Never both in one frame. The quick menu, choices, and cues draw over the panel. |
| 4 | In-game overlays | F10, F14; F15 (proposed) | Quick menu (F10); skip/auto indicator (F15); rewind tag (F14). |
| 5 | Choices | F07 | The open menu's buttons, one stack centered at x 640 in the choice area (y 16 to 16 above the name tab's top; with no text box, to the quick-menu floor, 686 at 100%), over the say window. Hidden with layers 3 and 4 in hidden mode (any input then only shows them). Picks are ignored for 250 ms after the buttons appear. |
| 6 | In-game cues | F14 | The shell's one cue slot (`GameShell.set_cue_layer`), drawn after the scene captures and before notices: the rollback limit mark, over choices, for at most 500 ms. Never in `scene_picture()`, a save thumbnail, or a menu backdrop, and not drawn while a menu-type screen covers the game or in error mode. Also drawn over a running minigame at its cue point. |

**Hidden mode.** H, middle click, or gamepad north hides
layers 3 and 4 instantly; the stage stays. Any advance input, H, middle click, or north
shows them again without advancing. The quick menu is also hidden whenever the say window
is not drawn.

**Screens above.** Above the in-game screen, whole screens stack in
screen-stack order (architecture, "Screen stack"). The **title** is an opaque bottom
screen when no game runs.

The **minigame screen** sits directly above the in-game screen and paints
every pixel: its own backdrop, or the frozen stage under `minigame.stage_dim_opacity`. While
it shows, layers 3 and 4 are not drawn. Layer 6 cues, notices, and the dev overlay are still
drawn above it. Any menu-type screen over it freezes it, with no time and no input.

The **game menu** covers the frozen in-game screen with a full-canvas dim
(`menu.dim_color` at `menu.dim_opacity`) and its panels; its pages draw inside it. A
**confirm dialog** is always the top screen, with its own extra dim. Every menu-type screen
dims what is below rather than hiding it, unless it is full-screen by design (title, dev
sampler). **Notices** are drawn over every screen, confirms included, and
stay in hidden mode. They are never part of a scene picture or save thumbnail. On top of
everything: the dev overlay (F3, dev runs only, F01). The error screen (F01) replaces all
screens and drops every notice.

The **fake crash screen** (F30, `effect crash`) sits directly above the in-game screen
and paints every pixel in the error screen's fixed look (section 4): heading, message,
the game's title and version, the hint at y 640, and, when the player turns on "Label
fake error screens", the label at y 680. It has no widgets and no images; the stage
under it is frozen and not drawn while it is opaque. It appears and leaves with one cut
(a 300 ms fade under reduced motion), ignores input for its first 0.5 s of drawn time,
then continues on Enter, Space, Esc, pad A or B, or a click in the canvas; every other
input is swallowed. Notices wait until it leaves. It is never in a save thumbnail (no
save is made while it shows; the quit auto-save has no picture), and closing the window
quits at once. A real error replaces it like any screen.

The **first-launch name question** (F30, `[meta] username = true`) comes after F33's
content warning and before the title: an opaque title-gradient ground under a confirm
dialog ("Allow" / "Don't allow", the latter focused). "Allow" ignores presses, with
no click sound, until 0.5 s of drawn time has passed and the press began after the
dialog's first frame. While the player's name is on screen (text box, NVL page, or a
menu question), scene pictures for save thumbnails and the kept backdrop leave out
layers 3 and above.

**Thumbnail during a minigame.** A save made while a minigame is running or
paused uses the minigame's **opening picture**: the frame drawn when its fade-in ended. It
does not use the current frame or the menu backdrop.

Owners of reserved rows confirm or adjust them in their `03-ui.md`.

## 3. Theme tokens

Every color, font, size, frame image, and sound a feature draws or plays comes from a
theme token, so authors restyle a game without engine code. Exceptions are the fixed
engine colors in §4.

### Naming

`<area>.<element>.<property>`, all lower-case `snake_case`, dotted. The element part is
dropped when the property belongs to the whole area.

- **area**: the feature's domain: `stage`, `textbox`, `choice`, and F10's `ui` (shared
  UI font, fades, back sound), `panel`, `button`, `toggle`, `slider`, `list`, `title`,
  `menu`, `quick_menu`, `confirm`; `save` and `notice`; `rollback`; `nvl` (full-screen
  text);
  `minigame` (the frame) and `plugin`; `flowchart` (F20);
  `effects` (proposed, F09).
  Grid cells use `button`.
- **Plugin tokens.** A minigame plugin declares its own tokens under
  `plugin.<minigame name>.<element>.<property>`, set in `[theme.plugin.<name>]`. Each has a
  type by the suffix below, a default (a value or another token's name), and a range. Its
  words live in `[words.plugin.<name>]`, where `title` is the display title. The usual
  validation and warnings apply.
- **element**: a part of it: `name_tab`, `indicator`, `heading`, `logo`, `badge`, …
- **state** (optional, before the property): `focused` (hover and keyboard focus share
  it), `pressed`, `disabled`, `selected`, `on`, `locked`. Example:
  `button.focused.border_color`. F10's widgets all take their focused look from
  `button.focused.*`.
- **property** ends with its type:

| Suffix | Type | Value in `config.toml` | Example |
|---|---|---|---|
| `_color` | color | `"#RRGGBB"`; translucency is a separate `_opacity` token | `stage.empty_color` |
| `_opacity` | opacity | number 0.0 (invisible) to 1.0 (opaque); multiplies the paired fill or frame image | `textbox.fill_opacity` |
| `_font` | font file | path in the game folder | `textbox.text_font` |
| `_size` | font size | int, canvas units | `textbox.text_size` |
| `_width`, `_height`, `_padding`, `_gap`, `_radius` | length | int, canvas units | `textbox.side_padding` |
| `_image` | image (nine-slice frames say so in their spec) | path, usually under `gui/` | `textbox.frame_image` |
| `_sound` | sound | path, usually under `audio/`; plays on F08's UI channels | `button.activate_sound` |
| `music` | music file | path, usually under `audio/`; looped on the music channel | `title.music` |
| `_ms` | duration | int, milliseconds | `choice.fade_in_ms` |

Durations and easings are tokens only when an author would plausibly change them. A token
whose default is another token's name (`ui.text_font` = `textbox.text_font`) follows that
token unless the author sets it.

### Frames and fills

- A panel is a filled rounded rectangle (`fill_color`, `fill_opacity`, `corner_radius`)
  with an inside border (`border_color`, `border_width`), or a **nine-slice**
  `frame_image` that replaces fill and border. Nine-slice: corners of
  `frame_slice_width` drawn unscaled, edges and center stretched, multiplied by
  `fill_opacity`.
- A missing or unusable frame image falls back to the drawn fill and border with a
  warning (F05 W43, F10 W64), never to the checkerboard, so text over it stays readable.
- **Per state.** A widget state may have its own `frame_image`
  (`button.focused.frame_image`); it replaces that state's fill and border only.
- Colors blend in sRGB as drawn.

### Where authors set them

In `game/config.toml`, under `[theme]`, using the token name as the key path. These two
forms are the same in TOML:

```toml
[theme.stage]
empty_color = "#000000"
```
```toml
[theme]
stage.empty_color = "#000000"
```

Nested elements and states use nested tables: `[theme.textbox.name_tab]`,
`[theme.button.focused]`. Unknown or invalid tokens follow the `config.toml` error and
warning rules (architecture, "Configuration"). Button words are not tokens; they live in
a separate table (F10 OQ-2).

**Looks that change at run time (F32).** A `[playthrough.N]` table (title tokens, words,
`title_entries`) and a `[style.<name>]` table (`textbox`, `choice`, `nvl`, `quick_menu`
tokens and words, and a color scheme `preset`) are layers over `[theme]`. Lookup order
for a token: style (own tokens, then its scheme) → playthrough table → `[theme]` tokens →
`[theme] preset`'s scheme → engine default. See script-language.md, "Dynamic UI", and
the color schemes below. `GameShell.theme` is a property that follows the
current look, so screens read their tokens through it each time and never keep an old
theme; a look is built once per combination and never changed in place. Player settings
win over every layer: F16's text size scales the looked-up size (a style's 40 at 150 % is
capped at 48), and reduce motion turns every fade into a cut. On a `ui style` switch the
text box's colors and frame change on the shown box at once and its text with the next
line; the quick menu takes the whole style at once. Error screens and F30's fake crash
never use a look.

**Color schemes (F49).** `[theme] preset = "<id>"` picks one of 28 built-in schemes,
which sets every mapped color token to its role's color (Studio: Game settings > Color
scheme). Colors you set under `[theme]` still win: the scheme layer sits under the
`[theme]` tokens in the lookup order above. A scheme sets colors only, never fonts, sizes,
opacities, frame images or sounds. A style may name its own scheme
(`[style.<name>.theme] preset`), which sets every mapped color except `title.*` while the
style is on, under the style's own tokens; `ui style off` returns to the main look.
`preset = "sakura"` is the same as no preset. An unknown id gives one config warning
(with a did-you-mean) and the engine colors show.

**Your own scheme (2026-11-05).** `[theme.scheme]` sets any of the eleven role colors
(`fill`, `text`, `border`, `accent`, `accent2`, `soft`, `focus`, `pressed`, `muted`,
`track`, `toggle`) plus a `name` for Studio's card. Each role set replaces that role of the
preset's scheme (Sakura's without a preset); the scheme's single-token extras are dropped
once any role is replaced (`schemes.custom_colors`). Studio's Import palette writes all
eleven from a palette (`engine/core/palette.py`: `.ase`, `.act`, `.gpl`, `.pal`, Paint.NET
`.txt`, Lospec `.hex`, Coolors links, CSS colors). Roles are derived as theme builders do
from seed colors: the lightest or darkest color is the background (moved until 7:1 text
fits on it), the most colorful readable one the accent, the most contrasting the text, and
the in-between fills are mixed from background and accent. Text, accents, muted text and
tracks are then moved toward black or white until each W67 pair passes, with see-through
fills checked over black and white. The 22 genre schemes after `groovy` were made the same
way from five picked colors (`palette.complete_roles`), so they give no W67 warnings.

| id | Name | fill | text | border | accent | accent2 | soft | focus | pressed | muted | track | toggle |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `sakura` | Sakura | #FFF4F8 | #3D2B36 | #F0A0C0 | #A02860 | #A02860 | #FFE6F0 | #FFD6E8 | #FFC2DC | #6E5E68 | #C8B8C2 | #7E5C74 |
| `pocket` | Pocket LCD | #9BBC0F | #0F380F | #306230 | #0F380F | #0F380F | #8BAC0F | #C4D96A | #8BAC0F | #244A24 | #8BAC0F | #306230 |
| `amber` | Amber Terminal | #140C02 | #FFB000 | #9A6800 | #FFCC00 | #FFCC00 | #2A1A04 | #3A2604 | #4A3006 | #B07A14 | #3A2604 | #9A6800 |
| `synthwave` | Synthwave Sunset | #262335 | #F2E9FF | #CA7CD8 | #FF68A8 | #64CFF7 | #34294F | #3D2E5C | #4A3570 | #9A90B4 | #4A3F66 | #5A4A7A |
| `vaporwave` | Vaporwave Dream | #FBE6F8 | #3A2B5C | #9F63C4 | #674AB3 | #137566 | #C6F5F2 | #C6F5F2 | #A8EDE6 | #6E5E82 | #D8C8E8 | #9F63C4 |
| `groovy` | Groovy '70s | #F3E6C8 | #3B2416 | #D08A1E | #9E3A12 | #2F6F6A | #F2D49B | #F2D49B | #E8C07A | #6E5848 | #D9C9A8 | #8A6A4A |

- **Mapped tokens** (64) take a role's color, for example `fill` sets every area's
  `fill_color`, `accent` the markers, headings and slider fill. The full role → token map
  is `engine/core/schemes.py` (`ROLE_TOKENS`). Sakura also sets a few single tokens to
  today's defaults, so it equals the engine colors exactly.
- **Following tokens** (18) are left unset and keep following another token: `nvl.*`,
  `notice.*`, `codex.*`, the flowchart's text, gate, unknown, path and "here" colors, and
  `minigame.fill_*`.
- **Neutral tokens** (6) are never set: `stage.empty_color`, `effects.flash_color`,
  `effects.fade_color`, `gallery.viewer.fill_color`, `menu.dim_color` and
  `title.loading.text_color`.
- Every new color token joins one of these groups.
- **Contrast warnings.** The non-Sakura schemes give some dev-run W67 contrast warnings
  (accepted, F49 D1). When both colors of a W67 pair come from the scheme, the warning
  ends with one more sentence: ` Both colors come from the {name} color scheme.` (a style's
  warnings name the style's scheme, else the main one). If either color is yours, it is
  left out.

**Genre kits (F60).** `[theme] kit = "<id>"` dresses the shared systems for a genre:
`romance`, `horror`, `mystery`, `fantasy`, `cozy`, `scifi` or `letters`
(`engine/core/kits.py`; Studio: Game settings > Kit). A kit fills in only what the author
left unset; today that is how a shown meter looks (`bar`, `number`, `hearts`, `pips` or
`dial`, from `skins.METER_LOOKS`), which corner it sits in (`skins.CORNER_PLACES`) and the
meter presets Studio suggests. Lookup order for a meter: its own `[meter.<name>]` table
(F62 round 2), then the kit, then the defaults (`bar`, `top_left`, a label from the
variable name): `kits.meter_look(config, meter)`. A kit suggests a color scheme but never
sets one: Studio's Apply writes `preset` too only when asked. An unknown id gives one
config warning (with a did-you-mean) and the game runs with no kit. Messages, clock,
items and checks join the kit as those systems land.

### Token list

| Token | Type | Default | Purpose |
|---|---|---|---|
| `stage.empty_color` | color | `"#000000"` | Fill of the empty stage (new game, `scene` with no image). |

**Stage effects (proposed, F09).** Set in `[theme.effects]`. Purposes are in
[F09 01-design](../specs/F09-transitions/01-design.md) §6.4; the lengths and the shake
size are behavior keys in `[effects]` (`dissolve`, `fade`, `shake`, `shake_size`, `flash`,
`reduce`), not tokens. The shake's edge band reuses `stage.empty_color`.

| Token | Type | Default | Purpose |
|---|---|---|---|
| `effects.flash_color` | color | `"#FFFFFF"` | Default `flash` color. |
| `effects.fade_color` | color | `"#000000"` | Default `fade` color. |

**Textbox.** Ranges and details are in
[F05 03-ui](../specs/F05-adv-textbox/03-ui.md), Theme tokens. F10 makes every one settable
in `[theme.textbox]` (PR-F10-16).

| Token | Type | Default | Purpose |
|---|---|---|---|
| `textbox.text_font` | font | bundled Noto Sans Regular | Body text. |
| `textbox.bold_font` | font | bundled Noto Sans Bold | Bold runs. |
| `textbox.italic_font` | font | bundled Noto Sans Italic | Italic runs. |
| `textbox.bold_italic_font` | font | bundled Noto Sans Bold Italic | Bold italic runs. |
| `textbox.text_size` | size | 28 (20–48) | Body size. |
| `textbox.text_color` | color | `"#3D2B36"` | Body text. |
| `textbox.fill_color` | color | `"#FFF4F8"` | Box fill. |
| `textbox.fill_opacity` | opacity | 0.80 | Box fill / frame opacity. |
| `textbox.border_color` | color | `"#F0A0C0"` | Box and tab border. |
| `textbox.border_width` | length | 2 | Box and tab border. |
| `textbox.corner_radius` | length | 16 | Box corners. |
| `textbox.frame_image` | image (nine-slice) | none | Replaces box fill and border. |
| `textbox.frame_slice_width` | length | 24 | Nine-slice corner size (box and tab). |
| `textbox.width` | length | 1000 | Box width. |
| `textbox.height` | length | 184 | Minimum box height; grows to 216 with text size. |
| `textbox.bottom_gap` | length | 32 | Canvas bottom to box bottom (quick-menu strip). |
| `textbox.side_padding` | length | 40 | Box edge to text, left/right. |
| `textbox.top_padding` | length | 28 | Box top to first line. |
| `textbox.bottom_padding` | length | 28 | Last line to box bottom. |
| `textbox.name_tab.text_font` | font | `textbox.bold_font` | Name text. |
| `textbox.name_tab.text_size` | size | 28 (20–48) | Name text. |
| `textbox.name_tab.text_color` | color | `"#A02860"` | Default name color; `Character` color overrides. |
| `textbox.name_tab.fill_color` | color | `"#FFE6F0"` | Tab fill. |
| `textbox.name_tab.fill_opacity` | opacity | 1.0 | Tab fill opacity. |
| `textbox.name_tab.frame_image` | image (nine-slice) | none | Replaces tab fill and border. |
| `textbox.name_tab.corner_radius` | length | 12 | Tab top corners. |
| `textbox.name_tab.left_gap` | length | 24 | Box left edge to tab. |
| `textbox.name_tab.side_padding` | length | 20 | Tab edge to name. |
| `textbox.name_tab.min_width` | length | 120 | Tab minimum width (maximum is half the box). |
| `textbox.indicator.fill_color` | color | `"#A02860"` | Continue indicators. |
| `textbox.indicator.line_image` | image | none | Replaces the line indicator shape. |
| `textbox.indicator.page_image` | image | none | Replaces the page indicator shape. |

**Choices (F07).** Set in `[theme.choice]` (sub-tables `[theme.choice.focused]`,
`[theme.choice.marker]`, `[theme.choice.locked]`); layout, states, and the fit rule are in
[F07 01-design](../specs/F07-choice-menus/01-design.md) §6. Ranges are F07 `04` §13's. Border
and marks are opaque; `fill_opacity` applies to the fill or frame only. Sounds are files
inside `audio/`, played on the UI sound pool; a missing one is warned about (W48) and stays
silent. Behavior lives in `[choice] show_locked` (`false`: choices whose condition is false
are hidden; `true`: shown locked, never pickable).

| Token | Type | Default | Purpose |
|---|---|---|---|
| `choice.text_font` | font | `textbox.text_font` | Choice text; bold and italic faces are the text box's. |
| `choice.text_size` | size | `textbox.text_size` (20–48) | Size before the fit rule; the player's text size scales it. |
| `choice.text_color` | color | `"#3D2B36"` | Normal and focused text. |
| `choice.fill_color` | color | `"#FFF4F8"` | Button fill. |
| `choice.fill_opacity` | opacity | 0.90 | Fill or frame opacity (normal and focused). |
| `choice.border_color` | color | `"#F0A0C0"` | Normal border. |
| `choice.border_width` | length | 2 (0–16) | Normal border. |
| `choice.corner_radius` | length | 12 (0–64) | Corners. |
| `choice.frame_image` | image (nine-slice) | none | Replaces fill and border (normal and locked). |
| `choice.frame_slice_width` | length | 24 (1–128) | Nine-slice corner size. |
| `choice.width` | length | 800 (400–1200) | Button width. |
| `choice.gap` | length | 12 (0–64) | Between buttons (4 when the stack doesn't fit). |
| `choice.side_padding` | length | 40 (0–200) | Edge to text; the text width is max(100, width − 2 × side_padding). |
| `choice.top_padding` | length | 10 (0–64) | Top edge to text. |
| `choice.bottom_padding` | length | 10 (0–64) | Text to bottom edge. |
| `choice.focused.fill_color` | color | `"#FFD6E8"` | Focused fill. |
| `choice.focused.border_color` | color | `"#A02860"` | Focused border. |
| `choice.focused.border_width` | length | 4 (0–16) | Focused border. |
| `choice.focused.frame_image` | image (nine-slice) | none | Focused frame. |
| `choice.marker.fill_color` | color | `"#A02860"` | Focus marker: a triangle 12 × 16, 16 inside the left edge. |
| `choice.locked.text_color` | color | `"#6E5E68"` | Locked text and its lock mark. |
| `choice.locked.fill_opacity` | opacity | 0.90 | Locked fill; at 0.90 locked text reads at 4.5:1. |
| `choice.focus_sound` | sound | none | Played on each focus change (never on clearing it). |
| `choice.pick_sound` | sound | none | Played on a pick. |
| `choice.fade_in_ms` | duration | 120 (0–1000) | Appear fade (§5). |
| `choice.timer.fill_color` | color | follows `choice.marker.fill_color` (`#A02860`) | Timed menus (F51): the bar's time left. |
| `choice.timer.track_color` | color | follows `choice.focused.fill_color` (`#FFD6E8`) | Timed menus (F51): the bar's time used. |
| `choice.timer.tick_sound` | sound | none | Timed menus (F51): played at 3, 2 and 1 seconds left. |

**Timed menus (F51).** A `menu time N:` shows a countdown panel as the first item of the
choice stack: `choice.width` wide, centered, `choice.gap` above the first button, `t + 12`
tall where `t` is the number's size, `round_half_up(24 × the player's text scale)` clamped to
20–36 (36 tall at 100 % text, 48 at 150 %). The fit steps count it as part of the stack, and
in full-screen text it heads the stack under the page. Its frame is `choice.fill_color` at
`choice.fill_opacity` with `choice.border_color` `choice.border_width` and radius
`min(choice.corner_radius, height / 2)`, never a frame image. Inside it: the whole seconds
left (rounded up) in `choice.text_font` at size `t` and `choice.text_color`, right-aligned 16
inside the right edge in a slot as wide as "60"; and an 8-tall bar, vertically centered, from
16 inside the left edge to 16 left of the number slot, its track `choice.timer.track_color`
and its fill `choice.timer.fill_color`, `track width × time left / total` wide from the left.
The bar is never the only cue: the number always shows with it. The panel is never focused,
takes no input, fades with the choices and hides with them. Both colors are in F49's
following group, so every color scheme styles them; fill on track is 3.5:1 in Sakura and at
least 3:1 in every built-in scheme.

**Full-screen text (F17).** Set in `[theme.nvl]` (sub-tables `[theme.nvl.name]`,
`[theme.nvl.indicator]`); layout and states are in
[F17 01-design](../specs/F17-nvl-mode/01-design.md) §6. Faces, indicator images, and the bob
are the text box's. A token with a `textbox.*` default follows that token unless set.
Out-of-range values are config errors and the default is kept.

| Token | Type | Default | Purpose |
|---|---|---|---|
| `nvl.fill_color` | color | `textbox.fill_color` (`"#FFF4F8"`) | Panel fill. |
| `nvl.fill_opacity` | opacity | 0.85 (0.5–1.0) | Panel opacity; under 0.5 text over art can't keep 4.5:1. |
| `nvl.width` | length | 920 (640–1200) | Text column, centered at x 640. |
| `nvl.top_gap` | length | 64 (24–200) | Canvas top to the first row. |
| `nvl.bottom_gap` | length | 72 (40–200) | Last row bottom to canvas bottom; 40 or more keeps the quick menu clear. |
| `nvl.line_gap` | length | 20 (0–80) | Between one line's last row and the next line's name or first row. |
| `nvl.text_size` | size | `textbox.text_size` (20–48) | Body and name size before the player's text size scales it. |
| `nvl.text_color` | color | `textbox.text_color` | Body text. |
| `nvl.name.text_color` | color | `textbox.name_tab.text_color` | Default name color; a `Character` color overrides. |
| `nvl.indicator.fill_color` | color | `textbox.indicator.fill_color` | Continue indicators. |

**UI framework (F10).** Ranges and purposes are in
[F10 03-ui](../specs/F10-ui-framework/03-ui.md), Theme tokens.

| Token | Type | Default |
|---|---|---|
| `ui.text_font`, `ui.bold_font` | font | `textbox.text_font`, `textbox.bold_font` |
| `ui.fade_ms` | duration | 150 |
| `ui.back_sound` | sound | none |
| `panel.fill_color`, `.fill_opacity` | color, opacity | `"#FFF4F8"`, 0.94 |
| `panel.border_color`, `.border_width`, `.corner_radius` | color, length, length | `"#F0A0C0"`, 2, 16 |
| `panel.frame_image`, `.frame_slice_width` | image (nine-slice), length | none, 24 |
| `panel.text_size`, `.text_color` | size, color | 28, `"#3D2B36"` |
| `panel.heading.text_size`, `.text_color` | size, color | 32, `"#A02860"` |
| `button.text_size`, `.text_color` | size, color | 28, `"#3D2B36"` |
| `button.fill_color`, `.fill_opacity` | color, opacity | `"#FFF4F8"`, 0.90 |
| `button.border_color`, `.border_width`, `.corner_radius` | color, length, length | `"#F0A0C0"`, 2, 12 |
| `button.frame_image`, `.frame_slice_width` | image (nine-slice), length | none, 24 |
| `button.height`, `.side_padding`, `.gap` | length | 56, 32, 12 |
| `button.focused.fill_color`, `.border_color`, `.border_width`, `.frame_image` | color, color, length, image | `"#FFD6E8"`, `"#A02860"`, 4, none |
| `button.pressed.fill_color`, `.frame_image` | color, image | `"#FFC2DC"`, none |
| `button.selected.frame_image` | image | none |
| `button.disabled.text_color`, `.border_width`, `.track_color`, `.frame_image` | color, length, color, image | `"#6E5E68"`, 0, `"#C8B8C2"`, none |
| `button.marker.fill_color` | color | `"#A02860"` |
| `button.focus_sound`, `.activate_sound` | sound | none |
| `toggle.track_color`, `toggle.on.track_color`, `toggle.on.knob_color` | color | `"#7E5C74"`, `"#A02860"`, `"#FFFFFF"` |
| `slider.track_color`, `.fill_color`, `.thumb_color`, `.thumb_border_color` | color | `"#7E5C74"`, `"#A02860"`, `"#A02860"`, `"#FFF4F8"` |
| `list.row_height` | length | 48 |
| `list.divider_color`, `.scrollbar_color`, `.scrollbar_track_color`, `list.empty.text_color` | color | `"#F0A0C0"`, `"#A02860"`, `"#F0D0DE"`, `"#6E5E68"` |
| `title.background_image`, `.logo_image` | image | none |
| `title.music` | music | none |
| `title.fill_top_color`, `.fill_bottom_color` | color | `"#FFF4F8"`, `"#FFD6E8"` |
| `title.logo.text_size`, `.text_color` | size, color | 64, `"#A02860"` |
| `title.button_width` | length | 320 |
| `title.version.text_size`, `.text_color`, `.fill_opacity` | size, color, opacity | 20, `"#6E5E68"`, 0.90 |
| `title.loading.text_color` | color | `"#FFE6F0"` |
| `title.fade_in_ms` | duration | 500 |
| `menu.dim_color`, `.dim_opacity` | color, opacity | `"#2A1E26"`, 0.55 |
| `menu.button_width` | length | 288 |
| `quick_menu.text_size`, `.text_color` | size, color | 20 (20–24), `"#3D2B36"` |
| `quick_menu.fill_color`, `.fill_opacity`, `.corner_radius` | color, opacity, length | `"#FFF4F8"`, 0.90, 14 |
| `quick_menu.frame_image`, `.frame_slice_width` | image (nine-slice), length | none, 12 |
| `quick_menu.side_padding`, `.bottom_gap` | length | 12, 2 |
| `quick_menu.focused.text_color`, `.underline_width` | color, length | `"#A02860"`, 2 |
| `quick_menu.pressed.fill_color` | color | `"#FFD6E8"` |
| `quick_menu.on.fill_color`, `.border_color`, `.border_width` | color, color, length | `"#FFD6E8"`, `"#A02860"`, 2 |
| `quick_menu.disabled.text_color` | color | `"#6E5E68"` |
| `quick_menu.activate_sound` | sound | none |
| `confirm.dim_opacity`, `.width`, `.button_width` | opacity, length, length | 0.35, 640, 200 |

**Save / load and notices.** Ranges and purposes are in
[F11 03-ui](../specs/F11-save-load/03-ui.md), Theme tokens.

| Token | Type | Default |
|---|---|---|
| `save.text_size` | size | 24 (24–36) |
| `save.badge.fill_color`, `.fill_opacity`, `.text_color` | color, opacity, color | `"#FFF4F8"`, 0.90, `"#3D2B36"` |
| `save.newest.fill_color`, `.text_color` | color | `"#A02860"`, `"#FFFFFF"` |
| `save.placeholder.fill_color`, `.text_color` | color | `"#F0D0DE"`, `"#3D2B36"` |
| `save.no_picture_image` | image | none |
| `save.load_fade_ms` | duration | 300 |
| `notice.fill_color`, `.fill_opacity`, `.border_color` | color, opacity, color | `panel.fill_color`, `panel.fill_opacity`, `panel.border_color` |
| `notice.border_width`, `.corner_radius` | length | 2, 12 |
| `notice.frame_image`, `.frame_slice_width` | image (nine-slice), length | none, 24 |
| `notice.text_size`, `.text_color` | size, color | 24 (24–36), `panel.text_color` |
| `notice.marker.fill_color` | color | `button.marker.fill_color` |
| `notice.max_width` | length | 560 |
| `notice.duration_ms`, `.fade_ms` | duration | 1500, 200 |
| `notice.sound` | sound | none |
| `corner.fill_color`, `.border_color`, `.text_color` | color | `textbox.fill_color`, `textbox.border_color`, `textbox.text_color` |
| `corner.accent_color` | color | `textbox.indicator.fill_color` (bars and marks, like a meter's fill) |
| `corner.fill_opacity` | opacity | 0.90 |
| `corner.border_width`, `.corner_radius` | length | 2, 12 |
| `corner.text_size` | size | 24 (20–36), scaled by the player's text size |
| `corner.side_padding`, `.top_padding`, `.gap`, `.margin` | length | 12, 8, 8, 24 |
| `corner.fade_ms` | duration | 150 |

**Rollback (F14).** Set in `[theme.rollback]` (the mark in `[theme.rollback.mark]`);
layout and states are in [F14 03-ui](../specs/F14-rollback/03-ui.md). The mark's colors
default to the default theme's name-tab fill, box border, and indicator colors; they are
their own values and don't follow those tokens. The rewind tag reuses `quick_menu.*` and
has no tokens. The quick menu's Back entry is labeled `words.back`, "Back" (`[words] back`).
A missing or unusable `rollback.mark.image` falls back to the drawn mark with W64 (`…, so
the drawn limit mark is used.`); dev runs check the glyph on the fill as a graphic, 3:1
(W67, `marks need at least 3:1`).

| Token | Type | Default | Purpose |
|---|---|---|---|
| `rollback.mark.fill_color` | color | `"#FFE6F0"` | Limit mark pill fill, opaque. |
| `rollback.mark.border_color` | color | `"#F0A0C0"` | Pill border, `textbox.border_width` wide. |
| `rollback.mark.glyph_color` | color | `"#A02860"` | The bar and up-triangle (6.0:1 on the default fill). |
| `rollback.mark.image` | image | none | Replaces pill and glyph, drawn at its own size on the same center. |
| `rollback.bump_height` | length | 6 (0–12) | Say-window bump with the mark; 0: no bump. |
| `rollback.limit_sound` | sound | none | Played on the UI channel when the mark appears. |

**Minigame frame.** Purposes are in
[F23 03-ui](../specs/F23-minigame-api/03-ui.md), Theme tokens.
- The heading, hint panel, and Skip Game reuse `panel.*`, `button.*`, and `confirm.*`.
- The new words are `skip_minigame` "Skip Game" and `confirm_skip_minigame` "Skip this game
  and go on with the story?"
- Plugins may read any token and any `[words]` key, and they play the UI sounds.

| Token | Type | Default |
|---|---|---|
| `minigame.fade_ms` | duration | 300 (0–1000) |
| `minigame.background_image` | image | none |
| `minigame.fill_top_color`, `.fill_bottom_color` | color | `title.fill_top_color`, `title.fill_bottom_color` |
| `minigame.stage_dim_opacity` | opacity | 0.30 (0.0–0.8), in `menu.dim_color` |
| `minigame.hint.text_size` | size | 24 (24–36) |

**Poem game (F24).** The bundled `poem_game` minigame's own tokens, set in
`[theme.plugin.poem_game.page]`, `[theme.plugin.poem_game.word]`, and
`[theme.plugin.poem_game.counter]`; layout and states are in
[F24 01-design](../specs/F24-poem-builder/01-design.md) §6 and the guide is
[minigames.md](minigames.md), "Poem game". The words reuse F10's row look: no fill at rest,
`button.focused.*` and `button.pressed.*` with the marker otherwise. A size or width outside
its range is clamped when the poem starts, with no warning (plugin tokens declare no range).

| Token | Type | Default | Purpose |
|---|---|---|---|
| `plugin.poem_game.page.paper_image` | image | none | Stretched over the page instead of the fill, margin, and rules. |
| `plugin.poem_game.page.fill_color` | color | `"#FFFDF6"` | The page, opaque. |
| `plugin.poem_game.page.rule_color` | color | `"#C9D8EE"` | The ruled lines, 1 unit wide. |
| `plugin.poem_game.page.margin_color` | color | `"#E8A0A0"` | The margin line, 2 units wide, 72 in from the page's left. |
| `plugin.poem_game.page.max_width` | length | 800 (560–1232) | The page's width, at most the content area's. |
| `plugin.poem_game.word.text_font` | font | `ui.text_font` | The words. |
| `plugin.poem_game.word.text_size` | size | 32 (24–48) | The words, then scaled by the player's text size; a long word steps down by 2 to 24, then ends in "…". |
| `plugin.poem_game.word.text_color` | color | `"#3A2E39"` | A word at rest (a focused word uses `list`'s focused text color). |
| `plugin.poem_game.counter.text_size` | size | 28 (24–40) | The `3 / 20` counter at the page's top right, then scaled by the player's text size. |
| `plugin.poem_game.counter.text_color` | color | `plugin.poem_game.word.text_color` | The counter. |

Words (`[words.plugin.poem_game]`): `title` "Poem" (the save description), `hint` "Pick a
word for your poem." (the hint bar).

**Present evidence (F25).** The bundled `present_evidence` minigame's own tokens, set in
`[theme.plugin.present_evidence]` (the sounds) and its `.statement`, `.speaker`, and `.bar`
sub-tables; layout and states are in
[F25 01-design](../specs/F25-present-evidence/01-design.md) §6 and the guide is
[minigames.md](minigames.md), "Present evidence". The testimony box, the penalty panel, the
picker's backing panel, and the buttons reuse `panel.*` and `button.*`; the picker is F21's
Codex view with `codex.*`, `list.*`, and `panel.*`. The statement size is clamped when the
cross-examination starts, with no warning (plugin tokens declare no range).

| Token | Type | Default | Purpose |
|---|---|---|---|
| `plugin.present_evidence.statement.text_size` | size | 28 (24–40) | The statement, then scaled by the player's text size; a long one steps down by 2 to 24 within 3 lines, then ends in "…". |
| `plugin.present_evidence.statement.text_color` | color | `"#1E6B34"` | The statement (6.1:1 on `panel.fill_color`). |
| `plugin.present_evidence.speaker.text_color` | color | `panel.heading.text_color` | The speaker's name over the statement (`panel.heading`'s font and size). |
| `plugin.present_evidence.bar.fill_color` | color | `"#A02860"` | The penalty bar's filled part (5.0:1 on the track). |
| `plugin.present_evidence.bar.track_color` | color | `"#F0D0DE"` | The bar's empty part, and the 2-unit notch between units when `penalty_max` is 10 or less. |
| `plugin.present_evidence.bar.loss_color` | color | `"#C62828"` | The diagonal hatching over what a wrong item takes, for 500 ms (4.0:1 on the track). |
| `plugin.present_evidence.press_sound` | sound | none | Played on Press, besides `button.activate_sound`. |
| `plugin.present_evidence.present_sound` | sound | none | Played when an item is presented, right or wrong. |

Words (`[words.plugin.present_evidence]`): `title` "Cross-Examination" (the save
description), `hint`, `hint_no_press`, `hint_picker` (with `{statement}`), `previous`,
`next`, `press`, `present`, `back`, and `bar_label` "Credibility"; their defaults are in
[minigames.md](minigames.md).

**Phone chat (F26).** The bundled `phone_chat` minigame's own tokens, set in the
`.phone`, `.bar`, `.header`, `.message`, `.them`, `.me`, `.name`, `.note`, and `.typing`
sub-tables of `[theme.plugin.phone_chat]`; layout and states are in
[F26 01-design](../specs/F26-phone-messages/01-design.md) §6 and the guide is
[minigames.md](minigames.md), "Phone chat". The reply buttons reuse `button.*` (F10's
states, focus, and marker) and the ignore row is italic. A size or width outside its range is
clamped when the chat starts, with no warning (plugin tokens declare no range). Contrast on
the defaults: them 12.7:1, me 7.1:1, the bar 12.9:1, names 6.5:1, dividers 5.5:1, dots 4.9:1.

| Token | Type | Default | Purpose |
|---|---|---|---|
| `plugin.phone_chat.phone.body_color` | color | `"#1E1E24"` | The phone's body, radius 40. |
| `plugin.phone_chat.phone.screen_color` | color | `"#F7F4F6"` | The screen, inset 12 in the body, radius 28, opaque. |
| `plugin.phone_chat.phone.body_width` | length | 420 (360–600) | The body's width at 100% text; 8 wider per unit the message size grows past 24 (516 at 150%). |
| `plugin.phone_chat.bar.fill_color` | color | `"#FFFFFF"` | The status bar at the top of the screen. |
| `plugin.phone_chat.bar.text_color` | color | `"#3A2E39"` | The clock in the bar (`ui.text_font`, 24, scaled) and the contact's name in the header. |
| `plugin.phone_chat.bar.line_color` | color | `"#E3D9DF"` | The 1-unit line under the header. |
| `plugin.phone_chat.header.text_font` | font | `ui.text_font` | The contact's name. |
| `plugin.phone_chat.header.text_size` | size | 28 (24–40) | The contact's name, then scaled by the player's text size; a long name ends in "…". |
| `plugin.phone_chat.message.text_font` | font | `ui.text_font` | The messages; W176 names a character it can't draw (dev). |
| `plugin.phone_chat.message.text_size` | size | 24 (24–36) | The messages, then scaled by the player's text size. |
| `plugin.phone_chat.them.fill_color` | color | `"#ECE6EA"` | The contact's bubbles (left) and the typing indicator. |
| `plugin.phone_chat.them.text_color` | color | `"#2A2128"` | Text in the contact's bubbles. |
| `plugin.phone_chat.me.fill_color` | color | `"#A02860"` | The player's bubbles (right). |
| `plugin.phone_chat.me.text_color` | color | `"#FFFFFF"` | Text in the player's bubbles. |
| `plugin.phone_chat.name.text_color` | color | `"#A02860"` | A sender's name above their messages in a group chat (24, scaled). |
| `plugin.phone_chat.note.text_color` | color | `"#6E5E68"` | The time dividers (24, scaled) and the message field's outline and word. |
| `plugin.phone_chat.typing.dot_color` | color | `"#6E5E68"` | The three typing dots. |

Words (`[words.plugin.phone_chat]`): `title` "Phone" (the save description), `ignore`
"Don't reply", `close` "Put the phone away", and `placeholder` "Message" (the message
field); an ask's own ignore label wins over `ignore`.

**Puzzle room (F27).** The bundled `puzzle_room` minigame's own tokens, set in the `.spot`
sub-table of `[theme.plugin.puzzle_room]`; layout and states are in
[F27 01-design](../specs/F27-puzzle-room/01-design.md) §6 and the guide is
[minigames.md](minigames.md), "Puzzle room". Hotspots are invisible but for their `image`;
the focused or hovered one (at most one) gets the ring and a name tag on `panel.*`. The
Items, Put away, and Back buttons reuse `button.*`, and the item picker is F21's codex view.
The ring is two lines, so it shows at 3:1 or better on any picture: the white outer line
against dark art, the near-black inner line against light art.

| Token | Type | Default | Purpose |
|---|---|---|---|
| `plugin.puzzle_room.spot.ring_color` | color | `"#FFFFFF"` | The focus ring: a 3-unit line just outside the hotspot's rect (grown by 4). |
| `plugin.puzzle_room.spot.ring_shadow_color` | color | `"#1A1A1A"` | The 2-unit line inside the ring, so it shows on light pictures too. |

Words (`[words.plugin.puzzle_room]`): `title` "Puzzle Room" (the save description), the
hints `hint`, `hint_using`, `hint_using_only`, `hint_picker`, and `hint_combine` (`{item}` is
the selected item's title), the buttons `items`, `back`, `use`, `combine`, and `put_away`
("Put away {item}"), and the captions `need_item`, `no_use`, and `no_combine`; their
defaults are in [minigames.md](minigames.md).

**Quick minigames (F53).** `code_lock`, `stay_still`, and `hand_game` draw every color from
engine tokens (`panel.*`, `button.*`, `slider.*`), so all six color schemes apply; their own
tokens are sizes, sounds, and pictures only. Layout and states are in
[F53 01-design](../specs/F53-quick-minigames/01-design.md) §4; the words are in
[minigames.md](minigames.md). Sizes are scaled by the player's text size and clamped
silently; a missing picture shows the hand's word.

| Token | Type | Default | Purpose |
|---|---|---|---|
| `plugin.code_lock.display.text_size` | size | 48 (32–64) | The keypad's display. |
| `plugin.code_lock.turn_sound`, `.wrong_sound`, `.open_sound` | sound | none | A dial turn, a wrong code, the lock opening. |
| `plugin.stay_still.line.text_size` | size | 32 (24–40) | The line; steps down by 2 (not below 24) to fit 3 lines, then "…". |
| `plugin.stay_still.flinch_sound` | sound | none | Each flinch. |
| `plugin.hand_game.hand.text_size` | size | 48 (32–64) | A hand's word on its card. |
| `plugin.hand_game.hand.rock_image`, `.paper_image`, `.scissors_image` | image | none | Replaces the hand's word, shrunk (never stretched) to fit the card. |
| `plugin.hand_game.reveal_sound` | sound | none | Both hands show. |

**Gift giving (F54).** `gift_giving` is F21's codex view as F25's picker (Give as the pick
word, Not now beside it) and a reaction card on `panel.*` with a `button.*` Continue; no
color of its own, so every scheme applies. Layout and words are in
[F54 SPEC](../specs/F54-gift-giving/SPEC.md) §4.1 and [minigames.md](minigames.md).

| Token | Type | Default | Purpose |
|---|---|---|---|
| `plugin.gift_giving.line.text_size` | size | 28 (24–40) | The card's line, scaled by the player's text size; up to 3 lines, then "…". |
| `plugin.gift_giving.give_sound` | sound | none | Give. |

**Flowchart (F20).** Set in `[theme.flowchart]` (sub-tables `[theme.flowchart.node]`, `.edge`,
and the rest). Purposes, shapes, and words are in
[F20 03-ui](../specs/F20-flowchart/03-ui.md), Theme tokens. The detail panel, Jump,
toolbar, scrollbars, and tags reuse `panel.*`, `button.*`, `list.*`, `save.badge.*`, and
`confirm.*`.

| Token | Type | Default |
|---|---|---|
| `flowchart.fill_color` | color | `"#FFFAFC"` (opaque viewport fill and edge-label backing) |
| `flowchart.text_size` | size | 24 (24–36) |
| `flowchart.node.width` | length | 240 (200–360), layout units |
| `flowchart.node.fill_color`, `.border_color`, `.text_color` | color | `"#FFE6F0"`, `"#7E5C74"`, `panel.text_color` |
| `flowchart.start.frame_image`, `.chapter.`, `.choice.`, `.scene.`, `.ending.`, `.gate.frame_image` | image (nine-slice) | none (visited nodes only) |
| `flowchart.gate.fill_color` | color | `flowchart.fill_color` |
| `flowchart.unknown.text_color` | color | `button.disabled.text_color` |
| `flowchart.edge.line_color`, `.line_width` | color, length | `"#7E5C74"`, 3 (2–6) |
| `flowchart.path.line_color`, `.line_width` | color, length | `button.marker.fill_color`, 6 (4–10) |
| `flowchart.here.fill_color`, `.text_color` | color | `save.newest.fill_color`, `save.newest.text_color` |

An unset color follows the token named as its default, the author's value of it included.
The words (`[words]`) are `flowchart` "Flowchart", `flowchart_jump` "Jump",
`flowchart_start` "Start", `flowchart_chapter` "Chapter", `flowchart_choice` "Choice",
`flowchart_scene` "Scene", `flowchart_ending` "Ending", `flowchart_route` "Locked route",
`flowchart_unknown` "???", `flowchart_var` "…" (a `{var}` in a choice or question),
`flowchart_here` "You are here", `flowchart_changed` "This part of the story has changed.",
`flowchart_no_state` "Reach this point again to jump here.", `flowchart_no_jump` "You can't
jump to this point.", `flowchart_confirm` "Jump to this point? Unsaved progress will be
lost.", `flowchart_confirm_autosave` "Jump to this point?", `flowchart_endings` "Endings",
and `flowchart_nodes` "Nodes". W67 checks the `flowchart.*` text and line pairs against
their fills.

**Codex (F21).** Set in `[theme.codex]` (sub-tables `[theme.codex.new]`,
`[theme.codex.locked]`); layout, states, and words are in
[F21 01-design](../specs/F21-codex/01-design.md) §6. The tab row is the shared page row; the
list, the detail panel, and the pick button reuse `button.*`, `list.*`, and `panel.*`. An
unset color follows the token named as its default, the author's value of it included.

| Token | Type | Default | Purpose |
|---|---|---|---|
| `codex.new.fill_color` | color | `button.marker.fill_color` (`"#A02860"`) | The unread dot: a 10×10 circle 24 left of the row's right edge (6.59:1 on `#FFF4F8`). |
| `codex.locked.text_color` | color | `button.disabled.text_color` (`"#6E5E68"`) | A locked tip's `???` row under `[codex] show_locked` (5.64:1 on `#FFF4F8`). |
| `codex.image_height` | length | 200 (0–320) | The picture box's height in the detail panel; 0 hides pictures. The box shrinks to fit the panel and is left out under 80. |

**Extras and the gallery (F34).** Extras is the title's game-menu screen with the `extras`
menu in its sidebar (Gallery first; F35–F37 add pages); its button shows on the title once
one of its pages has something unlocked. The Gallery page is 4 × 3 tiles of 188×138 (a
16:9 picture box, the title under it), F11's page row past 12; a locked tile is
`panel.fill_color` with `gallery_locked` in `button.disabled.text_color` (5.64:1 on
`#FFF4F8`). Tiles reuse `button.border_*`, `button.focused.border_*`, and `panel.*`. The
viewer fills the canvas and fits the picture; pictures crossfade over 200 ms (cuts under
reduced motion). Layout, input, and words are in
[F34 01-design](../specs/F34-cg-gallery/01-design.md) §6.
**Endings and Scenes (F36)** add no tokens. The Endings page (`endings`, under `[endings]
list`) is a count line ("`endings_count`: 2 / 5") in `panel.text_*` over an F10
`ScrollList` at (416, 164), 808×500: a reached ending's heading in
`panel.heading.text_color` and its title in `button.text_*`, with `ending_replay`
right-aligned in `button.marker.fill_color` (6.59:1 on `#FFF4F8`) while `[endings] replay`
is on; an unreached one is `ending_locked` in `button.disabled.text_color` (5.64:1) and
never takes focus. The Scenes page (`replays`) is the Gallery's tile grid, captioned with
each replay's title, `???` while locked, with no viewer. A replay starts with New Game's
fade and ends with the story-end fade back to Extras, its row or tile focused (cuts under
reduced motion). During a replay the game menu's Main Menu reads `replay_end` ("End
Replay") and leaves at once, with no question; Save, Load, and Flowchart are hidden (and
the quick menu's Save, Q.Save, Q.Load), and saving and loading are blocked with
`replay_no_saving`; nothing the player keeps changes, except music-room tracks and
achievements earned in it. Layout and rules are in
[F36 01-design](../specs/F36-ending-list/01-design.md) §6.
The gallery is set in `[theme.gallery]`
(sub-tables `[theme.gallery.caption]`, `[theme.gallery.viewer]`):

| Token | Type | Default | Purpose |
|---|---|---|---|
| `gallery.caption.text_size` | size | 20 (14–32) | A tile's title under its picture, cut with "…" to the tile's width. |
| `gallery.viewer.fill_color` | color | `"#000000"` | The viewer's fill around a picture that doesn't cover the canvas. |

## 4. Fixed engine colors

These are not themeable. They must render when a theme or the game's fonts are broken,
and look the same in every game so authors recognize them. All text here uses the
bundled Noto Sans (ADR-0004).

| Where | Colors and sizes | Source |
|---|---|---|
| Missing-image placeholder | Checkerboard of 32-unit squares `#FF00FF` / `#000000` (magenta at top-left); full-width `#000000` label band, `#FFFFFF` label at 20 units, 8 units padding, ≤ 6 lines. Image placeholder 256×256; sprite placeholder 320×576. | F01 §7.11.8; F04 UI-F04-09 to 11 |
| Missing background | `#202020` canvas fill, 256×256 placeholder centered | F04 UI-F04-09 |
| Placeholder screen | Fill `#202020`; title 48 units `#E0E0E0`; engine version 20 units `#A0A0A0` at bottom-right (1264, 704) | F01 SPEC §6.8.15 |
| Error screen | Fill `#141414`; heading 40 units `#FFFFFF`; message 28 units `#F0F0F0`; details 28 units `#C8C8C8`; key hint 28 units `#FFFFFF` | F01 SPEC §6.8.14 |
| Fake crash screen | The error screen's look (shared constants); details line `"<title>" version <version>`; hint at y 640; optional label 28 units `#C8C8C8` at (80, 680); no log line | F30 UI-F30-01 |
| Fade black | `#000000` for the launch canvas, title fades, story end, and the load fade (F11) | F10 03-ui, Motion |
| Dev sampler backdrop | `#FFFFFF`, or `#000000` when toggled | F10 03-ui |

`#202020` means "nothing real here yet" everywhere in the engine. The empty stage is
`#000000` (a token), so "missing" and "empty" never look alike. The title never shows
`#202020` or the checkerboard: with no art it draws its themed gradient. A save with no
usable thumbnail shows F11's themed placeholder, never the checkerboard.

## 5. Standard timings

| Name | Value | Used by |
|---|---|---|
| Instant cut | 0 ms, no intermediate frame | Every stage change with no `with` or with `with cut` (F04, F09); F05 box appear, page change, hide/show; F10 focus, page change, quick menu; F11 save-page change |
| Resize settle | 200 ms after the last size change; art may be softer, never moved | F01, all drawing |
| Status message | 2,000 ms | F01 error screen "Copied" |
| Indicator bob | 1,200 ms loop, 4 units down and back, `ease_in_out` | F05 continue indicators; F17 reuses |
| Screen fade | `ui.fade_ms` 150, `linear`, in and out | Every menu-type screen and page |
| Title fade-in | `title.fade_in_ms` 500 from black, `linear` | Title at launch and on every return |
| Story-end fade | 1,000 ms to black, `linear` | PR-F10-25 |
| Key activation | 100 ms pressed look | Widgets that stay on screen |
| Hold to repeat | First repeat after 500 ms, then every 80 ms | Lists, grids, sliders (never buttons, toggles); F11 page keys; F20 chart moves |
| Loading delay | 1,000 ms before "Loading" shows; dots loop 900 ms | Launch; a restore over 1,000 ms (F11) |
| Load fade | `save.load_fade_ms` 300 from black, `linear` | Every load; F20 jumps |
| Notice shown | min(8,000, `notice.duration_ms` 1,500 + 50 per character over 20) | Every notice ("Quick saved." 1,500) |
| Notice fade | `notice.fade_ms` 200: in `ease_in_out` with a 24-unit slide, out `linear`, restack `ease_in_out` | Every notice |
| Limit cue | Mark: cut in, 400 ms hold (restarted by each repeat), 100 ms `linear` fade; bump 80 ms up + 120 ms back, `ease_in_out` | Rollback at its limit; F20's chart limit bar (no bump) |
| Minigame dissolve | `minigame.fade_ms` 300, `linear`, a cross-dissolve (not through black), in and out. The plugin gets no time or input during it. A rollback-landing start is a cut; a load start uses only the load fade | Every minigame start and end |
| View pan (F20) | 200 ms, `ease_in_out`; a new target restarts it from where the view is; free-pan input stops it | A chart view keeping its selection in view |
| Double click (F20) | Second click within 400 ms, pointer moved ≤ 8 units, same item | F20 chart nodes (Jump) |
| Choice fade-in | `choice.fade_in_ms` 120, `linear`, from the frame the buttons appear; a pick is an instant cut | F07 every menu |
| Choice guard | 250 ms after the buttons appear, picks are ignored (focus still moves) | F07 every menu |
| Choice countdown (F51) | `menu time N`: N s (Timing assist Slower 2N s, No time limits none), counted only while the menu is on top, drawn, not hidden and the window has focus; the bar shrinks every frame, the number shows whole seconds rounded up; at 0 the timeout choice is picked (an instant cut). A Timing assist change keeps the fraction of time left. Reduced motion: the bar moves once per whole second, with the number; never a pulse, shake or flash | F51 timed menus |
| Check roll (F59) | 1.3 s in all, counted only while it is on top and the window has focus: the dice change face every 75 ms and bounce (at most 14 units, shrinking) for 600 ms, then land on the roll and the sum and result appear (a cut). A press, skip, a restore or New Game ends it at once. Reduced motion: landed from the first frame, no bounce | F59 checks on choices |
| `cut` (proposed, F09) | New picture in the next frame; 0 ms | `with cut`, and any length 0 |
| `dissolve` (proposed, F09) | Per-pixel blend old → new, `linear`; 500 ms (`[effects] dissolve`) | `with dissolve`, `Dissolve(…)` defines |
| `fade` (proposed, F09) | Old → color (first half), color → new (second half), `linear` each half; 1,000 ms, `effects.fade_color` | `with fade`, `Fade(…)` defines; F18's chapter cards by default |
| `Mask` (proposed, F09) | Pixel shows new when its mask value < progress, with a `soft` ramp, `linear`; 1,000 ms | `Mask(…)` defines |
| `shake` (proposed, F09) | Whole picture offset in whole canvas units; sides alternate every 50 ms; amplitude falls linearly to 0; uncovered edges show `stage.empty_color`; 500 ms, 12 units | `shake` |
| `flash` (proposed, F09) | Color over the stage at full strength for one frame, then fades out, `linear`; 300 ms, `effects.flash_color` | `flash` |
| Reduced flash (proposed, F09) | Rises to 50% then falls, `ease_in_out`; 300 ms up + 300 ms down | `flash` under reduced motion |
| `tear` (F28) | 2–6 bands, 8–80 units tall, together ≤ 40% of the height, each sliding ±(¼ to 1) × the size and wrapping; new bands every 100 ms; size 16 / 40 / 96 units (small / medium / large) | `effect tear` |
| `colorshift` (F28) | Red copy left, blue copy right, green in place; still; 2 / 6 / 12 units | `effect colorshift` |
| `static` (F28) | Gray noise, 2-unit grain, 50% average brightness on every frame; a new frame every 100 ms; 15% / 30% / 50% strength | `effect static` |
| `jitter` (F28) | The sprite's picture at a random offset over the sprite in place; a new offset every 80 ms; up to 4 / 10 / 24 units | `effect jitter <tag>` |
| Glitch burst (F28) | Starts and stops abruptly; `[effects] glitch` 500 ms (0.1–30 s); size `[effects] glitch_size` `medium` | `effect <glitch>` with a length or none |
| `with glitch` (F28) | `tear large` rising on the old picture over the first half, a cut at p = 0.5, then falling on the new one; 500 ms (0–30 s) | `with glitch` |
| Reduced `static` (F28) | Always `small`; one still frame, `ease_in_out` 300 ms in and out | `static` under reduced motion |
| Reduced `colorshift` (F28) | As written; still, `ease_in_out` 300 ms in and out | `colorshift` under reduced motion |

### Easings

| Name | Curve (t from 0 to 1) |
|---|---|
| `linear` | t |
| `ease_in_out` | (1 − cos(πt)) / 2 (sine) |

Later features add names here. The stage's transition and effect timings (proposed, F09)
are in the table above; a click finishes any transition at once.

### Reduced motion and flashing

F16's Settings page has one "Reduce motion and flashing" toggle; the setting in force is
that toggle OR `[effects] reduce`, which turns it on for every player. Every effect that
moves the screen, shakes, or flashes declares in its `03-ui.md` exactly what the reduced version looks like (for
example, a shake becomes no shake; a flash becomes a fade of at least 300 ms). Nothing may
flash more than 3 times per second when the setting is on (WCAG 2.3.1). Instant cuts
caused by the player advancing are not flashes. **Skip (proposed, F15)** under the setting
leaves at least 333 ms after each stage change before it acts again (≤ 3 per second).
Looping idle motion (the F05 indicator
bob, F10's loading dots) stops at its rest look. F04 has no motion, so the setting does
not change it. **UI screens:** every UI fade becomes an instant cut with
no black frame between (the choice fade-in too, F07); color-only state changes (pressed, focus) stay. **Timed menus (F51):** the countdown bar moves once per whole second, with its number, and the panel appears without a fade, like the choices. **Notices and the
load fade** become cuts too: no slide, no restack movement. **Rollback:** landed steps
are cuts and never replay shakes or flashes; the limit cue drops its bump and its mark cuts
in and out. **Minigames:** both dissolves become cuts. Plugins are told the
setting, and bundled minigames drop shakes, flashes, and large motion. **Chart views
(F20):** the view pan becomes a cut; the limit bar cuts in and out; free panning
follows input as usual (the player is moving it). **Stage transitions and effects
(proposed, F09).** The flash limit is always on, with or without the setting: the stage
never shows more than 3 flashes in any 1-second period (PR-F09-14). Counted: every `flash`
as drawn (after reduction), and every fade-type transition under 1 s, once at its start (it
goes dark and back, one opposing pair under WCAG 2.3.1), red and colored ones alike. Not
counted: dissolve, Mask, wipes, cut, a transition the player clicks through, and fades of
1 s or more. An extra flash isn't drawn and an extra fade plays as a dissolve of the same
length; the story is unchanged and W61 is logged. Under the setting (`[effects] reduce`
OR the player's, PR-F09-15): shake draws no movement; a flash rises to at most 50% and
falls, `ease_in_out`, at least 300 ms each way, at most one per second; moving and
non-calm transitions draw as a dissolve of the same length; `cut`, `dissolve`, `fade`, and
`Mask` are unchanged. The story is unchanged. **Glitch effects (F28).** Never a flash, with or without the setting: no glitch fills the stage with a color, red never flashes on its own, patterns change at most 10 times a second (12 for one sprite's jitter), and glitches change the stage's average brightness only when they start or stop. A burst shorter than 1 s (not jitter), every `with glitch` shorter than 1 s, and each start, resize, or end of a lasting static or colorshift count as one flash at their start in the same 3-per-second limit; glitches starting together count once. A refused burst isn't drawn and a refused `with glitch` plays as a dissolve; the story is unchanged and W182 is logged once per line. Under the setting: tear and jitter draw nothing; static is one still noise frame at the `small` strength, fading in and out over 300 ms; color shift stays as written but fades in and out over 300 ms; `with glitch` plays as a dissolve. Switching the setting mid-glitch changes the look the next frame. The story is unchanged.

## 6. Input

Global keys, handled by the engine before any screen (architecture, "Screen stack"):

| Key | Action |
|---|---|
| F11, Alt+Enter, Alt+keypad Enter, macOS Ctrl+Cmd+F | Toggle fullscreen |
| F3 | Dev overlay (dev runs only): frame rate and work time, then the story's meters (F22) |
| F12 | Reserved for F40 (console) |

No global key is a bare letter. **Esc is not global (F10 product Q4):**
each screen handles it as "back" (§9). Gamepad Start is reserved for F10 (game menu).
Clicks inside the letterbox bars are ignored by every feature. The stage (F04) takes no
input. Screen-level dev keys: Shift+F3 sampler (F10), Shift+F8 end minigame
(F23). Both are Shift only and do nothing in release runs.

### In-game reading keys

Handled by the in-game screen, not globally. Each acts on press, once per press; held
keys and OS key repeat never repeat it. Gamepad buttons are named by position (south =
A / Cross, east = B / Circle, north = Y / Triangle, west = X / Square).

| Input | Action | Owner |
|---|---|---|
| Left click in canvas, Space, Enter, keypad Enter, gamepad south | Advance (complete the line first) | F05 |
| H, middle click, gamepad north | Hide / show the say window and quick menu | F05 |
| Right click, Esc, gamepad east, gamepad Start | Open the game menu | F10 |
| F5 / F9 | Quick-save / quick-load | F11 |
| Wheel up (each notch), Page Up, gamepad left shoulder | Roll back one step; the wheel works anywhere in the window, and precise scrolling adds up to whole notches | F14 |
| Wheel down, Page Down, gamepad right shoulder | Roll forward one step | F14 |
| Ctrl (held, no other modifier) | Skip while held (proposed, F15) | F15 |
| Tab, no Ctrl/Alt/Meta | Skip on / off (proposed, F15) | F15 |
| A, no Ctrl/Alt/Meta | Auto on / off (proposed, F15) | F15 |

Quick-menu buttons are mouse targets only; they are never in the keyboard or gamepad
focus order, and every one has a key or menu path (PR-F10-34).

### In a minigame

These replace the reading keys while a minigame runs and nothing covers it.

| Input | Action |
|---|---|
| Esc, gamepad Start | Open the game menu; never delivered to the plugin |
| Right click, gamepad east, Backspace | The plugin's Back first. If unused, right click and east open the game menu |
| F5, F9, fullscreen keys, F3 | As everywhere |
| Wheel, Page Up / Down, shoulders | The plugin first (scroll, page). If unused: back closes the minigame before any used input, and shows the limit cue after; forward does nothing |
| Shift+F8 (dev) | End with the test outcome; never delivered to the plugin |
| Everything else (advance keys, arrows, Tab, letters, middle click, north, west) | Delivered to the plugin. Hide, skip, and auto don't act |
| Anything during a dissolve | Dropped. Esc, Start, F5, F9, and Shift+F8 snap the dissolve to its end, then act |

### Menu navigation

In every F10-based screen. Acts on press, once; the press that opens a screen never acts
inside it.

| Input | Action |
|---|---|
| Arrows, D-pad, left stick (past half, one step per push) | Move focus to the nearest widget that way (§9); Up/Down wrap in a single column |
| Tab / Shift+Tab | Next / previous widget in reading order, wrapping |
| Enter, keypad Enter, Space, gamepad south | Activate; with nothing focused, focus the default widget |
| Esc, right click, gamepad east | Back (inside a minigame: Backspace, right click, east) |
| Gamepad Start | Close the game menu when it is the top screen |
| Mouse wheel | Scroll the list or grid under the pointer only |
| Home / End | First / last row or cell; slider minimum / maximum |
| Page Up / Page Down | One page (lists, grids); on F11's pages also left / right bumper |
| Delete, Backspace, gamepad west | Delete the focused item where a page allows it; Backspace is Back inside a minigame |

**In a chart view (F20)** these differ (full table in F20 03-ui, Interaction):
arrows never wrap; Left with nothing that way goes to the sidebar and other directions
show the limit bar. The wheel pans (Shift+wheel horizontally), and Ctrl+wheel zooms. A
left drag pans. `+` / `-` and gamepad north zoom. Gamepad right stick pans freely.
End and gamepad west go to "You are here". Page Up / Down and the shoulders scroll the
detail panel.

## 7. Text

Rules for game text (say window, NVL, history, choices); a feature lists only what
differs.

- **Font faces.** Regular, bold, italic, and bold italic come from tokens. A missing face
  is synthesized from the regular face in use (heavier strokes; about 12° slant), never
  borrowed from a different family. Line breaks use the widths of the face as drawn.
- **Line pitch** is round(1.4 × size), using the largest size on the line; glyphs are
  vertically centered in the pitch band and share one baseline. Left-aligned, top-first.
- **Wrapping and pages** follow PR-F05-14 and 15. Decorations (indicators) sit in padding
  and never change a line break.
- **Typing look.** A character appears whole and fully opaque, in one frame, at its final
  position (no fade-in).
- **Contrast over art.** Text over art always has a backing panel. Body text needs 4.5:1
  against the panel composited over both pure black and pure white; names (≥ 24 units)
  and graphics need 3:1. Default textbox ratios: text 7.6:1, name 6.0:1, indicator 4.1:1.
  Tag colors that pass on the default box: red `#9A1C14` (4.8:1), blue `#1E4A9C` (4.9:1).
  Default full-screen text (F17) ratios on the panel over black / white: text 8.6:1 /
  12.4:1, name and indicator 4.6:1 / 6.6:1. In a story that uses `nvl on`, dev runs warn
  when a `[theme.nvl]` color or a `Character`'s `color` doesn't pass on the panel (F17
  W100).
  Dev runs warn when a `Character`'s `color` or `text_color` doesn't pass (F05 W41) and
  when the `[theme.textbox]` text and fill don't (F05 W44). Ratios print rounded down to
  one decimal, so a failing 4.47 shows as 4.4.
  **Over pictures inside UI** (save thumbnails, later gallery images), text sits on a tag
  (§9) with its own backing.
- **Continue indicators** are drawn shapes, not font glyphs: line or click-wait = one
  down-pointing triangle 16×12; page break = two stacked 16×10 triangles, 2 apart. Each
  sits 8 units after the last shown character, tip on the baseline, and bobs (§5).
- **Text size scaling.** The player's text-size setting (F16) scales body and name sizes;
  panels grow up to their limit, then text pages. Every layout is checked at 150%.
- **UI text.** Menu text uses `ui.text_font` (default the textbox font),
  is at least 24 units (quick menu 20–24), and scales with F16's setting; the quick menu
  stops at 24. A label too wide for its widget steps down by 2 units, not below 24, then
  ends in "…". Button and panel text meet 4.5:1 over black and white; dev runs warn when
  an author theme doesn't (W67).
- **Zoomed views (F20).** A view that zooms out never draws text below 24 units.
  It drops text instead (F20's Overview keeps only the "You are here" tab at full size).

## 8. Tools (proposed, F44)

Dev-only tool windows, such as the F44 scene editor, are native OS windows built from
standard widgets. The canvas, layers, theme tokens, fixed engine colors, timings, and
gamepad rules in this file don't apply to them. They use pixel sizes at 100% OS scaling,
fixed light colors with at least 4.5:1 contrast, and the OS UI font. F6 / Shift+F6 moves
focus between a tool's areas. Each tool's `03-ui.md` is the full reference.

## 9. Widgets, focus, and back

Every in-game menu, page, and minigame UI builds on these. Full looks, sizes, and states
are in [F10 03-ui](../specs/F10-ui-framework/03-ui.md).

| Widget | Look (default theme) |
|---|---|
| Button | Rounded panel, `#FFF4F8` at 0.90, 2-unit `#F0A0C0` border, centered plum label; height max(56, pitch + 16) |
| On/off button | Button plus a pip: filled = on, ring = off |
| Toggle | Row: label left, 56×28 track right with the word On/Off; on = filled accent track, knob right |
| Slider | Row: label above a bar; filled part 8 tall, rest 4 tall, 16×28 thumb, integer value at right |
| Scroll list | Rows ≥ 48 tall with dividers; 8-wide scrollbar only when rows overflow |
| Grid | Cells drawn as buttons; size per feature |
| Panel | `#FFF4F8` at 0.94, 2-unit border, radius 16; headings 32 units accent |
| Page row | A centered row of buttons H_b tall, 4 apart, each max(H_b, label + 32) wide, no focus marker; current page selected; ◀ ▶ appear only when not all fit |
| Tag | Small pill over a picture: height text size + 10, width text + 16, radius 8, own backing (`save.badge.*`); never focusable. F20 also uses it for edge labels, the "You are here" tab, and counts |
| Notice | Non-modal toast, below |
| Minigame heading, hint bar | Panels from §1 "Minigame screen regions"; never focusable; text changes are cuts |
| Codex view (F21) | F21's list and detail panel, optionally with a pick button; a minigame hosts it in its content area (≥ 640×400) |
| Chart view (F20) | A pannable, zoomable map in a clipped viewport: cells joined by routed edges, with F10 scrollbars on both axes when they overflow. Draws only what meets the viewport. Mouse-only glyph toolbar. Full spec in F20 03-ui |

**Standard states.** Normal; **focused** = focused fill `#FFD6E8`, 4-unit `#A02860`
border, and a 12×16 triangle marker 12 inside the left edge (the same for every widget,
and the same for hover and keys); **pressed** = fill `#FFC2DC`; **disabled** = no border
and muted `#6E5E68` text, knob or thumb hidden, never focused; **on** = pip, knob, or chip;
**selected** = a 6-unit accent bar at the left. Row widgets have no fill until focused.
Grid cells and page-row buttons may drop the marker; the 4-unit border carries focus. No
state is shown by color alone.

**Chart view focus (F20).** The one exception to "hover = focus".
- In a chart view the selection is the focus, and hover only tints a cell's fill. The panel
  driven by the selection then doesn't change while the pointer crosses cells.
- A click selects.
- The focused cell shows a 4-unit ring 6 outside the cell, plus F10's marker 8 to the left
  of the ring. A selected cell without focus shows a 2-unit ring.
- When the selection moves, the view pans so the selected cell stays inside a safe zone
  (§5 "View pan").

**Focus.** One focus per screen, shared by mouse and keys; the last input wins. A mouse
focus clears when the pointer leaves; a key focus stays. A screen opened by key or button
focuses its default widget at once (first widget; "No" in a confirm); one opened by mouse
shows none until the first navigation input. **Directional move:** among widgets whose
center lies beyond the current one that way, pick the smallest (distance along the
direction + 2 × sideways distance), ties in reading order. Focus moved out of view in a
list or grid scrolls it just into view.

**Back** (Esc, right click, gamepad east) closes the top screen or open page and returns
focus to the widget that opened it. On a confirm it means No; on the game menu's first
level it returns to the game; on the title it does nothing. Back never quits, starts, or
loads a game. **In a minigame** Esc always opens the game menu. Back for
the plugin is Backspace, right click, or east, and when unused it opens the game menu.

**Confirm dialogs.** Every yes/no question uses F10's dialog: message, Yes left, No right,
No focused first, clicks outside ignored, never timed out.

### Notice

The one non-modal message component, owned by the shell (F11 adds it; F12's W50–W52
notices, SEC-F12-12, and F37's achievements reuse it). Full layout in
[F11 03-ui](../specs/F11-save-load/03-ui.md), "Notice".

- **Kinds.** *Info* (plain) and *problem* (a 6-unit accent bar at the left, plus words that
  say what went wrong). The words always carry the meaning. F37 may add an icon at the left
  through its review.
- **Look.** A panel (`notice.*`, defaults follow `panel.*`), text 24 units (scales with
  F16, to 36), padding 20 × 12, radius 12, 160 to 560 wide, at most 4 lines, then "…".
  Text 10.7:1 over black, 12.3:1 over white.
- **Position.** First notice `topright` at (1256, 24); each next one 8 below the one above.
  No notice ends below y 400, so the textbox (≥ 472), name tab (≥ 410), quick menu, and
  F15's top-left indicators are never covered. On the title it stays clear of the logo box
  (x ≤ 640) at the default width.
- **Stacking.** At most 3 shown, oldest at the top. More wait in order (up to 10; past
  that the oldest waiting is dropped, as the log already has it), and a waiting notice
  shows when one leaves and it fits above y 400. A notice whose text matches one shown or
  waiting restarts that one's time instead of adding another (F5 held makes one "Quick
  saved.").
- **Timing.** Shown time is §5 "Notice shown", starting when the fade-in ends. It pauses
  while the pointer is over the notice and while the window is unfocused or minimized, and
  runs under menus. Notices raised during a fade to black, a load, or before the title has
  faded in wait until a title, game, or menu screen shows.
- **Input.** Never focused, never consumes a click, key, or wheel; hover only pauses it.
- **Never captured.** Not in `scene_picture()`, save thumbnails, or menu backdrops.
- **Reduced motion.** Appear, leave, and restack in one frame.

### Text field and on-screen keyboard (F52)

Full spec: [F52 01-design](../specs/F52-text-entry/01-design.md) §6.

- **Text field.** A one-line field with a caret, in a button-sized box (height
  max(56, pitch + 16)); F10's focused look. Variants: a **letter cell** (square, side
  max(40, pitch + 8), underlined, Up/Down turn the letter) and a **bare** field (no box; F56's
  prompt line). The caret blinks 500 ms on / 500 ms off and is steady under reduce motion.
  Notes ("That character can't be used here.") show as a tag 8 below for 2,000 ms.
- **Typing.** SDL text input is on only while a field is focused on the top screen; IME
  composition shows underlined at the caret and owns Enter, Esc, Backspace, arrows and Tab
  until committed. Backspace in a focused field never acts as Back (the one exception to
  "Back for the plugin is Backspace" above; Esc still opens the game menu, the text kept).
- **Focus.** A screen or minigame whose default widget is a text field focuses it visibly
  whatever input opened it (the one exception to the mouse-open rule under "Focus" above).
- **On-screen keyboard** (gamepad south on a field, or its keyboard icon by mouse): a modal
  panel owned by the screen or minigame host, `midbottom` (640, 696), 1040 wide, 472 tall at
  100 % text and 504 at 150 %, with an echo row, a page row, a 10 × 4 key grid and
  ◀ ▶ / Space / Delete / Done. West deletes, north adds a space, the bumpers change page, east
  closes. Pages follow the game's language and what its fonts draw.
- **Tokens** (all following, so every color scheme applies): `text_entry.fill_color`,
  `.fill_opacity`, `.border_color`, `.text_color`, `.text_size` (the `button.*` ones),
  `text_entry.placeholder_color` (`button.disabled.text_color`), `text_entry.caret_color`
  (`button.marker.fill_color`). The keyboard uses `panel.*` and `button.*`.
- **As built** (F52 build notes): a boxed field's text starts 32 inside its left edge (F10's
  side padding), so the focus marker never covers the first letter; keys are
  (1008 − 9 × 8) / 10 = 93.6 wide. W67 checks the `text_entry.*` pairs once the author sets
  one of its colors (until then the `button.*` pairs check the same colors).

### Status corner (F61)

Full spec: specs/F61-status-corner/SPEC.md. Module: `engine/ui/statuscorner.py`.

- **What.** Small always-on readouts (meters first, F62; later a clock, a goal, a hotbar) in
  the four places of `engine.core.skins.CORNER_PLACES`. One shell-owned layer
  (`GameShell.corner`): `set_item(key, place, item)`, `remove_item(key)`, `clear()`. It owns
  no game state; whoever adds items saves what is shown.
- **Layout.** Each item is its own panel (`corner.*` fill, border, corners) around content it
  measures and draws itself, `side_padding` / `top_padding` inside. Items stack inward from
  their corner in insertion order, `gap` apart, `margin` from the canvas edge. A panel jumps
  past the say window with its name tab (ADV) or the NVL text column, the quick-menu pill, and
  the F15/F14 indicator row (reserved even when nothing shows there, so items never jump).
  A narrow item fits beside the box (in the 116 units left of a 1000-wide box); a wider one
  sits above it. Top stacks end by y 360; bottom stacks end below their side's top stack. An
  item that doesn't fit is not drawn, nor are the later ones in that corner. Notices may lie
  over the top-right stack for their few seconds.
- **Layer.** Drawn by `draw_layer` after the scene captures (never in a save thumbnail, scene
  picture, or menu backdrop), under layer 6 cues and notices.
- **Visible** only in game with an in-game screen on top, while the say window is drawn (so
  hidden in hidden mode and with the box, exactly as the quick menu), in ADV and NVL; hidden
  under the game menu and its pages, confirms, fades, the title, and an opaque in-game screen
  (a running minigame). Showing and hiding the whole layer is a cut.
- **Motion.** An item fades in and out over `corner.fade_ms` (linear); restacking is a cut.
  Under reduced motion (the player's setting or `[effects] reduce`) fades are cuts.
- **Contrast.** W67 checks `corner.text_color` (4.5:1) and `corner.accent_color` (3:1) on the
  fill at `corner.fill_opacity`, over black and white, once the author sets a corner color
  or the opacity; every built-in scheme meets both at the default 0.90.
- **Pulse (F62).** `pulse(key)` sends one ring out from an item's panel in
  `corner.accent_color` (3 units wide): over 0.4 s it moves from 3 to 13 units outside the
  panel, eased out, while it fades from full to nothing, on the corner's fade clock. A new
  rank change starts it again. None under reduced motion.

### Shown meters (F62)

Spec: specs/F62-visible-meters/SPEC.md "Round 2". Modules: `engine/ui/meteritem.py` (the
item), `engine/app/meters.py` (keeps the corner in line with the story's shown list),
`engine/render/meter_marks.py` (hearts, pips, arcs).

- **Rows.** First row: the label, then the gauge, centered in a row as tall as a text line
  or the gauge. A meter with ranks adds a row with its rank, kept (empty) below the first
  rank so the panel never jumps. In NVL (`nvl on`) the item takes a column as wide as the
  space beside the NVL text (132 units at the defaults): label, gauge, rank on their own
  rows, a bar or row of marks shrunk to fit.
- **Looks** (`s` = corner text size after the player's scale). `bar`: 6`s` × 0.7`s`, a
  `s`/12 outline and a fill inset by two outlines. `number`: the value (thousands
  separated). `hearts`: 0.9`s` marks, 1.05`s` apart; `pips`: 0.6`s` circles, 0.85`s` apart;
  one per point up to a range of 10, else 5–10 marks of equal worth, the one in progress
  partly filled from the left; empty marks are `s`/12 outlines. `dial`: a 2`s` circle, a
  270° arc from bottom left, a thin track and a thick fill, the value beside it. A meter
  with no range is drawn as a number.
- **Colors.** Text in `corner.text_color`; every mark, outline and fill in
  `corner.accent_color`. No separate track color: empty parts are accent outlines, so the
  corner's two W67 pairs cover meters in every scheme.
- **Motion.** Shown and hidden meters fade with the corner; values change at once; a rank
  change pulses the panel. After a load or New Game the meters reappear at once (a cut).

### Hotbar and the bag's Use button (F64 round 2)

Spec: specs/F64-items/SPEC.md "Round 2". Modules: `engine/ui/hotbaritem.py` (the item),
`engine/app/hotbar.py` (what the slots hold, the corner, input, and `ItemUser`, the one door
for every use), `engine/ui/builtin/codex_page.py` (`UseAction`).

- **Where.** A status-corner item (F61), so it never covers the say window, the NVL column,
  the quick menu or the indicator row, and hides with the corner (under menus, with the box
  hidden, in minigames). `[hotbar] place`, else bottom left: above the say window's left
  edge. 4–8 slots fit one panel in every corner (8 slots ≈ 590 units at 100% text).
- **Slots** (`s` = corner text size after the player's scale). One row, 0.75`s` apart; each
  a 2.2`s` square well with an `s`/12 accent outline, and under it a strip one small line
  tall (0.65`s`, at least 14): the number key at the left, a counted item's "×3" at the
  right. A held item's picture is fitted into the well (inset 4 outlines); without one, its
  title's first letters ("JT", "Ma") in the corner text color. An empty slot is the outline
  and its key.
- **Colors.** Text in `corner.text_color`, outlines in `corner.accent_color`, and no text
  over a picture, so the corner's two W67 pairs cover the hotbar in all 28 schemes
  (tests/ui/test_hotbaritem.py).
- **Input.** 1–8 and the keypad use slot n (no Ctrl, Alt, Meta; no key repeat). A left click
  on a slot uses it and never advances the line. Gamepad: X rings the first slot (outline
  doubled, plus an inner ring), D-pad left/right move (wrapping), A uses it, B or X leaves;
  while ringed, the slots take the pad. Keys work only while the hotbar is on screen.
- **Refusals.** An empty slot does nothing. An item that can't be used now (the line still
  typing or stopped at `{w}`, a menu, a minigame, a pause, another item's scene) shows the
  notice "Not now" (`[words] use_not_now`).
- **Motion.** The panel fades in and out with the corner (`corner.fade_ms`), a cut under
  Reduce motion and after a load or New Game; nothing else moves.
- **The bag's Use button.** On the game menu's Codex page, an item with a Use scene shows
  Use in the detail panel's bottom row (where a picker's pick button goes), enabled only
  while the item can be used now. When the item is on the hotbar the row's left half says
  where ("Belt: 1": `[hotbar] word`, else the kit's, else `[words] hotbar`) and the button
  takes the right half. Use closes the game menu and the item's scene starts at once. The
  button is a focus group of its own (keys and gamepad reach it from the list or the body).

### Inbox page (F65 round 1)

Plan: specs/skins-contract.md "Phases 2-4" and proposal I-09 "Chats you can reread".
Modules: `engine/core/codexkinds.py` (codex kinds), `engine/ui/builtin/kind_page.py`
(`KindPage`), `engine/app/inbox.py` (the port and the game-menu entry).

- **Codex kinds.** Every page of collected entries is the Codex view (§9 "Codex view") over
  the kinds registered for that page: tips and items on the Codex page, finished chats on
  the Inbox page. A kind's description gives its page, default tab word, row order
  (declared, obtained, newest first) and which fields it shows; later kinds (contacts,
  goals, thoughts, profiles) reuse the same list, unread dot, detail panel, keys and mouse.
- **Where.** The game menu's `inbox` entry, after `codex`, shown once a chat has finished.
  Its label and the page heading are `[words] inbox`; with a genre kit and that word left
  as is, the kit's `messages` title (Messages, Whispers, Dispatches, Pigeon post, Comms,
  Letters).
- **Rows.** One per finished chat, newest first: the contact, then " · " and the chat's
  opening time when it has one. The unread dot (`codex.new.fill_color`) stays until the
  chat is shown on the page. One tab, so no tab row.
- **Detail.** The title is the row's. One paragraph per message, 12 apart: the sender's
  name and a colon in bold, then the text; the player's messages under `[words] inbox_me`
  ("You"); later time dividers in italics (the opening time is in the title). No picture, purse, pick or Use button.
- **Colors and motion.** The Codex view's tokens (`codex.*`, `list.*`, `panel.*`), so the
  page follows the theme, the scheme and W67 as the Codex page does; nothing moves.

### Check roll (F59)

Spec: specs/F59-choice-checks/SPEC.md and proposal I-05. Modules:
`engine/ui/builtin/check_roll.py` (the card), `engine/app/checkroll.py` (the `CheckRolled`
handler).

- **Where.** One card, 400 units wide, centered across the canvas and in the space above
  the say window (the canvas middle in NVL or with the box hidden), drawn above the stage
  and the box. It takes no input: a click, Space or Enter reaches the textbox, whose idle
  advance ends the roll's wait (Esc still opens the game menu).
- **Rows.** "Empathy check" (22 × text scale); two 64-unit dice 24 apart (rounded squares,
  3-unit outline, pips on a 3 × 3 grid); "Needs 10" while they tumble, then
  "Dice 6 + Empathy 3 = 9 vs 10" (20); then the result (30, bold): "Success" or "Failure",
  "(double six)" or "(double one)" when the rule decided it. Sizes follow the player's
  text scale up to 150 %.
- **Tokens.** No tokens of its own: it uses the choice buttons', so every color scheme,
  `[style.*]` look and imported palette styles it. Card: `choice.fill_color` at
  `max(choice.fill_opacity, 0.90)`, border `choice.marker.fill_color`. Dice:
  `choice.fill_color` with `choice.marker.fill_color` outlines and pips. Text:
  `choice.text_color`; "Success" in `choice.marker.fill_color`, "Failure" in
  `choice.text_color` (a failure is part of the story, not an error, so never red).
- **Contrast.** Text on the card is W67's `choice.text_color` / `choice.fill_color` pair
  (the card is at least as opaque as the buttons); the marker on the fill is the pair F59's
  badge uses (at least 4.47:1 in every built-in scheme; tests check both in all 28).
- **Motion.** See Standard timings, "Check roll (F59)".

## Changelog

- 2026-11-01: Created with F04 (vn-ui-designer): canvas and anchors, standard stage
  positions, layers, theme token naming and the `[theme]` table, fixed engine colors
  (recorded from F01), standard timings, reduced-motion rule, global keys.
- 2026-11-01: F05 (vn-ui-designer): in-game screen regions, say-window layer and hidden
  mode, `_opacity` suffix, frames and nine-slice convention, textbox tokens, indicator bob
  and easings, reduced-motion rule for idle loops, in-game reading keys, §7 Text.
- 2026-11-01: F44 (vn-ui-designer): §8 Tools, saying that dev tool windows are native and
  follow their own 03-ui.md.
- 2026-11-01: F10 (vn-ui-designer): quick-menu pill and F15 indicator slot, menu screen
  regions; layer 4 confirmed and hidden mode hides it; screens-above rule with dims; F10
  areas, `on` state, per-state frames, `music` type, F10 token list; fade black and
  sampler backdrop colors; F10 timings and reduced-motion rule for UI; Esc moved off the
  global table, Start reserved, menu navigation table; UI text rules; new §9 Widgets,
  focus, and back.
- 2026-11-01: F11 (vn-ui-designer): notice area and the title-page sidebar (F10 G2
  confirmed); notices above all screens and never captured; `save` and `notice` areas and
  tokens; load fade and notice timings; F5 / F9, west, and Delete / Backspace; text over
  pictures sits on tags; page row, tag, and notice widgets with the shared notice rules.
- 2026-11-01: F15 (vn-system-architect, from the approved F15 SPEC): the skip/auto
  indicator region and layer-4 row, Ctrl/Tab/A rows with their modifier rules (F15 07 I-6),
  and skip's reduced-effects pacing.
- 2026-11-02: F04 built (step 8): the standard stage positions, layer 1 (the stage),
  `stage.empty_color`, and the missing-art colors are no longer marked proposed.
- 2026-11-02: F14 (vn-ui-designer): rewind tag and limit mark regions; layer 4 adds the
  tag and new layer 6 "In-game cues"; `rollback` area and tokens; limit-cue timing and its
  reduced version; wheel, Page Up/Down, and shoulder rollback rows (wheel up no longer
  "history").
- 2026-11-02: F05 built (step 7): the say window region and layer, hidden mode, `_opacity`,
  frames and fills, the textbox tokens (the three styled faces are bundled), the indicator
  bob, easings, the in-game reading keys, and §7 Text are no longer marked proposed. §7
  names the dev contrast warnings.
- 2026-11-02: F23 (vn-ui-designer), all marked proposed:
  - Minigame screen regions (heading, hint bar, content area, cue point) and the sidebar
    fit steps.
  - The minigame screen in "Screens above", layer 6 over a minigame, and the
    opening-picture thumbnail rule.
  - The `minigame` and `plugin` areas, plugin tokens and words, the `minigame.*` tokens,
    and two words.
  - The minigame dissolve and its reduced version.
  - Shift+F8, the "In a minigame" input table, and Backspace as Back in a minigame.
  - Heading and hint, plus the Codex view as a hostable widget, in §9.
- 2026-11-02: F20 (vn-ui-designer), all marked proposed:
  - The flowchart viewport and detail-panel region.
  - The sidebar fit count with Codex and Flowchart, and a third title-fit step.
  - The `flowchart` area and its tokens.
  - View-pan and double-click timings, with limit-cue and load-fade reuse and their reduced
    versions.
  - Chart-view input differences and the no-text-below-24 rule for zoomed views.
  - The chart view widget, its focus exception (hover doesn't focus), and tag reuse.
- 2026-11-02: F10 built (step 9): the quick-menu strip row follows F10 I-4 (the pill stays
  inside the strip; its bottom and the choice floor at 100% and 150%), and no F10 entry is
  marked proposed: menu screen regions, layer 4, screens above, the F10 areas, `music`,
  per-state frames, the F10 token list, fade black and the sampler backdrop, the F10
  timings and reduced-motion rule, Esc, the game-menu row, menu navigation, UI text, and
  §9. Hidden mode and "Where authors set them" are confirmed.
- 2026-11-02: F07 built (step 5): layer 5 (Choices) is no longer reserved: the choice
  stack, its area, hidden mode, and the 250 ms guard. The `choice.*` tokens are listed
  with their defaults and ranges (`choice.locked.fill_opacity` 0.90, F07 07 I-3), with the
  choice fade-in and guard timings and the fade's reduced-motion cut.
- 2026-11-02: F09 step 5 (`04` §17 item 6, `07` I-10), verbatim from F09 `01-design.md` and
  marked "(proposed, F09)" until F09 signs off: layer 2's shake and flash (transitions
  replace layer 1's picture), the `effects` area and its `effects.*` tokens, the stage
  transition and effect rows under "Standard timings" (wipes are left out: not built), and
  the flash limit, its counting rule, and the reduced versions under "Reduced motion and
  flashing". The "Instant cut" row now names `with cut`.
- 2026-11-02: F11 built (step 12): no F11 entry is marked proposed: the notice area,
  notices over every screen, the `save` and `notice` areas and their tokens, the load
  fade and notice timings and their reduced-motion cuts, F5 / F9, Delete / Backspace /
  west on the save pages, text on tags over pictures, the page row, tag, and notice
  widgets, and §9's Notice.
- 2026-11-02: F22 built (step 3): the F3 row names the dev overlay's meter lines. F16
  built (step 5): "Reduced motion and flashing" names the Settings toggle and `[effects]
  reduce`.
- 2026-11-02: F14 built (step 6): no F14 entry is marked proposed: the rewind tag and limit
  mark regions, the rewind tag in layer 4, layer 6 "In-game cues" (the shell's cue slot,
  drawn after scene captures and before notices, not while covered), the `rollback` area,
  the six `rollback.*` tokens with their own defaults and purposes, `words.back`, the W64
  and W67 forms for the mark, the limit-cue timing and its reduced version, and the
  wheel, Page Up/Down, and shoulder rows.
- 2026-11-02: F17 built (step 5): the NVL say window region (panel, text column, name rows,
  line gap, the choice area under the page), layer 3's NVL panel (never drawn with the
  text box; the quick menu, choices, and cues over it), the `nvl` area, the ten `nvl.*`
  tokens with their defaults and ranges, and the default full-screen contrast ratios with
  the W100 warning in §7. Layer 3 is no longer reserved for F17.
- 2026-11-02: F21 built (step 5): the `codex` area and its three tokens
  (`codex.new.fill_color`, `codex.locked.text_color`, `codex.image_height`) with their
  defaults, ranges, and contrast on the default panel; the Codex view widget is no longer
  proposed.
- 2026-11-02: F24 built (step 4): the poem game's `plugin.poem_game` tokens, their
  defaults and clamped ranges (page width 560–1232, word size 24–48, counter size
  24–40), and its two words.
- 2026-11-02: F25 built (step 4): the cross-examination's `plugin.present_evidence`
  tokens (the statement, speaker, and bar colors, the statement size 24–40, and the Could
  `press_sound` and `present_sound`), their contrast on the defaults, and its ten words.
- 2026-11-02: F26 built (step 4): the phone chat's `plugin.phone_chat` tokens (the phone,
  bar, header, message, bubble, name, divider, and typing-dot tokens), their defaults and
  clamped ranges (body width 360–600, header size 24–40, message size 24–36), their contrast
  on the defaults, and its four words.
- 2026-11-02: F27 built (step 4): the puzzle room's `plugin.puzzle_room` tokens (the two
  ring colors) and its fourteen words.
- 2026-11-02: F20 built (step 9): no F20 entry is marked proposed: the flowchart viewport
  and detail panel region, the sidebar and title fit with Flowchart, the `flowchart` area and
  its tokens (with `[theme.flowchart]` and its sub-tables), the 18 `flowchart_*` words with
  their defaults, the view pan and double-click timings, reduced motion for chart views, the
  chart view's keys, zoom floor, widget, and focus rule.
- 2026-11-02: F23 built (steps 4–6): the minigame regions, screen, thumbnail rule, `minigame`
  and `plugin` areas, plugin tokens, frame, dissolves, Shift+F8, and minigame keys are no
  longer marked proposed.
- 2026-11-02: F28 built (step 6): layer 2's glitch contents replace "F28 (reserved)"; the
  glitch looks, bursts, and `with glitch` under "Standard timings"; the glitch flash rules and
  reduced looks under "Reduced motion and flashing".
- 2026-11-02: F30 built (step 6): the fake crash screen and the first-launch name question
  under "Screens above" (with the name's clean thumbnails), and the fake crash row in
  "Fixed engine colors".
- 2026-11-02: F32 built (step 6): run-time looks under "Where authors set them"
  (`[playthrough.N]` and `[style.<name>]` layers, `GameShell.theme` following the current
  look, player settings winning, what changes at once on a style switch).
- 2026-11-03: F36 W5: the Extras paragraph gains the Endings and Scenes pages (no new
  tokens) and the game menu during a replay.
- 2026-11-04: F49 W1: color schemes under "Where authors set them": `[theme] preset` and a
  style's `preset`, the lookup order with the scheme layer (as architecture "Looks"), the
  six-scheme table, the mapped, following and neutral token groups, and W67's scheme
  sentence.
- 2026-11-04: F52 (vn-feature-designer): §9 "Text field and on-screen keyboard (proposed,
  F52)": field, letter cell, bare field, typing rules, keyboard panel, `text_entry.*` tokens.
- 2026-11-04: F52 07 (vn-system-architect): §9's F52 entry accepted with the keyboard heights
  (472/504, F52 C1), its modal host ownership, and the Backspace and focus exceptions.
- 2026-11-04: F51 (builder, P4): `choice.timer.fill_color`, `track_color` (following
  `choice.marker.fill_color` and `choice.focused.fill_color`, C1) and `tick_sound` in §3
  with the timed menu's countdown panel; the "Choice countdown" row in §5 (Timing assist,
  the fraction kept on a level change, C5) and its reduced-motion rule.
- 2026-11-04: F52 (builder): §9 "Text field and on-screen keyboard" built (no longer
  proposed), with the as-built text inset, key width and W67 note.
- 2026-11-06: F60 (builder): "Genre kits" under the color schemes: `[theme] kit`, what a
  kit sets, and the meter look order (`[meter.<name>]` > kit > defaults).
- 2026-11-06: F61 (builder): the status corner: its region, `corner.*` tokens, and §9
  "Status corner" (layout, layer, visibility, motion, W67).
- 2026-11-06: F62 round 2 (builder): §9 "Shown meters" (rows, the five looks, the NVL
  column, colors, motion) and the corner's rank-change pulse.
- 2026-11-06: F59 (builder): §9 "Check roll" (the dice card after a checked pick: rows,
  choice tokens, contrast) and its Standard timings row; F62: the rank-change pulse is a
  ring that grows and fades over 0.4 s.
- 2026-11-06: F65 round 1 (builder): §9 "Inbox page": codex kinds, the Inbox page's rows
  and detail, and the kit's name for it.
