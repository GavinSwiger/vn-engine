"""The plugin message table (F23 ``02`` §4.1, ``04`` §11.1; ``06`` §0.1 "Codes").

Why this module exists: the plugin loader raises E273, E274, and E278 and warns W160, W161,
and W163–W165, but ``minigames`` never imports ``script`` (F23 ``04`` §2), so these texts
can't live in ``script/messages.py``. Tests read them from here. Every text is a draft for
the narrative designer (F23 ``06`` G2); the forms marked "drafted here" are not in ``02`` or
``04`` and were written by the s3a builder.

Every argument that comes from a file name or from plugin code goes through ``show()``
(``echo()``: redacted, escaped, and cut), and every finished message is cut to
``MESSAGE_MAX_CHARS``.
"""

from engine.core.minigame_types import API_VERSION
from engine.core.redact import echo, truncate

MESSAGE_MAX_CHARS = 1_000
SHOWN_MAX_CHARS = 80


def show(text: object) -> str:
    """A name or value from a file name or plugin code, safe to embed in a message."""
    return echo(text if type(text) is str else repr(text), SHOWN_MAX_CHARS)


def _cut(text: str) -> str:
    return truncate(text, MESSAGE_MAX_CHARS)


def _api(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


ENGINE_API = _api(API_VERSION)

# --- E273 P forms (the prefix ``minigames/x.py, line N: `` comes from the error) ----------

def e273_python_mistake(detail: str | None) -> str:
    """A SyntaxError in the plugin's text (02 §4.1)."""
    if detail:
        return _cut(f"this minigame plugin has a Python mistake: {detail}.")
    return "this minigame plugin has a Python mistake."


def e273_stopped(detail: str | None) -> str:
    """Another exception while the plugin's top level ran (02 §4.1)."""
    if detail:
        return _cut(f"this minigame plugin stopped with an error while loading: {detail}. "
                    "Fix the plugin; the log has the details.")
    return ("this minigame plugin stopped with an error while loading. Fix the plugin; the "
            "log has the details.")


def e273_stuck(seconds: float) -> str:
    return (f"this minigame plugin ran for {seconds:g} seconds while loading without "
            "finishing, so it is probably stuck in a loop.")


E273_NO_NAME = 'this minigame has no name. Add name = "stargazing" to the class.'


def e273_bad_name(name: str) -> str:
    return (f'the minigame name "{show(name)}" can\'t be used. Use a-z, 0-9, and _, starting '
            "with a letter, up to 40.")


def e273_bad_arg_name(name: str) -> str:
    return (f'the argument name "{show(name)}" can\'t be used. Argument names follow the '
            "rules for story variables.")


def e273_too_many_args(count: int, limit: int) -> str:
    return f"this minigame declares {count:,} arguments; keep it to {limit}."


def e273_not_plain(what: str, kind: str = "text") -> str:
    """``title must be text written in the class, not a property or computed value.``;
    ``kind`` is "text", "a dictionary", "True or False", "Arg() or Arg(default=…)", or
    "an Outcome or None" (the last three drafted here)."""
    return f"{what} must be {kind} written in the class, not a property or computed value."


def e273_unsaveable(subject: str, holds: str, advice: str) -> str:
    """``the test outcome holds a set, which can't be saved. Use a list instead.``"""
    return f"{subject} holds {holds}, which can't be saved. {advice}"


def e273_bad_change(subject: str) -> str:
    """Drafted here: an outcome's changes not made with the API's change functions."""
    return (f"{subject} has a change that wasn't made with add_points, set_points, give, take, "
            "or unlock_tip.")


def e273_not_a_class(shown: str) -> str:
    """Drafted here: ``register`` was given something other than a Minigame class."""
    return f"register needs a class that subclasses Minigame, but this got {shown}."


def e273_bad_api(value: str) -> str:
    """Drafted here: an ``api`` text that isn't a version."""
    return f'api must be a version such as "1.0", but this has "{show(value)}".'


def e273_other_major(unit: str, major: int) -> str:
    """Whole message (it names the file itself): another API major."""
    return (f"{unit} was written for minigame API {major}, but this engine runs API "
            f"{API_VERSION[0]}.")


def e278_newer_minor(unit: str, wanted: str) -> str:
    return (f"{unit} needs minigame API {wanted}, but this engine has {ENGINE_API}. Update the "
            f"engine, or use a version of the plugin made for {ENGINE_API}.")


# --- E273 G forms ------------------------------------------------------------------------

def e273_bad_file_name(ref: str) -> str:
    return (f"{show(ref)} can't be loaded: a plugin's name uses a-z, 0-9, and _, starting with "
            "a letter.")


def e273_reserved_file_name(ref: str) -> str:
    """Drafted here: a stem that fits the rule but is a Python word or a Windows device name
    (``for.py``, ``con.py``)."""
    return (f"{show(ref)} can't be loaded: its name is a reserved word on some systems or in "
            "Python. Rename it.")


E273_NOT_A_REAL_FOLDER = ("game/minigames is a link or not a real folder, so no minigame "
                          "plugins were loaded. Make it a real folder.")
E273_BOUND = ("game/minigames holds more than 64 plugins (or a file over 1 MB, or 8 MB in "
              "all), so they weren't loaded.")


def e273_bound_package(unit: str) -> str:
    """Drafted here: a package over 64 files or 3 folders deep."""
    return (f"{unit} holds more than 64 files or folders nested more than 3 deep, so it "
            "wasn't loaded.")


E273_BOUND_REGISTRATIONS = ("the minigame plugins register more than 256 minigames, so the "
                            "rest weren't loaded.")     # drafted here


def e273_not_utf8(ref: str) -> str:
    return f"{show(ref)} isn't UTF-8 text, so it wasn't loaded."


def e273_unreadable(ref: str) -> str:
    """Drafted here: an OS error while reading a listed plugin file."""
    return f"{show(ref)} couldn't be read, so it wasn't loaded."


# --- E274 G --------------------------------------------------------------------------------

def e274_two_plugins(name: str, first: str, second: str) -> str:
    return (f'two minigame plugins use the name "{show(name)}": {first} and {second}. Rename '
            "one of them.")


# --- Warnings (dev; area ``plugin``) -------------------------------------------------------

def w160_replaces(unit: str, name: str) -> str:
    return (f'{unit} replaces the bundled minigame "{show(name)}", so every minigame '
            f"{show(name)} line starts yours. Rename yours if you meant to keep both.")


def w161_registers_nothing(unit: str) -> str:
    return (f"{unit} registers no minigame, so the story can't start anything from it. "
            "Register one, or move the file into the folder of the plugin that uses it.")


def w163_link(ref: str) -> str:
    return (f"{show(ref)} is a link, so it wasn't loaded. Put the plugin itself in "
            "game/minigames.")


def w163_not_regular(ref: str) -> str:
    """I-9's second form, drafted here: a FIFO, device, or socket."""
    return (f"{show(ref)} isn't a regular file, so it wasn't loaded. Put the plugin itself in "
            "game/minigames.")


def w164_wrong_case(listed: str) -> str:
    return (f'the game has a folder named "{show(listed)}"; plugins load only from '
            '"minigames", in lower case.')


def w165_bidi(ref: str, line: int) -> str:
    return (f"{show(ref)}, line {line}, holds hidden text-direction characters, which can make "
            "code read differently from how it runs.")


W162_BUDGET_MS = 8                       # a plugin's update + draw per frame (04 §10)


def w162_slow_frame(name: str, ms: int) -> str:
    """W162 R (02 §4.1): the host, dev runs, once per minigame per session (s5b)."""
    return (f"minigame {show(name)} took {ms} ms to update and draw one frame, over "
            f"{W162_BUDGET_MS} ms, so the game may stutter. Draw less each frame, or keep "
            "pictures that don't change instead of redrawing them.")


def w64_plugin_image(name: str, ref: str, kind: str, suggestion: str | None) -> str:
    """W64 for ``ctx.gui_image`` (F24 07 I-5, Q-c; dev): drafted here (s5b), for the
    narrative designer. The plugin gets None and draws its own look."""
    if kind == "unreadable":
        return _cut(f"minigame {show(name)}: \"{show(ref)}\" couldn't be read as an image, so "
                    "the minigame's drawn look is used.")
    text = (f"minigame {show(name)}: \"{show(ref)}\" doesn't exist, so the minigame's drawn "
            "look is used.")
    if suggestion is not None:
        text += f' Did you mean "{show(suggestion)}"?'
    return _cut(text)


# --- The achievement hook (F37 §3; API 1.2) ------------------------------------------------
# Registration errors are E273 P forms (the plugin file and line come from the error): F37's
# §3 calls them "F23's E272 plugin form", but E272 is the run-time argument code and these
# are load-time declaration errors, which F23 numbers E273 (F37-S1 decision).

E273_HOOK_SHAPE = "register_achievement_hook needs an object with an unlocked(name) method."
E273_HOOK_TWICE = ("register_achievement_hook was called twice; a game has one achievement "
                   "hook.")
W225_TOO_LONG = "it ran too long"       # W225's reason when the watchdog stopped the call


def w225_failed(method: str, reason: str) -> str:
    """W225 G run: ``reason`` is the exception's type name or ``W225_TOO_LONG``."""
    return (f"the achievement platform hook failed in {method} ({show(reason)}), so it is off "
            "until the game restarts. Achievements are still kept on this computer.")


def w225_slow(method: str, seconds: float) -> str:
    """W225 G run, once per session."""
    return (f"the achievement platform hook took {seconds:.1f} s in {method}; keep hook calls "
            "under 0.1 s so the game doesn't stall.")


# --- The dev key, Shift+F8 (03 "Dev: Shift+F8 notice"; fixed English, not words) ------------

def dev_ended(title: str) -> str:
    return f'Dev: ended "{title}" with its test outcome.'


def dev_no_test_outcome(title: str) -> str:
    return f'Dev: "{title}" has no test outcome, so Shift+F8 can\'t end it.'


# --- INFO (SEC-F23-13; every run) ----------------------------------------------------------

def info_loaded(unit: str, size: int, digest: str, api: str) -> str:
    return f"Loaded minigame plugin {unit} ({size:,} bytes, SHA-256 {digest}, API {api})"


def info_replaced(unit: str, name: str) -> str:
    return f'Minigame plugin {unit} replaces the bundled minigame "{show(name)}"'
