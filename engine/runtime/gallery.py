"""The CG gallery at run time: the F12 unlock kind ``"gallery"`` (F34 ``04-technical.md`` §3,
§7.1, §7.2, §7.6).

Why this module exists: a gallery picture unlocks the first time it shows in the story and
stays unlocked across playthroughs, so its record is an F12 unlock kind, not ``GameState``
(nothing is saved, rolled back, or changed by a load or New Game; F16's Delete progress,
``store.reset``, empties it). The kind is **revocable**, so ``lock gallery`` (F19's ``Lock``
row and its ``run_lock``) can take a picture back; ``unlock gallery`` is ``run_lock`` too.

- ``register(interp)`` (``Interpreter.__init__``, F34-W2; F39 calls it again with a new
  program): the kind, with ``known`` = membership in ``program.gallery_pictures``, so names
  on file that the script no longer declares are never shown and give way when the kind is
  full (PR-F34-07). Registering again replaces ``known``.
- ``seen(interp, image)`` (the three stage executors, F34-W2): one lookup; a gallery
  picture (entry or version, named exactly as the stage holds it) is unlocked. Nothing
  during F14's quiet forward re-run (``timeline.replaying``); restores never call it.
- ``unlocked(program, store)``: the declared pictures the store holds, in gallery order (what
  the Gallery page shows; undeclared names on file stay hidden).
- ``preview_names(program)``: every gallery picture in gallery order (dev ``--extras``).

Layering as ``endings.py``: below the interpreter, importing it only under ``TYPE_CHECKING``.
Pure: no file, clock, randomness, or thread.
"""

from typing import TYPE_CHECKING, Final

from engine.runtime.persistent import PersistentStore

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter
    from engine.script.program import Program

GALLERY_KIND: Final = "gallery"         # the F12 unlock kind (revocable)


def register(interp: "Interpreter") -> None:
    """Register (or re-register, F39) the ``"gallery"`` kind on ``interp.persistent`` for
    ``interp.program``'s pictures. Safe to repeat."""
    pictures = interp.program.gallery_pictures

    def known(name: object) -> bool:
        return type(name) is str and name in pictures

    interp.persistent.register_kind(GALLERY_KIND, known=known, revocable=True)


def seen(interp: "Interpreter", image: str | None) -> bool:
    """A ``scene``/``show``/dialogue look put ``image`` on stage: unlock it when it is a
    gallery picture. True if that was new. Never during F14's quiet forward re-run."""
    if image is None or interp.timeline.replaying:
        return False
    if image not in interp.program.gallery_pictures:
        return False
    return interp.persistent.unlock(GALLERY_KIND, image)


def unlocked(program: "Program", store: PersistentStore) -> tuple[str, ...]:
    """The declared gallery pictures ``store`` holds, in gallery order (each entry's picture,
    then its versions)."""
    held = store.unlocked(GALLERY_KIND)
    if not held:
        return ()
    names = set(held)
    return tuple(p for entry in program.gallery for p in entry.pictures if p in names)


def preview_names(program: "Program") -> tuple[str, ...]:
    """Every gallery picture in gallery order: what dev ``--extras`` unlocks in memory."""
    return tuple(p for entry in program.gallery for p in entry.pictures)


__all__ = ["GALLERY_KIND", "preview_names", "register", "seen", "unlocked"]
