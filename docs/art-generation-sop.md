# How to generate character art

This is the step-by-step way to make the game's character art with an image generator:
**sprites** (a character's emotions, shown while she talks) and **CGs** (full-screen
romance scenes). Follow it in order, and every character will match the others and drop
straight into the game.

**Tool:** ChatGPT's image generation. It follows panel layouts better than Gemini, which
draws the figures over each other. Midjourney is worse still at layouts.

**Cast:**

| Character | Who she is | Class | Height and build |
|---|---|---|---|
| Seraphine | high-elf princess | royalty | tall |
| Amara | merchant's daughter | wealthy | average |
| Mei-Lin | magic academy student | middle class | short, petite |
| Wren | farm girl | rural poor | average, curvy and busty |
| Kesh | half-orc street thief | slum poor | tall, slender |

---

## Rules for every picture

1. **Style:** simple bright anime style, with bold clean outlines, flat colors, one soft
   shadow tone and large expressive eyes. Describe the style in words. Don't name another
   game: ChatGPT may refuse, or copy that game's characters.
2. **Keep details low.** A few strong features per character (hair, one accessory, a
   simple outfit). Heavy detail made the image step fail.
3. **Every character is an adult** ("adult", "early 20s" are in every prompt).
4. **Romance wording:** write "romantic", "tender", "close", "blushing". Don't write
   "sensual", "seductive" or "intimate"; they get refused or come out stiff.
5. **Keep the hands close to the body on sprite sheets.** A raised fist or open arms
   crosses into the next panel.
6. **Make Seraphine first.** Once you like her style, upload her sheet when you start
   each other character, so the style stays the same across the cast (see step 3 below).

---

## Part 1: Sprites

Each character gets 8 emotions, made as two sheets of 4 in one ChatGPT chat:

| Sheet | Panel 1 | Panel 2 | Panel 3 | Panel 4 |
|---|---|---|---|---|
| A | neutral | happy | sad | angry |
| B | surprised | embarrassed | worried | laughing |

### Steps

1. **Start a new chat** for the character.
2. **Paste her Sheet A prompt** (below).
3. **For every character after Seraphine,** upload Seraphine's Sheet A image and add this
   line at the very top of the prompt:
   `Match the art style of the attached image exactly, but draw a different character.`
4. **Check the sheet:** 4 panels, one figure in each, same outfit and size in all four,
   nothing crossing the white lines. Fix anything wrong (see [Fixing problems](#fixing-problems)).
5. **In the same chat, paste the Sheet B prompt** (below).
6. **Download both sheets** and cut them into sprites (see [Part 3](#part-3-putting-pictures-in-the-game)).

### Sheet A prompts

#### Seraphine (high-elf princess, royalty)
```
Visual novel character expression sheet, wide landscape image. Simple bright anime style: bold clean outlines, flat colors with one soft shadow tone, large expressive eyes, cute simple features, minimal detail, cheerful pastel-leaning palette.

4 equal tall vertical panels separated by thin white vertical lines, one figure per panel, each fully inside its panel with empty space around her. Same character in every panel, standing, head to mid-thigh, same size and position. Solid flat grey background. No text.

Character: Seraphine, an adult high-elf princess, early 20s, tall. Pale skin, pointed ears, long straight silver hair, small gold tiara, violet eyes. Simple white and blue royal dress with a gold belt.

Panel 1: neutral, calm, hands folded at her waist.
Panel 2: gentle warm smile, hands folded at her waist.
Panel 3: sad, teary downcast eyes, one hand on her chest.
Panel 4: angry, narrowed eyes, frown, arms at her sides.
```

#### Amara (merchant's daughter, wealthy)
```
Visual novel character expression sheet, wide landscape image. Simple bright anime style: bold clean outlines, flat colors with one soft shadow tone, large expressive eyes, cute simple features, minimal detail, cheerful pastel-leaning palette.

4 equal tall vertical panels separated by thin white vertical lines, one figure per panel, each fully inside its panel with empty space around her. Same character in every panel, standing, head to mid-thigh, same size and position. Solid flat grey background. No text.

Character: Amara, an adult merchant's daughter, early 20s, average height. Brown skin, amber eyes, long black hair in a side braid over her shoulder, gold hoop earrings. Simple yellow and teal tunic dress with a sash belt, gold bracelets.

Panel 1: neutral, confident small smirk, one hand on her hip.
Panel 2: bright friendly smile, hands clasped in front of her.
Panel 3: sad, teary eyes, holding her own arm.
Panel 4: angry, scowling, both hands on her hips.
```

#### Mei-Lin (academy student, middle class)
```
Visual novel character expression sheet, wide landscape image. Simple bright anime style: bold clean outlines, flat colors with one soft shadow tone, large expressive eyes, cute simple features, minimal detail, cheerful pastel-leaning palette.

4 equal tall vertical panels separated by thin white vertical lines, one figure per panel, each fully inside its panel with empty space around her. Same character in every panel, standing, head to mid-thigh, same size and position. Solid flat grey background. No text.

Character: Mei-Lin, an adult magic academy student, early 20s, short and petite. Light skin, dark eyes, round glasses, short black bob with bangs. Navy school robe over a white blouse and green vest, grey skirt, satchel strap across her chest.

Panel 1: neutral, attentive, both hands holding her satchel strap.
Panel 2: shy small smile with pink cheeks, both hands holding her satchel strap.
Panel 3: sad, shoulders slumped, eyes lowered.
Panel 4: angry pout with puffed cheeks, fists at her sides.
```

#### Wren (farm girl, rural poor)
```
Visual novel character expression sheet, wide landscape image. Simple bright anime style: bold clean outlines, flat colors with one soft shadow tone, large expressive eyes, cute simple features, minimal detail, cheerful pastel-leaning palette.

4 equal tall vertical panels separated by thin white vertical lines, one figure per panel, each fully inside its panel with empty space around her. Same character in every panel, standing, head to mid-thigh, same size and position. Solid flat grey background. No text.

Character: Wren, an adult farm girl, early 20s, average height, curvy full-figured build with a large bust. Fair skin with freckles, green eyes, red hair in a messy low ponytail. Plain cream shirt with rolled sleeves, brown laced vest, green neck scarf, brown skirt with a patch.

Panel 1: neutral, easygoing, hands on her hips.
Panel 2: big wide grin, hands on her hips.
Panel 3: sad, trembling lip, arms wrapped around herself.
Panel 4: angry, glaring, gritted teeth, fists at her sides.
```

#### Kesh (half-orc street thief, slum poor)
```
Visual novel character expression sheet, wide landscape image. Simple bright anime style: bold clean outlines, flat colors with one soft shadow tone, large expressive eyes, cute simple features, minimal detail, cheerful pastel-leaning palette.

4 equal tall vertical panels separated by thin white vertical lines, one figure per panel, each fully inside its panel with empty space around her. Same character in every panel, standing, head to mid-thigh, same size and position. Solid flat grey background. No text.

Character: Kesh, an adult half-orc street thief, early 20s, tall and slender with a lean, narrow build. Grey-green skin, two small lower tusks, gold eyes, dark curly hair tied up messily, small scar through one eyebrow. Ragged dark hooded cloak with the hood down, patched brown vest, bandaged hands.

Panel 1: neutral, wary, arms crossed.
Panel 2: sly crooked grin showing a tusk, arms crossed.
Panel 3: sad, looking away, holding her own arm.
Panel 4: angry, snarling, brows drawn down, fists at her sides.
```

### Sheet B prompt (same for every character, in the same chat as her Sheet A)
```
Make a second sheet of this exact same character in the same style and layout: 4 panels separated by thin white lines, one figure per panel, same size and position, same outfit and hair, solid flat grey background, no text. Only change the expressions:
Panel 1: surprised, wide eyes, small open mouth.
Panel 2: embarrassed, blushing, looking away, fingertips on her cheek.
Panel 3: worried, brows raised, biting her lip, hand at her chin.
Panel 4: laughing, eyes closed, open mouth, hand near her mouth.
```

---

## Part 2: Romance CGs

Two full-screen scenes per character, drawn from the player's point of view. They're
romantic but not sexual: fully clothed, built on closeness, blushing and eye contact.

### Steps

1. **Finish the character's sprites first.**
2. **Start a new chat** and upload her Sheet A image. Every CG prompt starts by asking
   ChatGPT to match it.
3. **Paste one CG prompt.** Make one CG per message.
4. **Check that her face is away from the top and bottom edges.** ChatGPT usually makes
   wide images in 3:2, and the game crops them to its 16:9 screen, cutting a strip off the
   top and bottom. If her face is too close to an edge, ask: "Make it a 16:9 image with
   the same content."

### Seraphine

**Moonlit balcony** (`cg/seraphine_balcony`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Seraphine, the high-elf princess, stands very close to the viewer on a castle balcony at night under a large full moon, soft blue moonlight and glowing lanterns. Close-up from the chest up, her face filling much of the frame. She holds the viewer's hand gently against her chest with both hands, cheeks deeply blushing, eyes soft and half-lowered, a shy tender smile, her silver hair lifted slightly by the breeze.
```

**Garden at dusk** (`cg/seraphine_garden`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Seraphine, the high-elf princess, in a royal rose garden at sunset, warm golden-pink light and drifting petals. Extreme close-up, her face very near the viewer's, leaning in slowly with her eyes gently closed and lips softly parted, deep blush across her cheeks, one hand lightly resting on the viewer's shoulder. A tender, quiet moment just before a kiss.
```

### Amara

**Rooftop at sunset** (`cg/amara_rooftop`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Amara, the merchant's daughter, sits close beside the viewer on a city rooftop among colorful silk awnings at sunset, a warm orange sky and a busy bazaar far below. Close-up from the chest up. She leans in toward the viewer with a playful, confident smile, one finger reaching out to tap the viewer's nose, cheeks lightly blushing, her braid falling over her shoulder.
```

**Lantern bazaar at night** (`cg/amara_bazaar`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Amara, the merchant's daughter, in a night bazaar strung with glowing paper lanterns. Close-up from the chest up. She has pulled the viewer close by the hand and is now caught off guard by how close they are: wide eyes, flustered deep blush, lips parted, still holding the viewer's hand between them, for once without a clever word to say.
```

### Mei-Lin

**Library at midnight** (`cg/meilin_library`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Mei-Lin, the academy student, sits right next to the viewer at a wooden desk in a magic library late at night, tall bookshelves, a single candle and a few floating glowing runes. Close-up from the chest up. She has just looked up from an open book and realized how close their faces are: glasses slightly askew, deep pink blush, wide startled eyes, a tiny embarrassed smile, holding the book to her chest.
```

**Sharing a cloak in the rain** (`cg/meilin_rain`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Mei-Lin, the academy student, stands pressed close to the viewer under a stone archway of the academy while rain pours outside, cool blue-grey light. Close-up from the chest up. She is holding her navy school robe up over both of their heads like a shelter, looking up at the viewer shyly, cheeks blushing, a few raindrops on her glasses, a soft hopeful smile.
```

### Wren

**Fence at sunset** (`cg/wren_fence`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Wren, the farm girl, leans forward on a wooden farm fence at sunset, facing the viewer from the other side of it, a golden wheat field and a red barn behind her, warm glowing light. Close-up from the chest up. Both of her forearms rest folded on top of the fence rail with her chin resting on them, her hands relaxed and mostly hidden under her arms. She looks up at the viewer with a soft warm smile and a deep blush, freckles bright in the sunlight, red hair glowing at the edges, a small wildflower tucked behind her own ear.
```

**Harvest festival dance** (`cg/wren_festival`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Wren, the farm girl, dancing with the viewer at a village harvest festival at night, a bonfire, string lights and blurred dancing villagers behind her. Close-up from the chest up. She holds both of the viewer's hands, mid-twirl, laughing with her eyes on the viewer, deeply blushing, a few strands of hair flying loose, joyful and a little breathless.
```

### Kesh

**City rooftop at night** (`cg/kesh_rooftop`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Kesh, the half-orc street thief, sits close to the viewer on a slum rooftop at night, the city lights spread out below and stars above. Close-up from the chest up. Her guard is down for once: hood down, a rare small soft smile, faint blush on her grey-green cheeks, looking at the viewer sideways with gentle eyes, her bandaged hand resting just beside the viewer's hand.
```

**Hiding in an alley** (`cg/kesh_alley`)
```
Match the character and art style of the attached image exactly. Romantic visual novel CG illustration, wide 16:9 landscape image, simple bright anime style: bold clean outlines, flat colors with soft shading, large expressive eyes. No text.

First-person view: Kesh, the half-orc street thief, has pulled the viewer into a narrow shadowed alcove of a rainy alley to hide from passing guards, a lantern's glow at the alley mouth. Extreme close-up, her face very near the viewer's, one finger pressed to her own lips to say "shh", eyes wide as she realizes how close they are, a surprised blush spreading across her cheeks.
```

---

## Fixing problems

Reply in the same chat. Don't start over unless the chat keeps failing.

| Problem | What to send |
|---|---|
| "Image generation failed" | Click **Try again** once or twice. Still failing: start a new chat and paste again. Still failing: cut details from the character line. If a short prompt fails too, ChatGPT is busy or you've hit your daily image limit. Wait a few hours. |
| One panel's outfit or hair is different | `Panel 3 has a different outfit than the others. Redo it to match panels 1, 2 and 4 exactly.` |
| One panel's expression is wrong | `Redo panel 2 only, keep everything else exactly the same.` |
| Figures cross the white lines | `Keep each figure fully inside its own panel with empty space around her. Nothing may cross the white lines.` If one gesture keeps crossing, change it to one closer to the body. |
| The image is square, not wide | `Make it a wide landscape image with the same content.` |
| The style doesn't match the others | Start a new chat, upload Seraphine's Sheet A, and add the "Match the art style…" line at the top. |
| A refusal on a CG | Look for words like "sensual" or "seductive" and swap them for "romantic" or "tender". |

---

## Part 3: Putting pictures in the game

### Sprites

1. Remove the grey background with any background-removal tool (for example, remove.bg or
   the "remove background" tool in most image editors).
2. Cut the sheet along the white lines into 4 pictures.
3. Save each one as a PNG in a folder named after the character, named after the emotion:

```
game/images/seraphine/neutral.png       →  show seraphine neutral
game/images/seraphine/happy.png         →  show seraphine happy
game/images/seraphine/sad.png           →  show seraphine sad
game/images/seraphine/angry.png         →  show seraphine angry
game/images/seraphine/surprised.png     →  show seraphine surprised
game/images/seraphine/embarrassed.png   →  show seraphine embarrassed
game/images/seraphine/worried.png       →  show seraphine worried
game/images/seraphine/laughing.png      →  show seraphine laughing
```

Use lowercase letters, digits and `_` only in file and folder names: no spaces or
hyphens (`meilin`, not `Mei-Lin`).

**Size:** ChatGPT's sprites come out about 1000 pixels tall, which is too big for the
game's 720-high screen. Tell the game once, in `game/config.toml`:

```toml
[stage]
art_height = 1080
```

**Height:** every sprite is drawn at the same scale, with Mei-Lin shorter and Seraphine and
Kesh taller. Don't resize one character to fill the frame, or they'll all look the same
height on screen.

### CGs

Save each CG in `game/images/cg/` with the name shown above its prompt, for example
`game/images/cg/seraphine_balcony.png`. CGs fill the screen at any size; no setting is
needed.

Add each CG to the **Extras** gallery with a line at the top level of a script (outside
any scene). It unlocks for the player the first time the story shows it:

```
lock gallery cg seraphine_balcony "Moonlit Balcony"

label seraphine_balcony_scene:
    scene cg seraphine_balcony
    seraphine "I've never shown anyone this view before."
```

---

## Checklist per character

- [ ] Sheet A made (neutral, happy, sad, angry)
- [ ] Sheet B made (surprised, embarrassed, worried, laughing)
- [ ] Style matches Seraphine's
- [ ] 8 sprites cut, background removed, saved in `game/images/<name>/`
- [ ] CG 1 made and saved in `game/images/cg/`
- [ ] CG 2 made and saved in `game/images/cg/`
- [ ] Both CGs added to the gallery with `lock gallery`
