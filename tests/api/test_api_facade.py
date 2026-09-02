"""`ducta.api` must advertise its surface without importing it.

The package used to re-export ~90 names eagerly, so importing *anything* under
`ducta.api` executed `__init__` and dragged the whole package in behind it:
auth (and therefore PyJWT), the database layer, the execution engine, every
route module, and the FastAPI app factory.

The visible symptom was that `from ducta.api.config import Settings` — a module
whose only dependency is pydantic-settings — died with `ModuleNotFoundError: No
module named 'jwt'`. The subtler one was that it defeated the laziness
`ducta.api.main` goes out of its way to implement, whose whole purpose is that
importing the module must not build the app and reconfigure logging.

Same two properties as `tests/test_public_api.py` asserts for the top-level
façade, and they pull against each other the same way: every advertised name
resolves, and importing the package stays cheap.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import ducta.api

#: `src/` of this checkout. The probes below must exercise the working tree,
#: not whatever copy of `ducta` happens to be installed in site-packages —
#: pytest gets this from `pythonpath = ["src"]` in pyproject.toml, but a bare
#: `python -c` subprocess inherits no such thing and would silently assert
#: against the installed package instead.
_SRC = Path(__file__).resolve().parents[2] / "src"


def _probe(code: str) -> str:
    """Run *code* in a clean interpreter against this checkout, return stdout."""
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.strip()


class TestSurface:
    def test_every_advertised_name_resolves(self):
        unresolved = []
        for name in ducta.api.__all__:
            try:
                getattr(ducta.api, name)
            except Exception as exc:  # noqa: BLE001
                unresolved.append(f"{name}: {type(exc).__name__}: {exc}")
        assert not unresolved, "names in __all__ that do not resolve:\n" + "\n".join(unresolved)

    def test_unknown_names_raise_attribute_error(self):
        # A typo must not surface as an ImportError from somewhere deep in the
        # package.
        with pytest.raises(AttributeError, match="no attribute 'NotAThing'"):
            ducta.api.NotAThing

    def test_dir_matches_all(self):
        assert dir(ducta.api) == sorted(ducta.api.__all__)

    def test_all_and_the_lazy_map_cannot_drift(self):
        # `__all__` is derived from `_PUBLIC_API`, so this pins the invariant
        # rather than a hand-maintained list: a name reachable through
        # `__getattr__` but absent from `__all__` would be invisible to tooling.
        assert set(ducta.api.__all__) == {"__version__"} | set(ducta.api._PUBLIC_API)

    def test_no_duplicate_names(self):
        # The eager façade listed `get_execution_manager` twice, importing it
        # from two different modules and silently keeping one. A dict cannot
        # express that ambiguity, and this keeps it from coming back via a
        # hand-edited __all__.
        assert len(ducta.api.__all__) == len(set(ducta.api.__all__))

    def test_version_is_a_real_attribute_not_a_lazy_one(self):
        # Cheap and universally wanted; it should not need a module import.
        assert isinstance(ducta.api.__version__, str)
        assert "__version__" not in ducta.api._PUBLIC_API

    def test_errors_are_catchable_from_the_facade(self):
        for name in ducta.api.__all__:
            if name.endswith("Error"):
                assert issubclass(getattr(ducta.api, name), Exception)


class TestImportCost:
    def test_importing_the_package_pulls_in_no_heavy_dependency(self):
        pulled = _probe(
            "import sys, ducta.api; "
            "print(','.join(m for m in ('fastapi','sqlalchemy','jwt','uvicorn') "
            "if m in sys.modules))"
        )
        assert pulled == "", f"import ducta.api pulled in {pulled}"

    def test_a_leaf_module_does_not_drag_in_the_package(self):
        # The exact import that used to fail on an install without the API
        # extras. `config` depends only on pydantic-settings.
        pulled = _probe(
            "import sys; from ducta.api.config import Settings; "
            "print(','.join(m for m in ('fastapi','jwt') if m in sys.modules))"
        )
        assert pulled == "", f"importing ducta.api.config pulled in {pulled}"

    def test_touching_a_name_resolves_it(self):
        # Laziness must not turn into "never loads": the deferred import has to
        # actually happen on attribute access.
        assert (
            _probe(
                "import sys, ducta.api; "
                "assert 'jwt' not in sys.modules; "
                "ducta.api.AuthService; "
                "assert 'jwt' in sys.modules; "
                "print('ok')"
            )
            == "ok"
        )
