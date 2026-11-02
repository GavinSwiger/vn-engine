"""AC-F12-43's subprocess (audit spy A, F03 ``06`` §0.5): write every default-tier input of
the hostile manifest into a game folder of its own, then, with an audit hook installed, read
each one the way a launch does (``app/persistence.py``'s ``open_for_launch``, every
``ReadJob`` step) and print what the hook saw as JSON.

Run as ``python -m tests.persist.audit_read`` from the repository root. Audit hooks can't
be removed, so this is a process of its own. Writing the inputs, importing every module, and
one warm-up read of a good file happen before the hook ("after setup").
"""

import json
import os
import sys
import tempfile
from pathlib import Path

WATCHED = ("exec", "compile", "import", "open", "os.system", "subprocess.Popen")


def main() -> int:
    from engine.app.persistence import open_for_launch
    from tests.persist import gen_hostile
    from tests.persist.gen_hostile import HOSTILE, Sparse

    rows = [row for row in gen_hostile.load_manifest() if row["tier"] == "default"]
    events: list[list[str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        games: list[tuple[str, Path, dict]] = []
        for n, row in enumerate(rows):
            game = base / f"g{n}"
            folder = game / "persistent"
            folder.mkdir(parents=True)
            target = folder / "persistent.json"
            content = (HOSTILE / row["file"]).read_bytes() if "file" in row \
                else gen_hostile.build(row)
            if isinstance(content, Sparse):
                with open(target, "wb") as f:
                    f.truncate(content.size)
            else:
                target.write_bytes(content)
            games.append((row["id"], game, row))
        warm = base / "warm"
        (warm / "persistent").mkdir(parents=True)
        (warm / "persistent" / "persistent.json").write_bytes(gen_hostile.dumps(gen_hostile.GOOD))
        open_for_launch(None, game_root=warm, release=False, app_id=None).run()
        current = ["-"]
        allowed = [""]

        def hook(event: str, args: tuple) -> None:
            if current[0] == "-" or event not in WATCHED:
                return
            detail = ""
            if event == "open" and args:
                path = args[0]
                if isinstance(path, int):
                    return                           # an fd already opened inside the folder
                full = os.path.abspath(os.fsdecode(path))
                if os.path.normcase(full).startswith(os.path.normcase(allowed[0])):
                    return
                detail = "outside"
            elif event == "exec" and args:
                detail = getattr(args[0], "co_filename", type(args[0]).__name__)
            elif event == "compile" and len(args) > 1:
                detail = str(args[1])
            elif args:
                detail = str(args[0])
            events.append([current[0], event, detail])

        sys.addaudithook(hook)
        outcomes = {}
        for row_id, game, row in games:
            old_digits = sys.get_int_max_str_digits()
            if "max_str_digits" in row:
                sys.set_int_max_str_digits(row["max_str_digits"])
            allowed[0] = str(game / "persistent") + os.sep
            current[0] = row_id
            try:
                launch = open_for_launch(None, game_root=game, release=False, app_id=None)
                launch.run()
                outcomes[row_id] = launch.mode.value
            finally:
                current[0] = "-"
                sys.set_int_max_str_digits(old_digits)
    print(json.dumps({"rows": len(games), "events": events, "outcomes": outcomes}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
