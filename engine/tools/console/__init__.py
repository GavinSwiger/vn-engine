"""F40 developer console (``specs/F40-dev-console``). Dev runs only: packaged builds leave
``engine/tools/`` out, and only ``engine/__main__.py`` hands the console to the App
(``install_console``, through ``bootstrap.launch``'s ``console`` factory)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.tools.console.console import DevConsole


def install_console(app: "App") -> "DevConsole":
    """The factory ``__main__`` passes in: the ``DevConsole`` for ``app.console``."""
    from engine.tools.console.console import DevConsole

    return DevConsole(app)


__all__ = ["install_console"]
