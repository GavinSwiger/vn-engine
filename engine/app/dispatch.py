"""The story seam: ``StoryDriver`` and ``CommandRouter`` (F03 plugs in here).

Why this module exists: the runtime (F03's interpreter) and the presentation layer must
never call each other directly (invariant 5). Each frame the App asks the story driver for
the commands it produced (``pump``) and hands each one to the router, which calls the one
handler registered for that command type. Input goes back only through ``post``. F01
registers no commands; F04, F05, F08, … each register handlers for their own commands.
"""

from collections.abc import Callable
from typing import Any, Protocol

from engine.core.errors import EngineError


class UnhandledCommandError(EngineError):
    """A command reached the router with no handler for its type or any base type."""


class StoryDriver(Protocol):
    """Implemented by F03's interpreter adapter. pump() yields runtime → presentation
    commands; post() takes presentation → runtime events. Presentation never touches
    GameState (invariant 5); F03 must not expose a mutable GameState through App."""

    def post(self, event: object) -> None: ...

    def pump(self, max_commands: int = 256) -> list[object]: ...


class CommandRouter:
    """Exactly one handler per command type; dispatch follows the type's MRO."""

    def __init__(self) -> None:
        self._handlers: dict[type, Callable[[Any], None]] = {}

    def register(self, command_type: type, handler: Callable[[Any], None]) -> None:
        """Exactly one handler per type; a second registration raises ValueError."""
        if command_type in self._handlers:
            raise ValueError(f"A handler for {command_type.__name__} is already registered")
        self._handlers[command_type] = handler

    def unregister(self, command_type: type) -> None:
        self._handlers.pop(command_type, None)

    def dispatch(self, command: object) -> None:
        """type(command), then its MRO. No handler → UnhandledCommandError."""
        for klass in type(command).__mro__:
            handler = self._handlers.get(klass)
            if handler is not None:
                handler(command)
                return
        raise UnhandledCommandError(f"No handler for the command {type(command).__name__}")
