"""No identity queries; home lookups in two modules; the clipboard only written by the error
screen: AC-F01-111 and the AST part of AC-F01-153 (SEC-F01-12, SEC-F01-19).

F30 (SEC-F30-01, AC-F30-03): the one allowed identity call is ``getpass.getuser`` in
``meta/username.py`` (``IDENTITY_ALLOWED``), the player's opt-in name. This module and F01's
``test_runtime_identity_is_not_reported`` are the only tests that may read the real name
(SEC-F30-11), so it doesn't use F30's name guard."""

import ast
import getpass
import platform
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "engine"
HOME_MODULES = {"core/paths.py", "core/logsetup.py"}
CLIPBOARD_MODULE = "ui/builtin/error.py"
# F40 (04 §7.6, SEC-F40-12): the dev console's Ctrl+V is the one clipboard read. It lives
# under ``engine/tools/``, which packaged builds leave out, and keeps one cleaned line.
CLIPBOARD_READER = "tools/console/panel.py"
# F30 (SEC-F30-01 (a)): the one identity call allowed, and where.
IDENTITY_ALLOWED = {"meta/username.py": ("getpass", "getuser")}

IDENTITY_CALLS = {("getpass", "getuser"), ("os", "getlogin"), ("platform", "node"),
                  ("platform", "uname"), ("os", "uname"), ("socket", "gethostname"),
                  ("socket", "getfqdn"), ("pwd", "getpwuid"), ("pwd", "getpwnam")}
IDENTITY_STRINGS = {"GetUserNameW", "GetComputerNameW", "GetUserNameExW"}
IDENTITY_MODULES = {"pwd"}                       # F30 SEC-F30-01 (c): no GECOS full name
IDENTITY_ENV = {"USER", "USERNAME", "LOGNAME", "COMPUTERNAME", "HOSTNAME", "USERDOMAIN"}
HOME_ENV = {"HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}"
    return ""


def env_key(node: ast.AST) -> str | None:
    """The variable name read by os.environ[...], os.environ.get(...), or os.getenv(...)."""
    if isinstance(node, ast.Subscript) and dotted(node.value) == "os.environ":
        key = node.slice
    elif isinstance(node, ast.Call) and dotted(node.func) in ("os.environ.get", "os.getenv",
                                                              "environ.get", "getenv"):
        key = node.args[0] if node.args else None
    else:
        return None
    return key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None


def findings(path: Path) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, list[int]] = {}

    def add(kind: str, node: ast.AST) -> None:
        found.setdefault(kind, []).append(getattr(node, "lineno", 0))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in IDENTITY_MODULES for alias in node.names):
                add("identity", node)
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in IDENTITY_MODULES:
                add("identity", node)
            for alias in node.names:
                if (node.module, alias.name) in IDENTITY_CALLS:
                    add("identity", node)
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            pair = tuple(name.rsplit(".", 1)[-2:])
            if pair in IDENTITY_CALLS:
                add("identity", node)
                add("call:" + ".".join(pair), node)
            if name in ("Path.home", "pathlib.Path.home", "os.path.expanduser") \
                    or name.endswith(".expanduser") or name.endswith("home_dir") \
                    or name == "expanduser":
                add("home", node)
            if (name == "str" or name.rsplit(".", 1)[-1] in LOG_METHODS) and any(
                    dotted(arg) == "os.environ" for arg in node.args):
                add("environ-output", node)
        if isinstance(node, ast.Attribute):
            if node.attr in IDENTITY_STRINGS:
                add("identity", node)
            if node.attr in ("get", "get_text", "get_types") and dotted(node.value).endswith("scrap"):
                add("clipboard-read", node)
            if node.attr == "put_text" and dotted(node.value).endswith("scrap"):
                add("clipboard-write", node)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and any(s in node.value for s in IDENTITY_STRINGS):
            add("identity", node)
        key = env_key(node)
        if key in IDENTITY_ENV:
            add("identity", node)
        if key in HOME_ENV:
            add("home", node)
    return found


def engine_findings() -> dict[str, dict[str, list[int]]]:
    return {path.relative_to(ENGINE).as_posix(): f for path in sorted(ENGINE.rglob("*.py"))
            if (f := findings(path))}


def _allowed_lines(path: str, found: dict[str, list[int]]) -> set[int]:
    pair = IDENTITY_ALLOWED.get(path)
    return set(found.get("call:" + ".".join(pair), ())) if pair else set()


def test_no_identity_queries_anywhere():
    bad = {path: lines for path, f in engine_findings().items() if "identity" in f
           if (lines := sorted(set(f["identity"]) - _allowed_lines(path, f)))}
    assert bad == {}


def test_ac_f30_03_one_reader_one_importer():
    """AC-F30-03 (privacy half; the import rows are in ``test_import_rules.py``).
    (a) ``getpass.getuser`` is called in exactly ``meta/username.py``, once, and every
    other identity query (``IDENTITY_CALLS``, ``os.getlogin``, ``pwd``, ``GetUserNameExW``)
    is found nowhere, ``meta/`` included; (b) that module imports only ``getpass``,
    ``unicodedata``, ``typing``, and ``engine.core`` and never names the environment or a
    home folder; (c) the minigame kit and the F23 plugin context expose nothing about the
    name, the crash, or the window title."""
    found = engine_findings()
    callers = {path: f["call:getpass.getuser"] for path, f in found.items()
               if "call:getpass.getuser" in f}
    assert {p: len(lines) for p, lines in callers.items()} == {"meta/username.py": 1}
    assert {path: f["identity"] for path, f in found.items() if "identity" in f
            and set(f["identity"]) - _allowed_lines(path, f)} == {}

    source = (ENGINE / "meta" / "username.py").read_text(encoding="utf-8")
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    assert all(name in ("getpass", "unicodedata", "typing") or name.startswith("engine.core.")
               for name in imports), imports
    assert [w for w in ("environ", "getenv", "home") if w in source.lower()] == []
    for other in sorted((ENGINE / "meta").glob("*.py")):     # no second reader in meta/
        if other.name != "username.py":
            assert "getpass" not in other.read_text(encoding="utf-8"), other

    import engine.minigames.api as api
    from engine.minigames.context import Context

    words = ("username", "login", "crash", "window_title")
    exposed = set(dir(api)) | set(dir(Context))
    assert [a for a in exposed if any(w in a.lower() for w in words)] == []


def test_os_environ_is_never_logged_or_stringified():
    bad = {path: f["environ-output"] for path, f in engine_findings().items()
           if "environ-output" in f}
    assert bad == {}


def test_home_lookups_only_in_paths_and_logsetup():
    bad = {path: f["home"] for path, f in engine_findings().items()
           if "home" in f and path not in HOME_MODULES}
    assert bad == {}


def test_clipboard_is_never_read_and_only_written_by_the_error_screen():
    found = engine_findings()
    readers = {p: f["clipboard-read"] for p, f in found.items() if "clipboard-read" in f}
    assert set(readers) <= {CLIPBOARD_READER}                   # F40: the dev console only
    assert len(readers.get(CLIPBOARD_READER, ())) <= 1
    writers = {p for p, f in found.items() if "clipboard-write" in f}
    assert writers == {CLIPBOARD_MODULE}


@pytest.mark.parametrize("source, kind", [
    ("import getpass\ngetpass.getuser()\n", "identity"),
    ("import os\nos.getlogin()\n", "identity"),
    ("import pwd\n", "identity"),
    ("from pwd import getpwnam\n", "identity"),
    ("name = 'GetUserNameExW'\n", "identity"),
    ("from socket import gethostname\n", "identity"),
    ("import os\nos.environ.get('USERNAME')\n", "identity"),
    ("import os\nos.getenv('COMPUTERNAME')\n", "identity"),
    ("import os\nx = os.environ['HOSTNAME']\n", "identity"),
    ("name = 'GetUserNameW'\n", "identity"),
    ("from pathlib import Path\nPath.home()\n", "home"),
    ("import os\nos.path.expanduser('~')\n", "home"),
    ("import os\nos.environ.get('USERPROFILE')\n", "home"),
    ("from engine.core.paths import home_dir\nhome_dir()\n", "home"),
    ("import os, logging\nlogging.getLogger().info(os.environ)\n", "environ-output"),
    ("import pygame\npygame.scrap.get_text()\n", "clipboard-read"),
    ("import pygame\npygame.scrap.put_text('x')\n", "clipboard-write"),
])
def test_scanner_detects(tmp_path, source, kind):
    path = tmp_path / "x.py"
    path.write_text(source, encoding="utf-8")
    assert kind in findings(path)


def test_runtime_identity_is_not_reported():
    from engine.app import bootstrap
    from engine.app.platform import os_description

    node = platform.node()
    user = getpass.getuser()
    for text in (os_description(), bootstrap._header_build_line(release=False)):
        if node:
            assert node not in text
        assert user not in text


# --- F31 (TR-F31-02, SEC-F31-02; AC-F31-26 privacy half) --------------------------------

# The three meta files modules: changes only as writer jobs, reads only through ``safefile``
# or ``GamePaths``. Rows for modules a later build step adds apply once the file exists.
META_MODULES = ("meta/files.py", "runtime/metafiles.py", "app/metafiles.py")
META_OS_ALLOWED = {"meta/files.py": {"os.lstat", "os.path.realpath"}}
META_BANNED_IMPORTS = {"shutil", "subprocess", "webbrowser", "importlib", "ctypes"}
META_BANNED_CALLS = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "unlink",
                     "rmdir", "mkdir", "touch", "rename", "iterdir", "glob", "rglob", "chmod",
                     "symlink_to", "hardlink_to"}


def meta_module_findings(source: str, allowed_os: set[str]) -> list[str]:
    """Each banned name in ``source`` as ``"<line>: <what>"`` (06 AC-F31-26)."""
    tree = ast.parse(source)
    out: list[str] = []
    os_names: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [f"{node.lineno}: import {a.name}" for a in node.names
                    if a.name.split(".")[0] in META_BANNED_IMPORTS]
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root == "os" or root in META_BANNED_IMPORTS:
                out.append(f"{node.lineno}: from {node.module} import")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                out.append(f"{node.lineno}: open()")
            elif isinstance(func, ast.Attribute):
                if func.attr in META_BANNED_CALLS:
                    out.append(f"{node.lineno}: .{func.attr}()")
                elif func.attr == "replace" and len(node.args) + len(node.keywords) == 1:
                    out.append(f"{node.lineno}: one-argument .replace()")
        if isinstance(node, ast.Attribute) and dotted(node).startswith("os."):
            os_names.setdefault(dotted(node), node.lineno)
    for name, line in os_names.items():
        if any(other.startswith(name + ".") for other in os_names):
            continue                                     # ``os.path`` inside ``os.path.x``
        if name not in allowed_os:
            out.append(f"{line}: {name}")
    return sorted(out)


def test_ac_f31_26_meta_modules_make_no_direct_file_calls():
    found = {ref: problems for ref in META_MODULES if (ENGINE / ref).exists()
             if (problems := meta_module_findings((ENGINE / ref).read_text(encoding="utf-8"),
                                                  META_OS_ALLOWED.get(ref, set())))}
    assert found == {}
    assert (ENGINE / "meta" / "files.py").exists()
    bad = ("import os, shutil\nfrom os import remove\nopen('x')\np.unlink()\n"
           "p.replace(q)\nos.replace(a, b)\nos.path.realpath(x)\nos.lstat(x)\n"
           "s.replace('a', 'b')\n")
    assert meta_module_findings(bad, {"os.lstat"}) == [
        "1: import shutil", "2: from os import", "3: open()", "4: .unlink()",
        "5: one-argument .replace()", "6: os.replace", "7: os.path.realpath"]
