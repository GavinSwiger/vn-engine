"""The meta folder guard (F31 ``06`` §0.3, AC-F31-07): tests never touch the repository's
``game/characters/`` (or its ``game/files/`` originals).

``tests/conftest.py`` applies both halves for the whole suite:

- an autouse session fixture wraps ``MetaFolder.__init__`` and ``Writer.client`` so a root
  inside the real ``game/characters`` raises ``RealFolderTouched``, a ``BaseException`` that
  no ``except Exception`` in engine code can swallow;
- ``pytest_sessionstart`` / ``pytest_sessionfinish`` compare a ``snapshot`` of
  ``game/characters/`` and ``game/files/`` (exists, names, sizes, ``mtime_ns``) and fail the
  run on any difference.

Every helper that copies ``game/`` ignores ``characters`` (07 I-8), so a developer's own
``game/characters/`` never reaches a copy and changes a ``file exists`` answer.
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
REAL_META = REPO / "game" / "characters"
WATCHED = (REPO / "game" / "characters", REPO / "game" / "files")


class RealFolderTouched(BaseException):
    """A test built a ``MetaFolder`` or a writer client on the real ``game/characters``."""


def touches_real(root: object) -> bool:
    """Whether ``root`` is, or lies inside, the repository's ``game/characters``."""
    try:
        path = Path(root).resolve()                     # type: ignore[arg-type]
        return path == REAL_META.resolve() or path.is_relative_to(REAL_META.resolve())
    except (OSError, TypeError, ValueError, RuntimeError):
        return False


def snapshot(folders=WATCHED) -> dict[str, object]:
    """``{folder: None}`` when missing, else ``{relative name: (size, mtime_ns)}`` of every
    entry under it by ``lstat`` (links not followed)."""
    out: dict[str, object] = {}
    for folder in folders:
        try:
            os.lstat(folder)
        except OSError:
            out[str(folder)] = None
            continue
        entries: dict[str, tuple[int, int]] = {}
        for base, dirs, files in os.walk(folder, followlinks=False):
            for name in (*dirs, *files):
                path = Path(base) / name
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                entries[path.relative_to(folder).as_posix()] = (st.st_size, st.st_mtime_ns)
        out[str(folder)] = entries
    return out


def install(monkeypatch) -> None:
    """Wrap ``MetaFolder.__init__`` and ``Writer.client`` with the guard."""
    from engine.meta import files
    from engine.persist import writer

    init = files.MetaFolder.__init__
    client = writer.Writer.client

    def guarded_init(self, root, names):
        if touches_real(root):
            raise RealFolderTouched("a test built MetaFolder on the real game/characters")
        init(self, root, names)

    def guarded_client(self, owner, *, root, names):
        if touches_real(root):
            raise RealFolderTouched("a test registered a writer client on game/characters")
        return client(self, owner, root=root, names=names)

    monkeypatch.setattr(files.MetaFolder, "__init__", guarded_init)
    monkeypatch.setattr(writer.Writer, "client", guarded_client)
