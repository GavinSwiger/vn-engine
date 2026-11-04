"""Studio's doc rows for the words registered before F45 step 1, the built-in forms, and the
modifiers (F45 ``04-technical.md`` §2 Q1, §3, §15 step 1).

Why this module exists: the words that were registered before the doc registry existed get
their ``StatementDoc`` rows here, in one module only F45 owns, so no earlier feature's
``StatementSpec`` site is edited. A word registered later calls ``register_doc`` next to its
own ``register`` (``docs/architecture.md`` "Script program", F45 additions; ``07`` O-2, I-5).

Imported by one line in ``engine/script/__init__.py``, after the statement modules. Every
example loads and launches cleanly in ``tests/fixtures/docgame/`` (TR-F45-01); a ``docs`` of
None is a word whose docs step is pending (the completeness test's ``DOCS_PENDING``).
"""

from engine.script.statement_docs import StatementDoc, register_doc

_LABEL = ("label",)
_IMAGE = ("image",)
_AUDIO = ("audio",)

ROWS: tuple[StatementDoc, ...] = (
    # --- Text ---------------------------------------------------------------------------
    StatementDoc(
        "dialogue", "Dialogue", "Text", '<character> [expression] "text"',
        "A character says a line. Words between the name and the text change the "
        "character's expression.",
        'hana happy "You came!"', "Dialogue and narration", "F02",
        fields=("You came!",)),
    StatementDoc(
        "narration", "Narration", "Text", '"text"',
        "A line of text with no speaker.",
        '"The lanterns were already lit."', "Dialogue and narration", "F02",
        fields=("The lanterns were already lit.",)),
    # --- Story flow ---------------------------------------------------------------------
    StatementDoc(
        "label", "Label (a scene)", "Story flow", "label <name>:",
        "Names a scene at the top level. The story starts at label start.",
        'label fireworks:\n    "The sky lit up."\n    jump bridge', "label", "F02",
        fields=("fireworks",)),
    StatementDoc(
        "jump", "Jump to a label", "Story flow", "jump <label>",
        "Continues at a label and doesn't come back.",
        "jump bridge", "jump", "F02", fields=("bridge",), names=_LABEL),
    StatementDoc(
        "call", "Call a label", "Story flow", "call <label>",
        "Visits a label and comes back to the next line at its return.",
        "call lantern_stall", "call and return", "F02",
        fields=("lantern_stall",), names=_LABEL),
    StatementDoc(
        "return", "Return", "Story flow", "return",
        "Goes back to the line after the call. With no call, the story ends.",
        "return", "call and return", "F02"),
    StatementDoc(
        "chapter", "Chapter card", "Story flow", 'chapter <name> ["heading"] "title" [seconds]',
        "Starts a chapter and shows its title card.",
        'chapter festival "Chapter 1" "The Lantern Festival"', "chapter", "F18",
        fields=("festival", "The Lantern Festival")),
    StatementDoc(
        "rollback", "Rollback wall", "Story flow", "rollback block|off|on|fixed",
        "Controls how far back the player can step. block stops rollback at this line.",
        "rollback block", "rollback", "F14", fields=("block",)),
    # --- Choices ------------------------------------------------------------------------
    StatementDoc(
        "menu", "Menu", "Choices",
        'menu [time <seconds>]:\n    "choice" [timeout] [if condition]:',
        "Shows choices as buttons. The picked choice's lines run, then the story goes on "
        "after the menu. With a time limit, the choice marked timeout is picked when the "
        "time runs out.",
        'menu:\n    "Go to the river":\n        jump river\n    "Stay here":\n'
        '        "You stay a while."', "menu (choices)", "F07",
        fields=("Go to the river", "Stay here")),
    # --- Logic --------------------------------------------------------------------------
    StatementDoc(
        "$", "Python line", "Logic", "$ <python>",
        "Runs one line of Python, usually to change a story variable.",
        "$ coins += 1", "$ (one line of Python)", "F02", fields=("coins += 1",)),
    StatementDoc(
        "if", "If", "Logic", "if <condition>:",
        "Runs its lines when the condition is true. elif and else can follow.",
        'if coins >= 2:\n    hana happy "You bought one!"\nelse:\n    hana sad "Not even one?"',
        "if, elif, else", "F02", fields=("coins >= 2",)),
    StatementDoc(
        "elif", "Elif", "Logic", "elif <condition>:",
        "Checked only when everything above it was false.",
        'if coins >= 2:\n    "Two or more."\nelif coins == 1:\n    "Just one."',
        "if, elif, else", "F02", fields=("coins == 1",), insert=False),
    StatementDoc(
        "else", "Else", "Logic", "else:",
        "Runs when nothing above it was true. It comes last.",
        'if coins >= 2:\n    "Two or more."\nelse:\n    "Fewer."',
        "if, elif, else", "F02", insert=False),
    StatementDoc(
        "points", "Change a meter", "Logic", "points <name> +=|-=|= <amount>",
        "Raises, lowers, or sets a meter. The value stays in the meter's range.",
        "points friendship += 1", "points (character stats)", "F22", fields=("friendship", "1"),
        names=("meter",)),
    # --- Stage --------------------------------------------------------------------------
    StatementDoc(
        "scene", "Scene", "Stage", "scene [<image>] [with <transition>]",
        "Removes every character and sets the background.",
        "scene bg room", "scene", "F04", fields=("bg room",), names=_IMAGE),
    StatementDoc(
        "show", "Show a sprite", "Stage", "show <image> [at <position>] [with <transition>]",
        "Shows a sprite, or changes the one with the same tag.",
        "show hana happy at left", "show", "F04", fields=("hana happy",), names=_IMAGE),
    StatementDoc(
        "hide", "Hide a sprite", "Stage", "hide <tag> [with <transition>]",
        "Removes the sprite with that tag.",
        "hide hana", "hide", "F04", fields=("hana",)),
    StatementDoc(
        "at", "Position", "Stage", "at <position> | at <x> [<y>]",
        "Where a shown sprite stands: left, center, right, a named position, or numbers.",
        "show hana sad at right", "show", "F04", fields=("right",), names=("position",)),
    # --- Audio --------------------------------------------------------------------------
    StatementDoc(
        "play", "Play music", "Audio", 'play music "<file>" [fadein <s>] [volume <n>]',
        "Loops a music track. The same track already playing carries on.",
        'play music "bgm/theme.wav" fadein 2.0', "play", "F08",
        fields=("bgm/theme.wav",), names=_AUDIO),
    StatementDoc(
        "play", "Play a sound", "Audio", 'play sound "<file>" [loop] [volume <n>]',
        "Plays an effect once, over anything else playing.",
        'play sound "sfx/chime.wav"', "play", "F08", fields=("sfx/chime.wav",), names=_AUDIO),
    StatementDoc(
        "queue", "Queue music", "Audio", 'queue music "<file>"',
        "Plays the track after the music before it ends.",
        'queue music "bgm/theme.wav"', "queue", "F08",
        fields=("bgm/theme.wav",), names=_AUDIO),
    StatementDoc(
        "stop", "Stop audio", "Audio", 'stop music|sound|voice ["<file>"] [fadeout <s>]',
        "Stops a channel. fadeout 0 is a hard cut.",
        "stop music fadeout 2.0", "stop", "F08", fields=("music",), names=_AUDIO),
    StatementDoc(
        "voice", "Voice a line", "Audio", 'voice "<file>"',
        "Voices the line directly below it.",
        'voice "voice/hana_001.wav"\nhana "You came!"', "voice", "F08",
        fields=("voice/hana_001.wav",), names=_AUDIO),
    # --- Effects ------------------------------------------------------------------------
    StatementDoc(
        "with", "Transition", "Effects", "... with <transition> [seconds] [color]",
        "Changes the picture with a transition at the end of scene, show, or hide.",
        "scene bg river with dissolve", "with", "F09",
        fields=("dissolve",), names=("transition",)),
    StatementDoc(
        "shake", "Shake the screen", "Effects", "shake [small|medium|large] "
        "[horizontal|vertical] [seconds]",
        "Shakes the screen for a moment.",
        "shake small", "shake", "F09", fields=("small",)),
    StatementDoc(
        "flash", "Flash the screen", "Effects", "flash [color] [seconds]",
        "Flashes the screen to a color and back.",
        "flash white 0.3", "flash", "F09", fields=("white",)),
    StatementDoc(
        "pause", "Pause", "Effects", "pause [seconds]",
        "Waits before the next line.",
        "pause 1.0", "pause", "F09", fields=("1.0",)),
    # --- Minigames (2026-11-02, AC-F45-53): one snippet per bundled minigame, its required
    # arguments as placeholder names (tests/tools/editor/test_outline.py ties them to the
    # plugins' signatures). docs is docs/script-language.md's "minigame" (F23 s6).
    StatementDoc(
        "minigame", "Poem game", "Minigames", "minigame poem_game words=<list> [into <variable>]",
        "The bundled poem game: the player picks words; the result goes into a variable.",
        "minigame poem_game words=poem_words into turns", "minigame", "F24",
        fields=("poem_words", "turns"), names=("minigame",)),
    StatementDoc(
        "minigame", "Present evidence", "Minigames",
        "minigame present_evidence testimony=<dict> answer=<dict> [into <variable>]",
        "The bundled cross-examination: press the witness or present an item.",
        "minigame present_evidence testimony=witness_lines answer=contradictions into turns",
        "minigame", "F25", fields=("witness_lines", "contradictions", "turns"), names=("minigame",)),
    StatementDoc(
        "minigame", "Phone chat", "Minigames",
        "minigame phone_chat chat=<list> contact=<text> [into <variable>]",
        "The bundled phone conversation: the player picks replies.",
        "minigame phone_chat chat=chat_lines contact=contact_name into turns", "minigame", "F26",
        fields=("chat_lines", "contact_name", "turns"), names=("minigame",)),
    StatementDoc(
        "minigame", "Puzzle room", "Minigames", "minigame puzzle_room room=<dict> [into <variable>]",
        "The bundled point-and-click room: look, take, use, and combine items.",
        "minigame puzzle_room room=room_spots into turns", "minigame", "F27",
        fields=("room_spots", "turns"), names=("minigame",)),
    # --- Declarations -------------------------------------------------------------------
    StatementDoc(
        "define", "Define a character", "Declarations", "define <name> = <value>",
        "Sets a name once for the whole game, before the story starts.",
        'define daichi = Character("Daichi", color="#3a6aa8")', "define", "F02",
        fields=("daichi", "Daichi")),
    StatementDoc(
        "default", "Story variable", "Declarations", "default <name> = <value>",
        "Declares a story variable and its starting value.",
        "default trust = 0", "default", "F03", fields=("trust", "0")),
    StatementDoc(
        "image", "Image name", "Declarations", 'image <name> = "<file or #color>"',
        "Names a file outside images/, or a solid color.",
        'image bg dusk = "#2b2140"', "image", "F04", fields=("bg dusk", "#2b2140")),
    StatementDoc(
        "points", "Meter", "Declarations", "points <name> [<low> to <high>] [start <n>]",
        "Declares a meter, a whole-number stat with a range.",
        "points courage 0 to 10 start 5", "points (character stats)", "F22", fields=("courage",)),
    # --- Files --------------------------------------------------------------------------
    StatementDoc(
        "include", "Include a file", "Files", 'include "<file>.vns"',
        "Adds another script file from the script folder to the story.",
        'include "chapter2.vns"', "include", "F02", fields=("chapter2.vns",)),
)

for _doc in ROWS:
    register_doc(_doc)
del _doc

__all__ = ["ROWS"]
