"""The `ducta` façade: what the project promises not to move.

"Declare the public Python API stable" is the gate to leaving alpha. Before the
façade there was nothing to declare — `ducta` exported only `__version__`, so
every consumer imported from an internal path like `ducta.core.executors.batch`
and stability would have meant freezing the whole layout.

Two properties matter, and they pull against each other:
  * every advertised name resolves, and
  * `import ducta` stays cheap enough for a bare `pip install ducta`, where
    pyspark/mlflow/fastapi are not installed at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import ducta


class TestSurface:
    def test_every_advertised_name_resolves(self):
        unresolved = []
        for name in ducta.__all__:
            try:
                getattr(ducta, name)
            except Exception as exc:  # noqa: BLE001
                unresolved.append(f"{name}: {type(exc).__name__}: {exc}")
        assert not unresolved, "names in __all__ that do not resolve:\n" + "\n".join(unresolved)

    def test_unknown_names_raise_attribute_error(self):
        # The lazy `__getattr__` must not turn a typo into an ImportError from
        # somewhere deep in the package.
        with pytest.raises(AttributeError, match="no attribute 'NotAThing'"):
            ducta.NotAThing

    def test_dir_matches_all(self):
        assert dir(ducta) == sorted(ducta.__all__)

    def test_all_and_the_lazy_map_cannot_drift(self):
        # `__all__` is spelled out so linters and IDEs see it statically; the
        # lazy `__getattr__` resolves from `_PUBLIC_API`. A name added to one
        # and not the other is either invisible to tooling or unresolvable.
        assert set(ducta.__all__) == {"__version__"} | set(ducta._PUBLIC_API)

    def test_the_documented_extension_points_are_public(self):
        # README points contributors at these by name.
        for name in ("register_check", "ReaderFactory", "WriterFactory"):
            assert name in ducta.__all__, f"{name} is a documented extension point"

    def test_errors_are_catchable_from_the_top_level(self):
        # `except ducta.DuctaError` should work without knowing the layout.
        assert issubclass(ducta.DuctaError, Exception)
        for name in ducta.__all__:
            if name.endswith("Error"):
                assert issubclass(getattr(ducta, name), Exception)


#: `src/` of this checkout. The probes below must exercise the working tree,
#: not whatever copy of `ducta` is installed in site-packages. pytest itself
#: gets this from `pythonpath = ["src"]` in pyproject.toml, but a bare
#: `python -c` subprocess inherits nothing of the sort — so these tests were
#: silently asserting against the installed package, and would both miss a
#: regression in the working tree and fail whenever the install merely lagged
#: behind it.
_SRC = Path(__file__).resolve().parent.parent / "src"


def _probe(code: str) -> str:
    """Run *code* in a clean interpreter against this checkout, return stdout."""
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.strip()


class TestImportCost:
    def test_importing_ducta_pulls_in_no_heavy_dependency(self):
        # A bare `pip install ducta` has none of these, and `ducta template`,
        # `ducta config` and `ducta certify` are documented to work anyway. An
        # eager re-export in __init__ would break that silently on the machines
        # that lack them — never on a dev box with `[all]` installed.
        pulled = _probe(
            "import sys, ducta; "
            "print(','.join(m for m in ('pyspark','mlflow','fastapi','sqlalchemy') "
            "if m in sys.modules))"
        )
        assert pulled == "", f"import ducta pulled in {pulled}"

    def test_the_facade_is_lazy(self):
        out = _probe(
            "import sys, ducta; "
            "before = len([m for m in sys.modules if m.startswith('ducta')]); "
            "_ = ducta.PipelineExecutor; "
            "after = len([m for m in sys.modules if m.startswith('ducta')]); "
            "print(before, after)"
        )
        before, after = (int(x) for x in out.split())
        assert before == 1, f"import ducta eagerly loaded {before} ducta modules"
        assert after > before, "touching PipelineExecutor should resolve it on demand"
