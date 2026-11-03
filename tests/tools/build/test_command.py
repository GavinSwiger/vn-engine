"""F42 P5: the build's step machine with fake check and packer children (AC-F42-02, -16, -19,
-21, -33). Real PyInstaller builds are P8's."""

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.core.editorreport import REPORT_MARKER
from engine.tools.build import checkstep, command, names, procs, tree
from engine.tools.build.licenses import Notice, Notices
from tests.core.test_safefile import link_dir

TITLE, VERSION, APP_ID = "Paper Lanterns", "0.1.0", "paper-lanterns"
FOLDER = f"{TITLE} {VERSION} Windows"
EXE = f"{TITLE}.exe"
GIB = 1 << 30


def report_line(event: str, **fields) -> bytes:
    data = {"v": 1, "event": event, **fields}
    return REPORT_MARKER + json.dumps(data, separators=(",", ":")).encode("ascii")


def problem(severity: str, text: str, source: str = "load") -> dict:
    return {"severity": severity, "code": "E1" if severity == "error" else "W1",
            "source": source, "text": text, "file": "script/start.vns", "line": 3,
            "column": None}


CLEAN_CHECK = [report_line("problems", items=[problem("warning", "unused image")]),
               report_line("names", kind="label", items=[["start", "script/start.vns", 1]]),
               report_line("done", loaded=True, problems=1, seconds=0.1)]


class FakeProc:
    pid = 4242

    def __init__(self, lines: list[bytes], code: int) -> None:
        self.stdout = io.BytesIO(b"".join(line + b"\n" for line in lines))
        self.returncode = code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class FakeChildren:
    """``popen`` for the check (``check`` lines) and the packer (writes ``dist/app``)."""

    def __init__(self, check=None, pack_code=0, pack_lines=(), on_pack=None) -> None:
        self.check = CLEAN_CHECK if check is None else check
        self.pack_code = pack_code
        self.pack_lines = list(pack_lines)
        self.on_pack = on_pack
        self.argvs: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.argvs.append(argv)
        if "check" in argv:
            return FakeProc(self.check, 0)
        dist = Path(argv[argv.index("--distpath") + 1])
        if self.pack_code == 0:
            app = dist / "app"
            (app / "_internal").mkdir(parents=True)
            (app / EXE).write_bytes(b"MZ fake exe")
            (app / "_internal" / "python312.dll").write_bytes(b"dll")
        if self.on_pack is not None:
            self.on_pack(argv)
        staging = str(dist.parent).encode()
        return FakeProc([line.replace(b"{staging}", staging) for line in self.pack_lines],
                        self.pack_code)


def fake_deps(children: FakeChildren, **over) -> command.BuildDeps:
    values = dict(
        popen=children,
        tool_status=lambda: procs.ToolStatus(None, procs.PYINSTALLER_VERSION),
        disk_free=lambda path: 100 * GIB,
        kill_tree=lambda proc: None,
        make_icon=lambda root, ref: b"ICO",
        collect_notices=lambda dirs: Notices((Notice("vn-engine.txt", b"x\r\n"),)),
        now=lambda: datetime(2026, 11, 2, tzinfo=timezone.utc))
    values.update(over)
    return command.BuildDeps(**values)


def make_game(root: Path, config: str | None = None) -> Path:
    (root / "script").mkdir(parents=True)
    (root / "script" / "start.vns").write_text("label start:\n    'Hi.'\n", encoding="utf-8")
    (root / "saves").mkdir()
    (root / "saves" / "1.save").write_bytes(b"save")
    if config is None:
        config = f'[game]\ntitle = "{TITLE}"\nversion = "{VERSION}"\nid = "{APP_ID}"\n'
    (root / "config.toml").write_text(config, encoding="utf-8")
    return root


@pytest.fixture
def game(tmp_path) -> Path:
    return make_game(tmp_path / "lanterns")


def run(game: Path, out: Path | None, deps, *, report=False, **options):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = command.build_command(game, out=out, report=report, deps=deps, stdout=stdout,
                                 stderr=stderr, **options)
    return code, stdout.getvalue(), stderr.getvalue()


def events(text: str) -> list[dict]:
    marker = REPORT_MARKER.decode("ascii")
    return [json.loads(line[len(marker):]) for line in text.splitlines()
            if line.startswith(marker)]


def listing(folder: Path) -> dict[str, bytes | None]:
    return {p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in sorted(folder.rglob("*"))}


def test_ac_f42_02_exit_codes_and_cli_lines(game, tmp_path):
    out = tmp_path / "builds"
    children = FakeChildren()
    code, stdout, stderr = run(game, None, fake_deps(children), zip=True)
    assert code == command.EXIT_BUILT, stderr
    lines = stdout.splitlines()
    assert lines[0] == f'Building "{TITLE}" {VERSION} for Windows (64-bit)'
    assert "Step 1 of 6: Checking your game" in lines
    assert "Step 2 of 6: Copying the game folder (2 files, " in stdout
    assert "Step 6 of 6: Finishing up" in lines
    assert "script/start.vns:3: warning W1 unused image" in lines    # the check, printed
    assert "Your game is built." in lines
    assert f"Built: {out / FOLDER} (" in stdout and f"Zip: {out / (FOLDER + '.zip')} (" in stdout
    assert "Built with 1 warning. They're listed above." in lines
    assert "saves — test-run data from your PC; players get their own" in stdout
    built = out / FOLDER
    assert (built / EXE).is_file() and (built / "game" / "config.toml").is_file()
    assert not (built / "game" / "saves").exists()
    assert (built / "README.txt").read_bytes().startswith(f"{TITLE} {VERSION}\r\n".encode())
    marker = tree.parse_marker((built / "_internal" / "vn-build.json").read_bytes())
    assert marker["id"] == APP_ID and marker["built"] == "2026-11-02T00:00:00Z"
    assert tree.is_earlier_build(built) and tree.zip_is_earlier_build(
        out / f"{FOLDER}.zip", FOLDER)
    # Children: argument lists; the packer's argv holds no game-folder path.
    check_argv, pack_argv = children.argvs
    assert check_argv[-3:] == ["check", str(game.resolve()), "--report-to-editor"]
    assert not any(str(game) in part for part in pack_argv)

    # 1: not built, with the Can't build / Fix lines on stderr.
    code, stdout, stderr = run(game, out, fake_deps(FakeChildren()))
    assert code == command.EXIT_NOT_BUILT
    assert stderr.splitlines() == [
        f'Can\'t build: An earlier build "{FOLDER}" is already in builds.',
        "Fix: Add --replace to replace it, or change the version."]

    # 2: GAME_DIR isn't a game folder.
    code, _, stderr = run(tmp_path / "missing", out, fake_deps(FakeChildren()))
    assert code == command.EXIT_USAGE and stderr.startswith("build: ")


def test_ac_f42_16_no_game_id_writes_nothing(tmp_path):
    game = make_game(tmp_path / "lanterns",
                     f'[game]\ntitle = "{TITLE}"\nversion = "{VERSION}"\n# id = ""\n')
    out = tmp_path / "builds"
    children = FakeChildren()
    code, stdout, _ = run(game, out, fake_deps(children), report=True, zip=True)
    assert code == 1
    assert events(stdout) == [{"v": 1, "event": "build_failed", "code": "B_NO_ID",
                               "values": {"slug": APP_ID}, "details": []}]
    assert not out.exists() and children.argvs == []
    code, _, stderr = run(game, out, fake_deps(FakeChildren()))
    assert stderr.splitlines() == [
        "Can't build: config.toml has no Game ID ([game] id).",
        f'Fix: Add one in Build game…, or add a line under [game]: id = "{APP_ID}"']


def _fail_copy(*args, **kwargs):
    raise tree.texts.BuildStopped("B_COPY_FAILED", ref="script/start.vns")


def _in_use(*args, **kwargs):
    raise tree.texts.BuildStopped("B_IN_USE")


def _bad_zip(folder, target):
    target.write_bytes(b"partial")
    raise OSError("disk full")


FAILURES = {
    "check": ("B_ERRORS", {"check": [report_line("problems", items=[problem("error", "bad")]),
                                     report_line("done", loaded=True, problems=1, seconds=0)]},
              {}),
    "check crashed": ("B_CRASHED", {"check": [b"Traceback (most recent call last):"]}, {}),
    "copy": ("B_COPY_FAILED", {}, {"copy": _fail_copy}),
    "pack": ("B_PACK_FAILED",
             {"pack_code": 1, "pack_lines": [b"ERROR: no module in {staging}"]}, {}),
    "notices": ("B_PACK_FAILED", {}, {"notices": ("SDL9.dll",)}),
    "zip": ("B_CRASHED", {}, {"write_zip": _bad_zip}),
    "finish": ("B_IN_USE", {}, {"install": _in_use}),
}


@pytest.mark.parametrize("where", list(FAILURES))
def test_ac_f42_19_a_failure_at_each_step_leaves_save_to_unchanged(game, tmp_path,
                                                                   monkeypatch, where):
    out = tmp_path / "builds"
    out.mkdir()
    (out / "notes.txt").write_bytes(b"mine")
    before = listing(out)
    key, child_options, patches = FAILURES[where]
    killed = []
    over = {"kill_tree": killed.append}
    if "copy" in patches:
        monkeypatch.setattr(tree, "copy_game", patches["copy"])
    if "install" in patches:
        monkeypatch.setattr(tree, "install_build", patches["install"])
    if "notices" in patches:
        over["collect_notices"] = lambda dirs: Notices((), patches["notices"])
    if "write_zip" in patches:
        over["write_zip"] = patches["write_zip"]
    seen = {}
    children = FakeChildren(**child_options,
                            on_pack=lambda argv: seen.setdefault("staging", Path(
                                argv[argv.index("--distpath") + 1]).parent))
    code, stdout, _ = run(game, out, fake_deps(children, **over), report=True, zip=True)
    assert code == 1
    failed = events(stdout)[-1]
    assert failed["event"] == "build_failed" and failed["code"] == key
    assert listing(out) == before                      # no staging, nothing new
    if where == "pack":
        staging = seen["staging"]
        assert failed["details"] == ["ERROR: no module in <staging>"]
        assert str(staging) not in stdout
    if where == "notices":
        assert failed["details"] == [
            "No license notice for SDL9.dll: add one to engine/tools/build/notices/."]
    steps = [e for e in events(stdout) if e["event"] == "build_step"]
    staged = [e["staging"] for e in steps if e["staging"]]
    if where not in ("check", "check crashed"):
        assert len(staged) == 1 and tree.STAGING_RE.fullmatch(staged[0])


def test_ac_f42_21_earlier_build_replaced_only_with_replace(game, tmp_path, monkeypatch):
    out = tmp_path / "builds"
    assert run(game, out, fake_deps(FakeChildren()), zip=True)[0] == 0
    old_marker = (out / FOLDER / "_internal" / "vn-build.json").read_bytes()

    # Without --replace: B_EXISTS, the earlier build untouched.
    later = fake_deps(FakeChildren(), now=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc))
    code, stdout, _ = run(game, out, later, report=True, zip=True)
    assert code == 1 and events(stdout)[-1]["code"] == "B_EXISTS"
    assert (out / FOLDER / "_internal" / "vn-build.json").read_bytes() == old_marker

    # With --replace: replaced, and the old one deleted only after the new one is in place.
    order = []
    real_install = tree.install_build

    def install(*args, **kwargs):
        order.append(("before", tree.is_earlier_build(out / FOLDER)))
        return real_install(*args, **kwargs)

    monkeypatch.setattr(tree, "install_build", install)
    code, stdout, _ = run(game, out, later, report=True, zip=True, replace=True)
    assert code == 0 and order == [("before", True)]
    marker = tree.parse_marker((out / FOLDER / "_internal" / "vn-build.json").read_bytes())
    assert marker["built"].startswith("2027")
    assert sorted(os.listdir(out)) == [FOLDER, f"{FOLDER}.zip"]       # no aside, no staging
    monkeypatch.setattr(tree, "install_build", real_install)

    # An unmarked folder at that name: B_NAME_TAKEN even with --replace.
    other = tmp_path / "other"
    (other / FOLDER).mkdir(parents=True)
    (other / FOLDER / "keep.txt").write_bytes(b"keep")
    code, stdout, _ = run(game, other, later, report=True, replace=True)
    assert events(stdout)[-1]["code"] == "B_NAME_TAKEN"
    assert (other / FOLDER / "keep.txt").read_bytes() == b"keep"

    # A link (junction) at that name to a real earlier build: not followed, not replaced.
    linked = tmp_path / "linked"
    linked.mkdir()
    link_dir(linked / FOLDER, out / FOLDER)
    code, stdout, _ = run(game, linked, later, report=True, replace=True)
    assert events(stdout)[-1]["code"] == "B_NAME_TAKEN"
    assert tree.parse_marker((out / FOLDER / "_internal" / "vn-build.json").read_bytes())


def test_ac_f42_33_no_space_and_long_paths(game, tmp_path):
    out = tmp_path / "builds"
    deps = fake_deps(FakeChildren(), disk_free=lambda path: 150 * (1 << 20))
    code, stdout, _ = run(game, out, deps, report=True, zip=True)
    failed = events(stdout)[-1]
    assert code == 1 and failed["code"] == "B_NO_SPACE"
    assert failed["values"]["free"] == "150 MB" and failed["values"]["need"] == "200 MB"
    assert not out.exists()
    long_ref = "images/" + "a" * 150 + ".png"
    (game / "images").mkdir()
    (game / "images" / long_ref.split("/")[1]).write_bytes(b"\x89PNG")
    code, stdout, _ = run(game, out, fake_deps(FakeChildren()), report=True)
    done = events(stdout)[-1]
    assert code == 0 and done["event"] == "build_done"
    assert done["long_paths"] == 1 and done["long_path_example"] == long_ref
    assert done["folder"] == FOLDER and done["exe"] == EXE and done["zip"] is None
    assert done["warnings"] == 1 and done["left_out_total"] == 1
    code, stdout, _ = run(game, tmp_path / "cli", fake_deps(FakeChildren()))
    assert ("1 file paths are very long and may not unzip on some PCs. Shorten folder or "
            f"file names, like {long_ref}.") in stdout


def test_check_lines_are_relayed_unchanged_and_bad_lines_dropped(game, tmp_path):
    bad = REPORT_MARKER + b'{"v":1,"event":"problems","items":[{"severity":"boom"}]}'
    children = FakeChildren(check=[bad, b"noise", *CLEAN_CHECK])
    code, stdout, _ = run(game, tmp_path / "builds", fake_deps(children), report=True)
    assert code == 0
    raw = [line.encode("ascii") for line in stdout.splitlines()]
    assert CLEAN_CHECK[0] in raw and CLEAN_CHECK[2] in raw
    assert bad not in raw and CLEAN_CHECK[1] not in raw            # names aren't relayed
    assert checkstep.decode_line(bad) is None
    assert names.folder_name(TITLE, VERSION, APP_ID) == FOLDER
