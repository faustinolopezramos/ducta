"""A server run forgets the project's modules, not the libraries it imported.

Removing an installed package from ``sys.modules`` made the next run re-import it, and a
C extension such as numpy 2 refuses that ("cannot load module more than once per
process"): every run after the first one that imported it failed its preflight.
"""

from __future__ import annotations

import sys
import sysconfig
from pathlib import Path
from types import ModuleType

from ducta.api.execution.isolation import ModuleIsolationManager


def _module(name: str, file: Path) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(file)
    return module


def test_project_modules_go_and_installed_ones_stay(tmp_path, monkeypatch):
    project = _module("demo_src_ml", tmp_path / "src" / "ml.py")
    library = _module("demo_lib", tmp_path / "venv" / "site-packages" / "demo_lib" / "__init__.py")
    stdlib = _module("demo_std", Path(sysconfig.get_paths()["stdlib"]) / "demo_std.py")

    manager = ModuleIsolationManager()
    manager.snapshot_modules("run")
    for module in (project, library, stdlib):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    assert manager.cleanup("run") == 1
    assert "demo_src_ml" not in sys.modules
    assert sys.modules["demo_lib"] is library
    assert sys.modules["demo_std"] is stdlib


def test_a_module_without_a_file_is_still_judged_by_name(monkeypatch):
    manager = ModuleIsolationManager()
    manager.snapshot_modules("run")
    monkeypatch.setitem(sys.modules, "demo_namespace", ModuleType("demo_namespace"))
    assert manager.cleanup("run") == 1
    assert "demo_namespace" not in sys.modules
