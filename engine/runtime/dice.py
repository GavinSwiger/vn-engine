"""``dice``: PCG32 and the author-facing front object (F03 ``04-technical.md`` §7.8).

Why this module exists: story randomness must replay after a load or rollback (invariant 7,
SR-F03-18), so the generator's whole state is one integer stored in ``GameState.dice``. It
is pure Python with masks: results depend only on the seed and the calls, never on the
clock, the OS, or the hash seed. The seed comes from ``app`` (the runtime reads no entropy).

``Pcg32`` is never reachable by name from author code. Authors see ``make_dice(core)``: an
object whose only public attributes are ``roll``, ``pick``, ``decimal``, and ``shuffle``.
"""

from engine.runtime.values import kind_words, register_kind

MASK32 = 0xFFFF_FFFF
MASK64 = 0xFFFF_FFFF_FFFF_FFFF
PCG_MULTIPLIER = 6364136223846793005
PCG_INCREMENT = 1442695040888963407     # the reference default increment

DICE_CALLS = ("decimal", "pick", "roll", "shuffle")   # dir() order


class Pcg32:
    """PCG32 XSH-RR with a 64-bit ``state`` and the fixed default increment.

    ``ready`` is False until a game starts: defines run at launch, before any seed, and a
    dice call there is E85k (``DiceNotReady``). The interpreter sets ``state`` and
    ``ready`` directly on restore."""

    __slots__ = ("state", "ready")

    def __init__(self, state: int = 0, *, ready: bool = False) -> None:
        self.state = state & MASK64
        self.ready = ready

    def seed(self, seed: int) -> None:
        """The reference ``pcg32_srandom_r(seed, ...)`` with the default increment; the
        generator is then ready. ``seed`` is an int, 0 <= seed < 2**64."""
        if type(seed) is not int or not 0 <= seed <= MASK64:
            raise ValueError("seed must be an int in 0 .. 2**64 - 1")
        self.state = 0
        self.next32()
        self.state = (self.state + seed) & MASK64
        self.next32()
        self.ready = True

    def next32(self) -> int:
        """The next raw 32-bit output."""
        old = self.state
        self.state = (old * PCG_MULTIPLIER + PCG_INCREMENT) & MASK64
        shifted = (((old >> 18) ^ old) >> 27) & MASK32
        rot = old >> 59
        return ((shifted >> rot) | (shifted << ((-rot) & 31))) & MASK32

    def below(self, n: int) -> int:
        """A uniform int in ``0 .. n - 1`` for any ``n >= 1``: concatenate
        ``ceil(n.bit_length() / 32)`` outputs, keep ``n.bit_length()`` bits, and retry while
        the result is ``>= n`` (unbiased)."""
        bits = n.bit_length()
        words = (bits + 31) // 32
        drop = 32 * words - bits
        while True:
            r = 0
            for _ in range(words):
                r = (r << 32) | self.next32()
            r >>= drop
            if r < n:
                return r

    def decimal(self) -> float:
        """A float in ``[0, 1)`` with 53 random bits, from two outputs."""
        a = self.next32()
        b = self.next32()
        return ((a >> 5) * 67108864 + (b >> 6)) / 9007199254740992.0


class DiceNotReady(Exception):
    """A ``dice`` call before a game started, e.g. in a define at launch (E85k)."""

    def __init__(self, call: str) -> None:
        super().__init__(f"dice.{call} was called before a game started")
        self.call = call


class DiceArgumentError(Exception):
    """Wrong values for a ``dice`` call (E85j). ``call`` is the call's name; ``form`` is
    one of ``count`` (``got`` = number of values given), ``whole`` (``value`` isn't an exact
    int), ``order`` (``value`` = ``(lo, hi)`` with lo > hi), ``empty`` (``pick`` of an empty
    list), ``list`` (``value`` isn't a list). The phase-2 messages are built from these
    fields; ``kind`` is the value's kind in words (SR-F03-33)."""

    def __init__(self, call: str, form: str, *, value: object = None, got: int = 0) -> None:
        super().__init__(f"wrong values for dice.{call} ({form})")
        self.call = call
        self.form = form
        self.value = value
        self.got = got

    @property
    def kind(self) -> str:
        return kind_words(self.value)


class DiceFacade:
    """Base of every ``dice`` object; it has no public attributes of its own. Any other
    attribute read, set, or delete raises ``AttributeError(name=..., obj=...)`` (E85c), so
    ``$ dice.seed(1)`` and ``$ dice.state = 0`` change nothing."""

    __slots__ = ()

    def __getattr__(self, name: str):
        raise AttributeError(f"dice has no {name!r}", name=name, obj=self)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"dice has no {name!r}", name=name, obj=self)

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"dice has no {name!r}", name=name, obj=self)

    def __repr__(self) -> str:
        return "<dice>"


register_kind(DiceFacade, "the dice")


def make_dice(core: Pcg32) -> DiceFacade:
    """The author-facing ``dice`` (``G["dice"]``, SR-F03-19): four functions closing over
    ``core``. Arguments are taken as ``*args`` so a wrong count is E85j, not a Python
    error."""

    def ready(call: str) -> None:
        if not core.ready:
            raise DiceNotReady(call)

    def roll(*args):
        ready("roll")
        if len(args) != 2:
            raise DiceArgumentError("roll", "count", got=len(args))
        lo, hi = args
        for value in args:
            if type(value) is not int:
                raise DiceArgumentError("roll", "whole", value=value)
        if lo > hi:
            raise DiceArgumentError("roll", "order", value=(lo, hi))
        return lo + core.below(hi - lo + 1)

    def pick(*args):
        ready("pick")
        if len(args) != 1:
            raise DiceArgumentError("pick", "count", got=len(args))
        items = args[0]
        if type(items) is not list:
            raise DiceArgumentError("pick", "list", value=items)
        if not items:
            raise DiceArgumentError("pick", "empty", value=items)
        return items[core.below(len(items))]

    def decimal(*args):
        ready("decimal")
        if args:
            raise DiceArgumentError("decimal", "count", got=len(args))
        return core.decimal()

    def shuffle(*args):
        ready("shuffle")
        if len(args) != 1:
            raise DiceArgumentError("shuffle", "count", got=len(args))
        items = args[0]
        if type(items) is not list:
            raise DiceArgumentError("shuffle", "list", value=items)
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = core.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out

    calls = {"roll": roll, "pick": pick, "decimal": decimal, "shuffle": shuffle}
    namespace = {name: staticmethod(fn) for name, fn in calls.items()}
    namespace["__slots__"] = ()
    namespace["__module__"] = "dice"
    namespace["__qualname__"] = "dice"
    for name, fn in calls.items():
        fn.__qualname__ = f"dice.{name}"
    return type("dice", (DiceFacade,), namespace)()
