"""How Ducta's packages may depend on each other — read from the source, not imported.

  * No two packages import each other at module level. ``setting`` ↔ ``mlrun`` did
    (``setting.contexts`` → ``mlrun.hyperparams``; ``mlrun.config`` → ``setting``):
    it worked only for as long as the import order happened to.
  * Nothing in ``ducta`` imports the web server (``ducta_server``): it is a separate
    distribution (``ducta-server``) that depends on this one, never the other way round.
  * The engine does not depend on the layers built on it. ``core`` and ``check``
    imported the CLI's presentation (``console.ux``) to print progress; they now
    report through ``ducta.reporting``, which the CLI and the API server fill in.

Imports inside functions and under ``if TYPE_CHECKING:`` are lazy: they are
allowed to point upwards for the first rule, but not for the second.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterator, Set, Tuple

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "ducta"

#: The engine: it runs pipelines and must work without the CLI or the server.
#: ``project_store`` and ``runs`` read and edit what the engine runs and leaves
#: behind; the CLI, the AI layer and the server share them.
ENGINE = ("setting", "gate", "check", "mlrun", "stream", "core", "project_store", "runs")
#: What is built on top of the engine.
INTERFACES = ("console", "api", "ai")


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imports(path: Path) -> Iterator[Tuple[str, bool]]:
    """``(imported module, at module level)`` for every ``ducta.*`` import of *path*."""
    rel = path.relative_to(SRC).with_suffix("").parts

    def visit(node: ast.AST, top: bool) -> Iterator[Tuple[str, bool]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                yield from visit(child, False)
            elif isinstance(child, ast.If) and _is_type_checking(child):
                yield from visit(child, False)
            elif isinstance(child, ast.Import):
                yield from ((a.name, top) for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                if child.level:
                    base = rel[: len(rel) - child.level]  # `.` is the file's own package
                    yield ".".join(("ducta", *base, *([child.module] if child.module else []))), top
                else:
                    yield child.module or "", top
            else:
                yield from visit(child, top)

    yield from visit(ast.parse(path.read_text(encoding="utf-8")), True)


def _package_edges() -> Dict[Tuple[str, str], Set[Tuple[str, bool]]]:
    """``{(package, imported package): {(file, at module level), ...}}``."""
    edges: Dict[Tuple[str, str], Set[Tuple[str, bool]]] = defaultdict(set)
    for path in SRC.rglob("*.py"):
        parts = path.relative_to(SRC).parts
        if len(parts) < 2 or "node_modules" in parts:
            continue
        package = parts[0]
        for module, top in _imports(path):
            target = module.split(".")
            if target[0] == "ducta" and len(target) > 1 and target[1] != package:
                edges[(package, target[1])].add((str(path.relative_to(SRC)), top))
    return edges


EDGES = _package_edges()


def test_the_scan_sees_the_packages():
    # Guards the guard: a scan that found nothing would pass every rule below.
    assert ("core", "setting") in EDGES
    assert ("console", "core") in EDGES


def test_no_two_packages_import_each_other_at_module_level():
    top_level = {pair for pair, sites in EDGES.items() if any(top for _, top in sites)}
    cycles = sorted({tuple(sorted(pair)) for pair in top_level if pair[::-1] in top_level})
    assert cycles == [], f"module-level import cycles between packages: {cycles}"


def test_the_engine_never_imports_the_cli_the_server_or_the_ai_layer():
    offending = sorted(
        f"{file} -> ducta.{target}"
        for (package, target), sites in EDGES.items()
        if package in ENGINE and target in INTERFACES
        for file, _ in sites
    )
    assert offending == [], "the engine reports through ducta.reporting:\n" + "\n".join(offending)


@pytest.mark.parametrize("module", ["reporting.py", "locking.py", "state.py"])
def test_the_shared_low_level_modules_depend_on_nothing_in_ducta(module):
    # Every package may import them, so they may import none: no cycle can start here.
    imported = [name for name, _ in _imports(SRC / module)]
    assert not [m for m in imported if m.startswith("ducta")]


SERVER = Path(__file__).resolve().parents[1] / "server" / "src" / "ducta_server"


def _all_imports(root: Path) -> Iterator[Tuple[str, str]]:
    """``(file, imported module)`` for every import under *root*, lazy ones included."""
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield str(path.relative_to(root.parent)), alias.name
            elif isinstance(node, ast.ImportFrom) and not node.level:
                yield str(path.relative_to(root.parent)), node.module or ""


def test_ducta_never_imports_the_server():
    # `ducta ui` finds the server by name at run time (console/ui.py), never by import:
    # it is a separate distribution (ducta-server) that depends on this one.
    offending = sorted(
        f"{file} -> {module}"
        for file, module in _all_imports(SRC)
        if module.split(".")[0] in ("ducta_server",) or module.startswith("ducta.api")
    )
    assert offending == [], "the server is a separate package:\n" + "\n".join(offending)


def test_the_server_lives_outside_the_engine_tree():
    assert not (SRC / "api").exists() and not (SRC / "ui").exists()
    assert (SERVER / "main.py").is_file()


def test_the_server_uses_no_private_name_of_the_engine():
    # What the server imports from `ducta` is the engine's contract with it: a
    # private name there breaks the server on an engine refactor no engine test sees.
    offending = []
    for path in SERVER.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ducta."):
                offending += [
                    f"{path.relative_to(SERVER.parent)}: {node.module}.{a.name}"
                    for a in node.names
                    if a.name.startswith("_") and not a.name.startswith("__")
                ]
    assert offending == [], "\n".join(offending)
