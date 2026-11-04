"""Starts ``engine.tools.assistant.mcp.serve`` the way ``python -P -m engine assist-mcp``
will (W1 adds that command): ``python -P -m tests.tools.assistant.mcp_harness GAME
[--read-only] [--no-launch] [--import-print]``, with ``PYTHONPATH`` the repository.

``--import-print`` is AB-07's import-time ``print`` row: a module the server imports while
it starts prints to stdout as it is imported, which must land on stderr."""

import importlib.abc
import sys
from pathlib import Path

NOISE = '{"jsonrpc":"2.0","id":1,"result":{"forged":true}}'


class _Noisy(importlib.abc.MetaPathFinder):
    """Prints ``NOISE`` when the tool layer is imported, then finds nothing itself."""

    def find_spec(self, name, path=None, target=None):
        if name == "engine.tools.assistant.tools":
            print(NOISE)
        return None


def main(argv: list[str]) -> int:
    flags = {arg for arg in argv if arg.startswith("--")}
    game = next(arg for arg in argv if not arg.startswith("--"))
    if "--import-print" in flags:
        sys.meta_path.insert(0, _Noisy())
    from engine.tools.assistant.mcp import serve
    return serve(Path(game), read_only="--read-only" in flags,
                 launch="--no-launch" not in flags)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
