"""ADR-0002 import rules, checked by an AST scan of ``engine/**``: AC-F01-49.

The table encodes all of ADR-0002, so packages added by later features are checked as soon
as they exist. Relative imports are resolved to absolute names. ``engine`` itself (the
version) and ``engine._bootcheck`` count as the entry-point layer: only ``app``, ``tools``,
as written, and the top-level entry modules may import them.

F44 (``07`` I-12, ADR-0008; AC-F44-33 (c)): ``engine/tools/editor`` imports only ``core``,
``script``, and itself, never pygame; ``engine/__main__.py`` may import ``engine.tools`` only
inside a function (the ``edit`` handler), so ``run`` never loads the editor.

F30 (``07`` I-1; AC-F30-03): only ``app`` imports ``meta`` (``tools`` doesn't either), and
``engine.meta.username``, the one opt-in OS identity query, only ``app/fourthwall.py``
(``MODULE_IMPORTERS``). F31 (TR-F31-01): ``engine.meta.files`` only ``app/metafiles.py``.
"""

import ast
from pathlib import Path

from tests.fakes.username import no_real_username  # noqa: F401  (F30 name guard, AC-F30-07)

REPO = Path(__file__).resolve().parent.parent

PACKAGES = ("core", "script", "runtime", "persist", "meta", "render", "audio", "ui",
            "minigames", "app", "tools")
ROOT_LAYER = "<entry>"                    # engine/__init__.py and engine/_bootcheck.py
MAY_IMPORT: dict[str, set[str]] = {
    "core": set(),
    "script": {"core"},
    "runtime": {"core", "script"},
    "persist": {"core", "script", "runtime"},
    "meta": {"core"},
    "render": {"core", "runtime"},
    "audio": {"core", "runtime"},
    "ui": {"core", "runtime", "render", "audio"},
    "minigames": {"core", "runtime", "render", "audio", "ui"},
    "app": set(PACKAGES) - {"tools"} | {ROOT_LAYER},
    "tools": set(PACKAGES) - {"meta"} | {ROOT_LAYER},             # F30 07 I-1
}
# Modules that only the listed files (relative to the repository) may import (F30 07 I-1).
MODULE_IMPORTERS: dict[str, set[str]] = {
    "engine.meta.username": {"engine/app/fourthwall.py"},
    "engine.meta.files": {"engine/app/metafiles.py"},             # F31 TR-F31-01
}
NO_PYGAME = {"core", "script", "runtime", "persist", "meta"}
# Top-level modules: engine/__init__.py imports nothing; engine/_bootcheck.py only the
# stdlib (and pygame, inside check_pygame); engine/__main__.py is an entry point.
TOP_LEVEL = {"__init__": set(), "_bootcheck": set(), "__main__": {"app", ROOT_LAYER}}
# Layers a top-level module may import only inside a function body (lazily).
LAZY_ONLY = {"__main__": {"tools"}}
# Sub-packages with a stricter row than their package (F44 I-12).
# F45 (04 §3, 07 O-2): tools/check.py, Studio's check child, imports core, script, and
# runtime only (no pygame, app, render, ui, audio, persist, meta, or minigames).
# F47 (04 §9): tools/helper.py, Studio's helper child, imports core, script, render, ui, and
# audio (and runtime, which they build on), never app, meta, minigames, persist, or
# runtime.interpreter (``SUBPACKAGE_BANNED``); unlike the other rows it may import pygame.
SUBPACKAGES: dict[tuple[str, str], set[str]] = {("tools", "editor"): {"core", "script"},
                                                ("tools", "check"): {"core", "script",
                                                                     "runtime"},
                                                ("tools", "helper"): {"core", "script",
                                                                      "runtime", "render",
                                                                      "ui", "audio"},
                                                ("tools", "build"): {"core", "script",
                                                                     ROOT_LAYER},
                                                # F40 (04 §3, 07 I-3): never meta, persist,
                                                # audio, minigames or another tools package.
                                                ("tools", "console"): {"core", "script",
                                                                       "runtime", "render",
                                                                       "ui", "app"}}
SUBPACKAGE_BANNED: dict[str, tuple[str, ...]] = {
    "engine.tools.helper": ("engine.runtime.interpreter",)}
PYGAME_SUBPACKAGES = {"engine.tools.helper", "engine.tools.console"}
# F42 (04 §3.4, 07 I-10): tools/build imports core, script, the stdlib and itself (and the
# engine version, for the build marker, like the tools row); pygame only
# in icon.py; never PyInstaller (it runs only as a child). tools/editor (Studio) may import
# only the five shared build modules, and those import only each other within tools/build.
PYGAME_FILES = {"engine/tools/build/icon.py"}
EXTERNAL_BANNED: dict[str, tuple[str, ...]] = {"engine.tools.build": ("PyInstaller",)}
BUILD_PACKAGE = "engine.tools.build"
SHARED_BUILD = frozenset({"names", "texts", "rules", "tree", "procs"})
SHARED_BUILD_USERS = {"engine.tools.editor"}
# F41 (04 §3; F43 07 I-9): tools/lint.py, the linter's rules, has tools/check.py's row; it
# never imports tools.check (check imports lint).
SUBPACKAGES[("tools", "lint")] = {"core", "script", "runtime"}
# Narrow sibling exceptions to the sub-package rule: importer → the one module it may load.
# F41 P3 (04 §3): the check child runs the linter's rules.
SUBPACKAGE_ALLOWED: dict[str, tuple[str, ...]] = {"engine.tools.check": ("engine.tools.lint",)}
# F48 (04 §3, 07 §2.2, I-2; AC-F48-01): tools/assistant imports core, script, itself, the
# pure editor modules 04 §3 names (and ``cleanup``, S4) and tools.build.procs; never tkinter,
# pygame, runtime, app, meta or tools.check, and the network modules only in ``providers/``.
# Outside engine/tools only ``__main__`` imports it, inside its ``assist-mcp`` handler
# (``LAZY_ONLY``); the other rows already refuse ``tools``.
ASSISTANT = "engine.tools.assistant"
ASSISTANT_EDITOR = ("checker", "document", "scenes", "scriptedit", "files", "config_help",
                    "assist", "dbmodel", "declarations", "cleanup",
                    "tomlpatch")           # 2026-11-04: propose_settings writes config.toml
SUBPACKAGES[("tools", "assistant")] = {"core", "script"}
SUBPACKAGE_ALLOWED[ASSISTANT] = (*(f"engine.tools.editor.{m}" for m in ASSISTANT_EDITOR),
                                 "engine.tools.build.procs")
NETWORK_MODULES = ("socket", "ssl", "http", "urllib")
EXTERNAL_BANNED[ASSISTANT] = ("tkinter", *NETWORK_MODULES)
# F48 W3/W4 (04 §3.2, §18 item 5): Studio's Tk modules for the assistant may import
# tools.assistant; no other editor module may (the assistant imports the pure editor modules,
# which stay Tk-free: test_f48_i2_the_server_closure_loads_no_tk_or_network).
ASSISTANT_TK_MODULES = ("aisettings", "assistpane", "assistwiring")
FILE_SIBLING_ALLOWED: dict[str, tuple[str, ...]] = {
    f"engine/tools/editor/{name}.py": (ASSISTANT,) for name in ASSISTANT_TK_MODULES}
# Files allowed one of their package's EXTERNAL_BANNED modules (prefix of the repo path).
EXTERNAL_ALLOWED: dict[str, tuple[str, ...]] = {
    "engine/tools/assistant/providers/": NETWORK_MODULES}


def _module_name(path: Path, engine_dir: Path) -> list[str]:
    parts = list(path.relative_to(engine_dir.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def _function_imports(tree: ast.AST) -> set[int]:
    """Line numbers of the import statements inside a function body."""
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    lines.add(inner.lineno)
    return lines


def _imports(tree: ast.AST, module: list[str], is_package: bool) -> list[tuple[int, str]]:
    """(line, absolute module name) for every import statement."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module if is_package else module[:-1]
                base = base[:len(base) - (node.level - 1)]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            if name == "engine":
                # "from engine import x": x may be a package or module of the engine.
                for alias in node.names:
                    found.append((node.lineno, f"engine.{alias.name}"))
            else:
                found.append((node.lineno, name))
    return found


def _module_targets(tree: ast.AST, module: list[str],
                    is_package: bool) -> list[tuple[int, str]]:
    """(line, absolute name) for every module an import statement may load, including
    ``from a.b import c`` as ``a.b.c`` (for ``MODULE_IMPORTERS``)."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module if is_package else module[:-1]
                base = base[:len(base) - (node.level - 1)]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            found.append((node.lineno, name))
            found.extend((node.lineno, f"{name}.{alias.name}") for alias in node.names)
    return found


def _layer(name: str) -> str | None:
    """The ADR-0002 package an absolute ``engine.*`` name belongs to (None: not engine)."""
    parts = name.split(".")
    if parts[0] != "engine":
        return None
    if len(parts) == 1 or parts[1] not in PACKAGES:
        return ROOT_LAYER                  # engine, engine.__version__, engine._bootcheck
    return parts[1]


def _build_modules(line: int, name: str,
                   targets: list[tuple[int, str]]) -> set[str] | None:
    """The ``tools/build`` modules an import of ``name`` on ``line`` loads (``from
    engine.tools.build import names`` → ``{"names"}``), or None when it isn't one."""
    if name.startswith(BUILD_PACKAGE + "."):
        return {name.split(".")[3]}
    if name != BUILD_PACKAGE:
        return None
    return {target.split(".")[3] for at, target in targets
            if at == line and target.startswith(BUILD_PACKAGE + ".")}


def _sibling_allowed(own_prefix: str, line: int, name: str,
                     targets: list[tuple[int, str]]) -> bool:
    """Whether ``own_prefix`` may import ``name`` (on ``line``) by ``SUBPACKAGE_ALLOWED``:
    ``from engine.tools.editor import files`` counts as ``engine.tools.editor.files``."""
    allowed = SUBPACKAGE_ALLOWED.get(own_prefix, ())

    def ok(target: str) -> bool:
        return any((target + ".").startswith(a + ".") for a in allowed)

    if ok(name):
        return True
    loaded = [t for at, t in targets if at == line and t.startswith(name + ".")]
    return bool(loaded) and all(ok(t) for t in loaded)


def _file_allowed(rel: str, name: str) -> bool:
    """``FILE_SIBLING_ALLOWED``: this one file may import ``name``."""
    return any((name + ".").startswith(a + ".") for a in FILE_SIBLING_ALLOWED.get(rel, ()))


def _external_banned(own_prefix: str | None, rel: str, top: str) -> bool:
    if not own_prefix or top not in EXTERNAL_BANNED.get(own_prefix, ()):
        return False
    return not any(rel.startswith(prefix) and top in modules
                   for prefix, modules in EXTERNAL_ALLOWED.items())


def scan(engine_dir: Path) -> list[str]:
    """Every ADR-0002 violation under ``engine_dir`` as ``"<file>:<line>: <message>"``."""
    violations = []
    for path in sorted(engine_dir.rglob("*.py")):
        module = _module_name(path, engine_dir)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(engine_dir.parent).as_posix()
        lazy: set[str] = set()
        own_prefix: str | None = None             # a sub-package may import only itself
        if len(module) >= 2 and module[1] in PACKAGES:
            package = module[1]
            allowed = MAY_IMPORT[package] | {package}
            if len(module) >= 3 and (package, module[2]) in SUBPACKAGES:
                allowed = SUBPACKAGES[(package, module[2])] | {package}
                own_prefix = ".".join(module[:3])
                package = own_prefix.removeprefix("engine.")
        else:
            package = None
            top = module[-1] if len(module) > 1 else "__init__"
            allowed = TOP_LEVEL.get(top, set())
            lazy = LAZY_ONLY.get(top, set())
        in_functions = _function_imports(tree)
        targets = _module_targets(tree, module, path.name == "__init__.py")
        # The modules of tools/build this file may import: any (its own child-only
        # modules), only the shared five (Studio, and the shared five themselves), or
        # none (every other file, by the sub-package rule).
        shared_only = own_prefix in SHARED_BUILD_USERS or (
            own_prefix == BUILD_PACKAGE and len(module) > 3 and module[3] in SHARED_BUILD)
        for line, name in _imports(tree, module, path.name == "__init__.py"):
            top = name.split(".")[0]
            if top == "pygame" and rel not in PYGAME_FILES and (
                    package in NO_PYGAME
                    or (own_prefix and own_prefix not in PYGAME_SUBPACKAGES)):
                violations.append(f"{rel}:{line}: {package} must not import pygame")
                continue
            if _external_banned(own_prefix, rel, top):
                violations.append(f"{rel}:{line}: {package} must not import {name}")
                continue
            layer = _layer(name)
            if layer is None:
                continue
            build = _build_modules(line, name, targets)
            if shared_only and build is not None:
                for extra in sorted(build - SHARED_BUILD):
                    violations.append(f"{rel}:{line}: {package} must not import "
                                      f"{BUILD_PACKAGE}.{extra}")
                continue
            if own_prefix and layer != ROOT_LAYER \
                    and layer == name.split(".")[1] == own_prefix.split(".")[1] \
                    and not (name + ".").startswith(own_prefix + ".") \
                    and not _sibling_allowed(own_prefix, line, name, targets) \
                    and not _file_allowed(rel, name):
                violations.append(f"{rel}:{line}: {package} must not import {name}")
            elif own_prefix and any(name == banned or name.startswith(banned + ".")
                                    for banned in SUBPACKAGE_BANNED.get(own_prefix, ())):
                violations.append(f"{rel}:{line}: {package} must not import {name}")
            elif layer in lazy and line in in_functions:
                continue
            elif layer not in allowed:
                violations.append(f"{rel}:{line}: {package or module[-1]} must not import {name}")
        seen: set[tuple[int, str]] = set()
        for line, name in _module_targets(tree, module, path.name == "__init__.py"):
            target = next((m for m in MODULE_IMPORTERS
                           if name == m or name.startswith(m + ".")), None)
            if target is not None and rel not in MODULE_IMPORTERS[target] \
                    and (line, target) not in seen:
                seen.add((line, target))
                violations.append(f"{rel}:{line}: only "
                                  f"{', '.join(sorted(MODULE_IMPORTERS[target]))} "
                                  f"may import {target}")
    return violations


def test_engine_follows_adr_0002():
    assert scan(REPO / "engine") == []


def test_scanner_finds_violations(tmp_path):
    engine = tmp_path / "engine"
    for package in ("render", "ui", "app"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text('__version__ = "0"\n', encoding="utf-8")
    (engine / "render" / "bad.py").write_text("import engine.ui\n", encoding="utf-8")
    (engine / "ui" / "bad.py").write_text("from engine.app import cli\n", encoding="utf-8")
    (engine / "app" / "app.py").write_text("from engine.app import dispatch\n"
                                           "from . import cli\n", encoding="utf-8")
    (engine / "ui" / "ok.py").write_text("from ..render import canvas\nimport pygame\n",
                                         encoding="utf-8")
    assert scan(engine) == [
        "engine/render/bad.py:1: render must not import engine.ui",
        "engine/ui/bad.py:1: ui must not import engine.app",
    ]


def test_scanner_flags_pygame_in_core_and_relative_escapes(tmp_path):
    engine = tmp_path / "engine"
    (engine / "core").mkdir(parents=True)
    (engine / "core" / "__init__.py").write_text("", encoding="utf-8")
    (engine / "core" / "x.py").write_text("import pygame\nfrom ..render import canvas\n",
                                          encoding="utf-8")
    assert scan(engine) == [
        "engine/core/x.py:1: core must not import pygame",
        "engine/core/x.py:2: core must not import engine.render",
    ]


def test_ac_f30_03_meta_rows(tmp_path):
    """AC-F30-03 (import half; the privacy half is in ``test_privacy_ast.py``): ``meta``
    imports only ``core``; only ``app`` imports ``meta``; ``engine.meta.username`` only
    ``app/fourthwall.py``, in every import form."""
    engine = tmp_path / "engine"
    for package in ("core", "meta", "ui", "app", "tools"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")

    def write(ref: str, *lines: str) -> None:
        (engine / ref).write_text("".join(line + chr(10) for line in lines), encoding="utf-8")

    write("meta/username.py", "import getpass", "from engine.core import graphemes",
          "from engine.ui import theme")
    write("app/fourthwall.py", "from engine.meta.username import UsernameSource")
    write("app/other.py", "from engine.meta import username", "import engine.meta.username",
          "from engine import meta")
    write("tools/x.py", "from engine.meta import username")
    write("ui/y.py", "import engine.meta")
    assert scan(engine) == [
        "engine/app/other.py:1: only engine/app/fourthwall.py may import engine.meta.username",
        "engine/app/other.py:2: only engine/app/fourthwall.py may import engine.meta.username",
        "engine/meta/username.py:3: meta must not import engine.ui",
        "engine/tools/x.py:1: tools must not import engine.meta",
        "engine/tools/x.py:1: only engine/app/fourthwall.py may import engine.meta.username",
        "engine/ui/y.py:1: ui must not import engine.meta",
    ]
    assert scan(REPO / "engine") == []


def test_editor_row_and_lazy_main_import(tmp_path):
    """F44 I-12: tools/editor imports only core, script, and itself; ``__main__`` imports
    tools only inside a function."""
    engine = tmp_path / "engine"
    for package in ("core", "script", "app", "tools", "tools/editor", "tools/other"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")

    def write(ref: str, *lines: str) -> None:
        (engine / ref).write_text("".join(line + chr(10) for line in lines), encoding="utf-8")

    write("tools/editor/ok.py", "from engine.core import paths",
          "from engine.script import messages", "from engine.tools.editor import ok",
          "import tkinter")
    write("tools/editor/bad.py", "from engine.app import cli", "import pygame",
          "from engine.tools import other")
    write("tools/other/fine.py", "from engine.app import cli")
    write("__main__.py", "from engine.app import cli", "", "def _edit():",
          "    from engine.tools import editor", "", "from engine.tools import editor")
    assert scan(engine) == [
        "engine/__main__.py:6: __main__ must not import engine.tools",
        "engine/tools/editor/bad.py:1: tools.editor must not import engine.app",
        "engine/tools/editor/bad.py:2: tools.editor must not import pygame",
        "engine/tools/editor/bad.py:3: tools.editor must not import engine.tools",
    ]


def test_f42_build_rows(tmp_path):
    """F42 07 I-10 (04 §3.4): tools/build imports core, script and itself, pygame only in
    ``icon.py``, never PyInstaller; tools/editor imports only the five shared build modules,
    which import only each other; ``__main__`` imports build only inside a function."""
    engine = tmp_path / "engine"
    for package in ("core", "script", "app", "tools", "tools/editor", "tools/build"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")

    def write(ref: str, *lines: str) -> None:
        (engine / ref).write_text("".join(line + chr(10) for line in lines), encoding="utf-8")

    write("tools/build/icon.py", "import pygame", "from engine.core import paths",
          "from engine.tools.build import texts")
    write("tools/build/command.py", "from engine.tools.build import icon, tree",
          "from engine.script import assetgroups", "import pygame", "import PyInstaller",
          "from engine.app import cli")
    write("tools/build/tree.py", "from engine.tools.build import texts, rules",
          "from engine.tools.build.icon import make_ico")
    write("tools/editor/buildmodel.py", "from engine.tools.build import names, procs",
          "from engine.tools.build.tree import remove_tree",
          "from engine.tools.build import texts, command", "import engine.tools.build.spec")
    write("__main__.py", "from engine.app import cli", "", "def _build():",
          "    from engine.tools.build.command import build_command", "",
          "import engine.tools.build.command")
    assert scan(engine) == [
        "engine/__main__.py:6: __main__ must not import engine.tools.build.command",
        "engine/tools/build/command.py:3: tools.build must not import pygame",
        "engine/tools/build/command.py:4: tools.build must not import PyInstaller",
        "engine/tools/build/command.py:5: tools.build must not import engine.app",
        "engine/tools/build/tree.py:2: tools.build must not import engine.tools.build.icon",
        "engine/tools/editor/buildmodel.py:3: tools.editor must not import "
        "engine.tools.build.command",
        "engine/tools/editor/buildmodel.py:4: tools.editor must not import "
        "engine.tools.build.spec",
    ]


def test_ac_f45_15_the_check_child_row(tmp_path):
    """AC-F45-15: ``tools/check.py`` imports only core, script, runtime (and itself), never
    pygame; ``tools/editor`` never imports it or ``runtime``. A planted ``engine.app``
    import in a copy of the real ``check.py`` is found."""
    engine = tmp_path / "engine"
    for package in ("core", "script", "runtime", "app", "tools", "tools/editor"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")
    real = (REPO / "engine" / "tools" / "check.py").read_text(encoding="utf-8")
    lines = real.count(chr(10))
    (engine / "tools" / "check.py").write_text(
        real + "from engine.app import loading" + chr(10) + "import pygame" + chr(10),
        encoding="utf-8")
    (engine / "tools" / "editor" / "bad.py").write_text(
        "from engine.tools import check" + chr(10) + "from engine.runtime import launch"
        + chr(10), encoding="utf-8")
    assert scan(engine) == [
        f"engine/tools/check.py:{lines + 1}: tools.check must not import engine.app",
        f"engine/tools/check.py:{lines + 2}: tools.check must not import pygame",
        "engine/tools/editor/bad.py:1: tools.editor must not import engine.tools",
        "engine/tools/editor/bad.py:2: tools.editor must not import engine.runtime",
    ]


# --- AC-F05-41: F05's pygame-free modules, the tag types' route, no eval in the text check ---

F05_NO_PYGAME = ("engine/render/typewriter.py", "engine/script/texttags.py",
                 "engine/runtime/text.py", "engine/core/graphemes.py")


def test_ac_f05_41_text_modules_and_the_launch_check():
    for ref in F05_NO_PYGAME:
        tree = ast.parse((REPO / ref).read_text(encoding="utf-8"))
        names = [name for _, name in _imports(tree, _module_name(REPO / ref, REPO / "engine"),
                                              False)]
        assert not [n for n in names if n.split(".")[0] == "pygame"], ref
    for package in ("render", "ui"):
        for path in sorted((REPO / "engine" / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            module = _module_name(path, REPO / "engine")
            for _, name in _imports(tree, module, path.name == "__init__.py"):
                assert not name.startswith("engine.script"), (path.name, name)
    check = ast.parse((REPO / "engine" / "app" / "text_check.py").read_text(encoding="utf-8"))
    calls = {node.func.id for node in ast.walk(check)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not calls & {"eval", "exec", "compile", "__import__"}


# --- AC-F07-40: F07's modules (04 §3.2) -------------------------------------------------------
# Each F07 module's engine imports, as prefixes (TYPE_CHECKING and in-function imports
# included). ``runtime/menu.py`` also reaches ``engine.core.logsetup``: its records go to the
# ``choice`` log area (07 I-11), the one core module it uses. ``app/choices.py`` reaches the
# tag types and messages through ``runtime.commands`` and ``runtime.errors`` (the re-export
# route F05's ``text_check.py`` uses; only ``loading.py`` of ``engine.app`` imports
# ``engine.script``, AC-F02-66), and its own package (``app.text_check``'s contrast
# function; ``app.app`` for a type).

F07_ROWS: dict[str, tuple[str, ...]] = {
    "engine/script/menu.py": ("engine.script", "engine.core"),
    "engine/runtime/menu.py": ("engine.script", "engine.runtime", "engine.core.logsetup"),
    "engine/render/choices.py": ("engine.runtime.commands", "engine.render", "engine.core"),
    "engine/ui/builtin/choice_screen.py": ("engine.runtime.commands", "engine.render",
                                           "engine.ui", "engine.core"),
    "engine/app/choices.py": ("engine.ui", "engine.render", "engine.core",
                              "engine.runtime.commands", "engine.runtime.errors",
                              "engine.app"),
}
F07_NO_STDLIB = {"engine/script/menu.py": ("pygame",),
                 "engine/runtime/menu.py": ("pygame", "time", "datetime", "random")}


def _f07_imports(ref: str) -> list[str]:
    path = REPO / ref
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [name for _, name in _imports(tree, _module_name(path, REPO / "engine"), False)]


def test_ac_f07_40_choice_modules_import_only_their_rows():
    for ref, allowed in F07_ROWS.items():
        names = _f07_imports(ref)
        engine_names = [n for n in names if n.split(".")[0] == "engine"]
        assert engine_names, ref
        bad = [n for n in engine_names
               if not any(n == a or n.startswith(a + ".") for a in allowed)]
        assert bad == [], (ref, bad)
        banned = F07_NO_STDLIB.get(ref, ())
        assert [n for n in names if n.split(".")[0] in banned] == [], ref


def test_ac_f07_40_the_rows_catch_a_stray_import():
    """The row check itself: in ``runtime/menu.py``, ``time``, an ``engine.ui`` import,
    and any ``core`` module but ``logsetup`` would be found."""
    tree = ast.parse("import time\nfrom engine.ui import screen\nfrom ..core import paths\n"
                     "from engine.core.logsetup import get_logger\n")
    names = [n for _, n in _imports(tree, ["engine", "runtime", "menu"], False)]
    assert names == ["time", "engine.ui", "engine.core", "engine.core.logsetup"]
    allowed = F07_ROWS["engine/runtime/menu.py"]
    assert [n for n in names if n.startswith("engine")
            and not any(n == a or n.startswith(a + ".") for a in allowed)] == [
        "engine.ui", "engine.core"]
    assert "time" in F07_NO_STDLIB["engine/runtime/menu.py"]


# --- AC-F09-40: F09's modules (04 §2.2) -------------------------------------------------------
# The runtime half has no clock, entropy, or pygame; the presentation half follows 04 §2.2's
# directions (``render`` → core, runtime; ``stage_screen`` → core, runtime, render, ui).

F09_ROWS: dict[str, tuple[str, ...]] = {
    "engine/runtime/transitions.py": ("engine.core", "engine.runtime", "engine.script"),
    "engine/runtime/effects.py": ("engine.core", "engine.runtime", "engine.script"),
    "engine/render/transitions.py": ("engine.core", "engine.runtime", "engine.render"),
    "engine/render/stage.py": ("engine.core", "engine.runtime", "engine.render"),
    "engine/ui/builtin/stage_screen.py": ("engine.core", "engine.runtime", "engine.render",
                                          "engine.ui"),
}


def test_ac_f09_40_transition_modules_import_only_their_rows():
    for ref, allowed in F09_ROWS.items():
        names = _f07_imports(ref)
        bad = [n for n in names if n.split(".")[0] == "engine"
               and not any(n == a or n.startswith(a + ".") for a in allowed)]
        assert bad == [], (ref, bad)
        if ref.startswith("engine/runtime/"):
            assert not {n.split(".")[0] for n in names} & {"pygame", "time", "random"}, ref


# --- AC-F17-33: F17's modules (04 §3 Imports; security checklist 1, 5) -----------------------

F17_NO_PYGAME = ("engine/script/nvl.py", "engine/runtime/nvl.py", "engine/render/nvllayout.py")
F17_NO_UPPER = {"engine/script/nvl.py": ("engine.render", "engine.ui", "engine.app",
                                          "engine.persist"),
                "engine/runtime/nvl.py": ("engine.render", "engine.ui", "engine.app",
                                           "engine.persist")}
F17_PRESENTATION = ("engine/render/nvl.py", "engine/render/nvllayout.py",
                    "engine/ui/builtin/nvl_page.py")
F17_MODULES = F17_NO_PYGAME + ("engine/render/nvl.py", "engine/ui/builtin/nvl_page.py")
# F29 (07 I-2): the pose module never imports pygame (``runtime.commands`` for types only).
F29_NO_PYGAME = ("engine/render/textfx.py",)
# F20 (04 §3; AC-F20-69's row): the chart layout is pure, never pygame.
F20_NO_PYGAME = ("engine/ui/flowlayout.py",)


def test_ac_f17_33_nvl_modules_import_only_their_rows():
    for ref in F17_NO_PYGAME + F29_NO_PYGAME + F20_NO_PYGAME:
        assert "pygame" not in {n.split(".")[0] for n in _f07_imports(ref)}, ref
    for ref, banned in F17_NO_UPPER.items():
        names = _f07_imports(ref)
        assert not [n for n in names if any(n == b or n.startswith(b + ".") for b in banned)], ref
    for ref in F17_PRESENTATION:
        names = _f07_imports(ref)
        assert not [n for n in names if n.split(".")[:2] in (["engine", "script"],
                                                              ["engine", "persist"],
                                                              ["engine", "tools"])], ref
    for ref in F17_MODULES:                    # no eval, exec, open, or GamePaths read
        tree = ast.parse((REPO / ref).read_text(encoding="utf-8"))
        calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))}
        assert not calls & {"eval", "exec", "open", "read_bytes", "read_text"}, ref
        assert "GamePaths" not in (REPO / ref).read_text(encoding="utf-8"), ref
    assert scan(REPO / "engine") == []


# --- AC-F19-32: F19's modules (04 §3, §8; 07 I-7) ---------------------------------------------

def test_ac_f19_32_routes_and_endings_modules():
    routes = _f07_imports("engine/script/routes.py")
    assert [n for n in routes if n.startswith("engine.")
            and n.split(".")[1] not in ("core", "script")] == []
    names = _f07_imports("engine/runtime/endings.py")
    assert not {n.split(".")[0] for n in names} & {"pygame", "time", "threading", "random",
                                                   "os", "pathlib", "io", "shutil"}
    assert not [n for n in names if n.split(".")[:2] in (
        ["engine", "app"], ["engine", "ui"], ["engine", "render"], ["engine", "persist"])]
    tree = ast.parse((REPO / "engine/runtime/endings.py").read_text(encoding="utf-8"))
    calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
             for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, (ast.Name, ast.Attribute))}
    assert not calls & {"eval", "exec", "open", "read_bytes", "read_text", "write_bytes"}
    # Only app/loading.py of the app layer imports engine.script at run time (07 I-7); an
    # ``if TYPE_CHECKING:`` import (annotations only) doesn't count.
    script_users = []
    for path in sorted((REPO / "engine" / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        typing_only = {inner.lineno for node in ast.walk(tree) if isinstance(node, ast.If)
                       and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                       for inner in ast.walk(node) if hasattr(inner, "lineno")}
        module = _module_name(path, REPO / "engine")
        if any(n.split(".")[:2] == ["engine", "script"] and line not in typing_only
               for line, n in _imports(tree, module, path.name == "__init__.py")):
            script_users.append(path.relative_to(REPO).as_posix())
    assert script_users == ["engine/app/loading.py"], script_users
    # render and ui reach TitleCard only through runtime.commands.
    for package in ("render", "ui"):
        for path in sorted((REPO / "engine" / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "TitleCard" not in text:
                continue
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and any(a.name == "TitleCard"
                                                            for a in node.names):
                    assert node.module == "engine.runtime.commands", path
    assert scan(REPO / "engine") == []


# --- The bundled minigames' import kit (F23 04 §7.10; F24; F25 A7, F26 A8, SPEC I-20) ------

BUNDLED_KIT = ("engine.minigames.api", "engine.minigames.bundled", "engine.ui.focus",
               "engine.ui.widgets", "engine.ui.paint", "engine.ui.nav", "engine.ui.layouts",
               "engine.render.frames", "engine.render.text",
               "engine.core.constants")   # canvas size (F27 room_rules; project decision 2026-11-02)


def _bundled_strays(path: Path) -> list[str]:
    """Imports of ``path`` outside the kit and the stdlib (``if TYPE_CHECKING:`` excepted)."""
    import sys

    tree = ast.parse(path.read_text(encoding="utf-8"))
    typing_only = {inner.lineno for node in ast.walk(tree) if isinstance(node, ast.If)
                   and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                   for inner in ast.walk(node) if hasattr(inner, "lineno")}
    module = _module_name(path, REPO / "engine") if path.is_relative_to(REPO) else \
        ["engine", "minigames", "bundled", path.stem]
    strays = []
    for line, name in _imports(tree, module, path.name == "__init__.py"):
        top = name.split(".")[0]
        if line in typing_only or top == "pygame" or (top != "engine"
                                                      and top in sys.stdlib_module_names):
            continue
        if not any(name == k or name.startswith(k + ".") for k in BUNDLED_KIT):
            strays.append(name)
    return strays


def test_bundled_minigames_import_only_the_kit(tmp_path):
    for path in sorted((REPO / "engine" / "minigames" / "bundled").glob("*.py")):
        assert _bundled_strays(path) == [], path.name
    planted = tmp_path / "bad.py"
    planted.write_text("from typing import TYPE_CHECKING\nimport re\nimport pygame\n"
                       "from engine.ui.nav import Nav\nfrom engine.ui.layouts import pitch\n"
                       "from engine.minigames.context import Context\n"
                       "from engine.runtime.state import GameState\n"
                       "from engine.ui.menus import MenuScreen\n"
                       "if TYPE_CHECKING:\n    from engine.app.app import App\n",
                       encoding="utf-8")
    assert _bundled_strays(planted) == ["engine.minigames.context", "engine.runtime.state",
                                        "engine.ui.menus"]


# --- AC-F21-35: F21's modules (04 §3 imports, TR-F21-06) ---------------------------------------

def _runtime_imports(ref: str) -> list[tuple[int, str, bool]]:
    """(line, name, under ``if TYPE_CHECKING:``) for every import of ``ref``."""
    path = REPO / ref
    tree = ast.parse(path.read_text(encoding="utf-8"))
    typing_only = {inner.lineno for node in ast.walk(tree) if isinstance(node, ast.If)
                   and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
                   for inner in ast.walk(node) if hasattr(inner, "lineno")}
    return [(line, name, line in typing_only)
            for line, name in _imports(tree, _module_name(path, REPO / "engine"), False)]


def test_ac_f21_35_codex_modules_import_only_their_rows():
    script = [n for _, n, _ in _runtime_imports("engine/script/codex.py")
              if n.startswith("engine")]
    assert script and all(n.split(".")[1] in ("core", "script") for n in script), script
    runtime = _runtime_imports("engine/runtime/codex.py")
    assert not {n.split(".")[0] for _, n, _ in runtime} & {
        "pygame", "time", "random", "threading", "os", "pathlib", "io", "shutil"}
    lazy = _function_imports(ast.parse((REPO / "engine/runtime/codex.py").read_text(
        encoding="utf-8")))                       # the executor's ``Step``, inside a function
    assert all(typing or line in lazy for line, n, typing in runtime
               if n == "engine.runtime.interpreter")
    page = [n for _, n, _ in _runtime_imports("engine/ui/builtin/codex_page.py")]
    assert not [n for n in page if n.split(".")[:2] in (["engine", "script"],
                                                        ["engine", "persist"])], page
    app = _runtime_imports("engine/app/codex.py")
    assert all(typing for _, n, typing in app if n.split(".")[:2] == ["engine", "script"])
    assert scan(REPO / "engine") == []


def test_ac_f23_60_minigame_modules_import_only_their_rows():
    """F23 ``04`` §2 (Imports), §8 invariants 5 and 7: ``engine/minigames`` imports only
    ``core``, ``runtime``, ``render``, ``audio``, and ``ui``; ``app/minigames.py`` imports
    ``engine.script`` only for type checking; ``runtime/minigame.py`` reads no clock and
    imports no ``random``, ``threading``, or ``pygame``."""
    for path in sorted((REPO / "engine" / "minigames").glob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        for _, name, _ in _runtime_imports(rel):
            parts = name.split(".")
            if parts[0] == "engine":
                assert parts[1] in ("core", "runtime", "render", "audio", "ui",
                                    "minigames"), (rel, name)
    app = _runtime_imports("engine/app/minigames.py")
    assert all(typing for _, n, typing in app if n.split(".")[:2] == ["engine", "script"])
    runtime = _runtime_imports("engine/runtime/minigame.py")
    assert not {n.split(".")[0] for _, n, _ in runtime} & {"pygame", "time", "random",
                                                          "threading"}
    assert scan(REPO / "engine") == []


def test_ac_f31_26_meta_files_import_rows():
    """AC-F31-26 (import half; the privacy half is in ``test_privacy_ast.py``):
    ``engine.meta.files`` is imported only by ``app/metafiles.py`` and imports only the
    standard library and ``engine.core`` (never ``engine.meta.username``);
    ``runtime/metafiles.py`` imports no ``engine.meta``, ``engine.app``, ``engine.persist``,
    or ``pygame``; ``app/metafiles.py`` imports ``engine.script`` only for type checking."""
    users = set()
    for path in sorted((REPO / "engine").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if any(n == "engine.meta.files" or n.startswith("engine.meta.files.")
               for _, n, _ in _runtime_imports(rel)):
            users.add(rel)
    assert users == {"engine/app/metafiles.py"}
    for _, name, _ in _runtime_imports("engine/meta/files.py"):
        parts = name.split(".")
        assert parts[0] != "engine" or parts[1] == "core", name
        assert parts[0] != "pygame", name
    runtime = [n for _, n, _ in _runtime_imports("engine/runtime/metafiles.py")]
    assert not [n for n in runtime if n.split(".")[0] == "pygame" or n.split(".")[:2] in (
        ["engine", "meta"], ["engine", "app"], ["engine", "persist"])], runtime
    app = _runtime_imports("engine/app/metafiles.py")
    assert all(typing for _, n, typing in app if n.split(".")[:2] == ["engine", "script"])
    assert scan(REPO / "engine") == []


def test_f40_console_row(tmp_path):
    """F40 (04 §3, 07 I-3): tools/console may import core, script, runtime, render, ui, app
    and pygame; never meta, persist, audio, minigames, or another tools package."""
    engine = tmp_path / "engine"
    for package in ("core", "app", "persist", "audio", "minigames", "meta", "tools",
                    "tools/console", "tools/editor", "tools/check"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")
    (engine / "tools" / "console" / "ok.py").write_text(
        "import pygame\nfrom engine.core import redact\nfrom engine.app import editor_link\n"
        "from engine.tools.console import ok\n", encoding="utf-8")
    (engine / "tools" / "console" / "bad.py").write_text(
        "from engine.persist import saves\nimport engine.audio\nfrom engine.minigames import x\n"
        "import engine.meta\nfrom engine.tools.editor import y\n"
        "from engine.tools import check\n", encoding="utf-8")
    assert scan(engine) == [
        "engine/tools/console/bad.py:1: tools.console must not import engine.persist",
        "engine/tools/console/bad.py:2: tools.console must not import engine.audio",
        "engine/tools/console/bad.py:3: tools.console must not import engine.minigames",
        "engine/tools/console/bad.py:4: tools.console must not import engine.meta",
        "engine/tools/console/bad.py:5: tools.console must not import engine.tools.editor",
        "engine/tools/console/bad.py:6: tools.console must not import engine.tools",
    ]


# --- F43 pure modules (04 §3, 07 "Shared contracts"): core/langtags and core/fontcmap import
# the standard library only; render/linebreak imports the stdlib and engine.core, no pygame ---

F43_ROWS = {"engine/core/langtags.py": (), "engine/core/fontcmap.py": (),
            "engine/render/linebreak.py": ("engine.core",)}


def test_f43_pure_modules_import_only_their_rows():
    import sys

    for ref, allowed in F43_ROWS.items():
        for _, name, _ in _runtime_imports(ref):
            top = name.split(".")[0]
            assert (top != "engine" and top in sys.stdlib_module_names) or any(
                name == k or name.startswith(k + ".") for k in allowed), (ref, name)


# --- AC-F48-01: tools/assistant (04 §3; 07 §2.2, I-2) -------------------------------------------

def test_ac_f48_01_assistant_row(tmp_path):
    """tools/assistant imports core, script, itself, the named pure editor modules and
    tools.build.procs; never tkinter, pygame, runtime, app, tools.check or another editor or
    build module; network modules only in ``providers/``. ``__main__`` imports it only inside
    a function, and no other package imports it."""
    engine = tmp_path / "engine"
    for package in ("core", "script", "runtime", "app", "ui", "tools", "tools/assistant",
                    "tools/assistant/providers", "tools/editor", "tools/build"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")

    def write(ref: str, *lines: str) -> None:
        (engine / ref).write_text("".join(line + chr(10) for line in lines), encoding="utf-8")

    write("tools/assistant/ok.py", "import json", "from engine.core import redact",
          "from engine.script.parser import parse_file", "from engine.tools.assistant import ok",
          "from engine.tools.editor import files, scenes as sc",
          "from engine.tools.editor.checker import CheckItem",
          "from engine.tools.build.procs import without_keys",
          "from engine.tools.build import procs")
    write("tools/assistant/providers/http.py", "import socket", "import ssl",
          "import http.client", "from urllib.parse import urlsplit")
    write("tools/assistant/bad.py", "import tkinter", "import pygame", "import socket",
          "from http import client", "from engine.runtime import launch",
          "from engine.app import cli", "from engine.tools import check",
          "from engine.tools.editor import files, window",
          "from engine.tools.editor.studiomenus import x", "from engine.tools.build import tree")
    write("ui/x.py", "from engine.tools.assistant import ok")
    write("__main__.py", "from engine.app import cli", "", "def _assist_mcp():",
          "    from engine.tools.assistant.mcp import serve", "",
          "import engine.tools.assistant.mcp")
    assert scan(engine) == [
        "engine/__main__.py:6: __main__ must not import engine.tools.assistant.mcp",
        "engine/tools/assistant/bad.py:1: tools.assistant must not import tkinter",
        "engine/tools/assistant/bad.py:2: tools.assistant must not import pygame",
        "engine/tools/assistant/bad.py:3: tools.assistant must not import socket",
        "engine/tools/assistant/bad.py:4: tools.assistant must not import http",
        "engine/tools/assistant/bad.py:5: tools.assistant must not import engine.runtime",
        "engine/tools/assistant/bad.py:6: tools.assistant must not import engine.app",
        "engine/tools/assistant/bad.py:7: tools.assistant must not import engine.tools",
        "engine/tools/assistant/bad.py:8: tools.assistant must not import engine.tools.editor",
        "engine/tools/assistant/bad.py:9: tools.assistant must not import "
        "engine.tools.editor.studiomenus",
        "engine/tools/assistant/bad.py:10: tools.assistant must not import "
        "engine.tools.build",
        "engine/ui/x.py:1: ui must not import engine.tools.assistant",
    ]
    assert scan(REPO / "engine") == []


def test_f48_w4_only_the_assistant_tk_modules_import_the_assistant(tmp_path):
    """04 §3.2: aisettings, assistpane and assistwiring may import tools.assistant; any
    other tools/editor module may not."""
    engine = tmp_path / "engine"
    for package in ("core", "script", "tools", "tools/assistant", "tools/editor"):
        (engine / package).mkdir(parents=True)
        (engine / package / "__init__.py").write_text("", encoding="utf-8")
    (engine / "__init__.py").write_text("", encoding="utf-8")
    line = "from engine.tools.assistant import prefs" + chr(10) + \
        "import engine.tools.assistant.chat" + chr(10)
    for name in (*ASSISTANT_TK_MODULES, "window"):
        (engine / "tools" / "editor" / f"{name}.py").write_text(line, encoding="utf-8")
    assert scan(engine) == [
        "engine/tools/editor/window.py:1: tools.editor must not import engine.tools.assistant",
        "engine/tools/editor/window.py:2: tools.editor must not import "
        "engine.tools.assistant.chat",
    ]


def test_f48_i2_the_server_closure_loads_no_tk_or_network():
    """07 I-2: with tkinter and pygame blocked, importing ``tools.assistant.mcp`` and
    ``.tools`` (the MCP server's closure, the pure editor modules included) succeeds and
    loads no ``socket``, ``ssl`` or ``http``."""
    import os
    import subprocess
    import sys

    code = ("import sys\n"
            "sys.modules['tkinter'] = sys.modules['pygame'] = None\n"
            "import engine.tools.assistant.mcp, engine.tools.assistant.tools\n"
            "print(sorted(m for m in sys.modules\n"
            "             if m.split('.')[0] in ('socket', '_socket', 'ssl', '_ssl', 'http')))\n")
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("PYTHON")}
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.run([sys.executable, "-P", "-c", code], capture_output=True, text=True,
                          timeout=120, cwd=str(REPO), env=env)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "[]"
