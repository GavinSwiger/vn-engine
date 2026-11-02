"""SIGS (F23 ``06`` §5): fake minigame signatures for Run H and the load checks. No plugin
code runs, except ``lantern_memory``'s declared ``check`` (AC-F23-06).

- ``probe``: ``pairs`` (required), ``hints`` (False), ``label`` (""); title ``Probe game``;
  test ``Outcome(9, (hana += 1,))``; skipped ``Outcome("skipped")``.
- ``bare``: no arguments, no test, no skipped outcome.
- ``lantern_memory``: ``pairs`` (required), ``hints`` (False), with a ``check``.
- ``stargazing``: ``stars`` (required), ``minutes`` (2).
- ``two``: ``pairs`` and ``theme``, both required.

``TWO`` holds only ``lantern_memory`` and ``stargazing``; ``FILLER`` is the 11-name map of
AC-F23-03's "and N more" row (no name close to ``zzz``).
"""

from types import MappingProxyType

from engine.core.minigame_types import REQUIRED, ArgSpec, MeterChange, MinigameSig, Outcome


def _lantern_check(args: dict, story: object) -> str | None:
    pairs = args.get("pairs")
    if type(pairs) is int and pairs > 12:
        return "it takes 2 to 12 pairs."
    return None


def _sig(name: str, *args: ArgSpec, title: str = "", test: Outcome | None = None,
         skipped: Outcome | None = None, check=None) -> MinigameSig:
    return MinigameSig(name=name, title=title or name, source=f"minigames/{name}.py",
                       args=args, test=test, skipped=skipped, check=check)


PROBE = _sig("probe", ArgSpec("pairs", REQUIRED), ArgSpec("hints", False),
             ArgSpec("label", ""), title="Probe game",
             test=Outcome(9, (MeterChange("hana", "+=", 1),)), skipped=Outcome("skipped"))
BARE = _sig("bare")
LANTERN_MEMORY = _sig("lantern_memory", ArgSpec("pairs", REQUIRED), ArgSpec("hints", False),
                      check=_lantern_check)
STARGAZING = _sig("stargazing", ArgSpec("stars", REQUIRED), ArgSpec("minutes", 2))
TWO_REQUIRED = _sig("two", ArgSpec("pairs", REQUIRED), ArgSpec("theme", REQUIRED))

SIGS = MappingProxyType({sig.name: sig for sig in (PROBE, BARE, LANTERN_MEMORY, STARGAZING,
                                                    TWO_REQUIRED)})
TWO = MappingProxyType({sig.name: sig for sig in (LANTERN_MEMORY, STARGAZING)})
FILLER = MappingProxyType({name: _sig(name) for name in (
    "archery", "bonsai", "calligraphy", "dumplings", "embers", "fishing", "goldfish",
    "haiku", "ikebana", "juggling", "kites")})

__all__ = ["FILLER", "SIGS", "TWO"]
