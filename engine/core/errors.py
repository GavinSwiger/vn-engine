"""Engine exception types.

Why this module exists: startup, config, and asset code must tell apart errors an author or
player can fix (shown on the error screen without a stack trace) from engine bugs, and the
asset errors must carry only the reference as written, never a resolved path
(SEC-F01-03). Later features subclass ``UserFacingError`` (F02 parse errors, F03 script
errors), so its ``format()`` is a shared contract.
"""

from engine.core.constants import MB
from engine.core.redact import echo


class EngineError(Exception):
    """Base for engine-raised errors."""


class UserFacingError(EngineError):
    """An error an author or player can fix. Shown on the error screen without a stack
    trace. F02 (parse errors) and F03 (script runtime errors) subclass this. Its text is
    redacted and escaped by the ErrorScreen and the log formatter, never trusted as safe."""

    def __init__(self, message: str, *, file: str | None = None,
                 line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.file = file
        self.line = line
        self.column = column

    def format(self) -> str:
        """'config.toml, line 4, column 9: <message>' (omits parts that are None).

        The file is never named twice (implementation note I-2): when there is no line, a
        message that already starts with the file name is returned as is, so
        ``ConfigError("config.toml is larger than 1 MB. …", file="config.toml")`` formats
        as ``config.toml is larger than 1 MB. …``. Otherwise ``<file>: <message>``.
        """
        if self.line is not None:
            where = f"line {self.line}" if not self.file else f"{self.file}, line {self.line}"
            if self.column is not None:
                where += f", column {self.column}"
            return f"{where}: {self.message}"
        if self.file and not self.message.startswith(self.file):
            return f"{self.file}: {self.message}"
        return self.message


class ConfigError(UserFacingError):
    """A problem in ``config.toml``: unreadable file, syntax error, or an invalid value."""


class ConfigErrorGroup(UserFacingError):
    """Every ``ConfigError`` of one load, shown together on the error screen (§7.1 step 8,
    PR-F01-12). Each error is logged as its own record; only the screen joins them."""

    def __init__(self, errors: list[ConfigError]) -> None:
        self.errors = list(errors)
        super().__init__("\n\n".join(error.format() for error in self.errors))

    def format(self) -> str:
        """Each error's ``format()``, joined by blank lines."""
        return self.message


class AssetRefError(UserFacingError):
    """A reference that breaks a PR-F01-55 rule or leaves the game folder.
    message == f'Asset path "{echo(ref)}" is not allowed: {reason}'. Never contains a
    resolved target or an absolute path (SEC-F01-03)."""

    def __init__(self, ref: str, reason: str) -> None:
        super().__init__(f'Asset path "{echo(ref)}" is not allowed: {reason}')
        self.ref = ref
        self.reason = reason


class AssetMissing(EngineError):
    """The reference is valid but names nothing in the game folder (or differs only in
    letter case, in which case ``suggestion`` holds the correctly cased reference)."""

    def __init__(self, ref: str, suggestion: str | None) -> None:
        text = f"{echo(ref)} not found"
        if suggestion is not None:
            text += f" — did you mean {echo(suggestion)}?"
        super().__init__(text)
        self.ref = ref
        self.suggestion = suggestion


class AssetNotFile(EngineError):
    """The reference names a folder, FIFO, device, … It is never opened."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"{echo(ref)} is not a file")
        self.ref = ref


class AssetTooLarge(EngineError):
    """The file is larger than the reader's ``max_bytes``."""

    def __init__(self, ref: str, max_bytes: int) -> None:
        limit = f"{max_bytes // MB} MB" if max_bytes >= MB and max_bytes % MB == 0 \
            else f"{max_bytes:,} bytes"
        super().__init__(f"{echo(ref)} is larger than {limit}")
        self.ref = ref
        self.max_bytes = max_bytes


class AssetUnreadable(EngineError):
    """An ``OSError`` while opening or reading the file. The OS text is dropped, because
    it can quote absolute paths (SEC-F01-03, SEC-F01-10)."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"could not read {echo(ref)}")
        self.ref = ref
