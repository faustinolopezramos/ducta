"""Shared pytest fixtures and configuration for the Ducta test suite.

The suite is intentionally engine-light: the vast majority of tests exercise
pure Python logic (config parsing/validation, dependency resolution, security
sanitizers, data-quality checks over pandas, MLOps bookkeeping) and therefore
run without a PySpark/JVM environment. Tests that genuinely need Spark are
marked ``@pytest.mark.spark`` and skip automatically when pyspark is absent.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Point every process at this repo's coverage config.
#
# Several tests chdir into a temporary project and spawn worker processes
# (``run_in_process``, the sweep workers, the template smoke tests).
# pytest-cov's .pth hook starts coverage inside those children, but from a cwd
# where this pyproject.toml is not discoverable — so they record statement-only
# data while the parent records branch data (``[tool.coverage.run] branch =
# true``). The run then dies in the final combine with "Can't combine statement
# coverage data with branch data", *after* every test has passed, which reads as
# a coverage crash rather than a test failure.
#
# CI set COVERAGE_RCFILE in the workflow env, so `pytest --cov` was green there
# and crashed for anyone running it locally. Setting it here fixes both, and
# keeps the two from drifting apart again. An operator-supplied value wins.
# ---------------------------------------------------------------------------
os.environ.setdefault(
    "COVERAGE_RCFILE", str(Path(__file__).resolve().parent.parent / "pyproject.toml")
)

# Spark launches its Python workers with whatever `python3` is first on PATH —
# on macOS the system 3.9 — and every Python-side operation then dies with
# PYTHON_VERSION_MISMATCH. Pin them to this interpreter for every test that
# starts a real session, not only the integration ones: tests/check starts one
# too, and passed only when the integration conftest had already set this.
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

# ---------------------------------------------------------------------------
# Eagerly import the real modules that some per-directory conftests
# (tests/setting, tests/gate) would otherwise replace with lightweight fakes
# in sys.modules. Those conftests install their mocks only ``if name not in
# sys.modules``, so importing the genuine packages here first — before pytest
# loads the subdirectory conftests — makes those guards no-op and keeps the
# real modules available to every test in the session. Without this, a fake
# ``ducta.core`` (a plain module, not a package) shadows ``ducta.core.utils``
# et al. and breaks collection of the engine tests.
# ---------------------------------------------------------------------------
_REAL_MODULES = (
    "pydantic",
    "pandas",
    "numpy",
    "ducta.setting",
    "ducta.setting.dependency_inference",
    "ducta.setting.pipeline_dependency_resolver",
    "ducta.core",
    "ducta.core.utils",
    "ducta.core.dependency_resolver",
    "ducta.check",
    "ducta.check.core",
    "ducta.mlrun",
    "ducta.mlrun.hyperparams",
    # Real pyspark, when installed, so the fake `pyspark.*` modules that
    # tests/gate and tests/stream install ("only if absent") stay no-ops. Without
    # this the winner depends on collection order, and tests/integration — which
    # needs a genuine JVM-backed session — could be handed the fakes.
    "pyspark",
    "pyspark.sql",
    # MLflow inspects whatever is in sys.modules (a stub `pyspark`/`polars`) while it
    # imports, and fails with "cannot import name 'EvaluationDataset'". ducta.mlrun used
    # to import it eagerly, which made this import happen here, before any stub existed;
    # it is lazy now (the CLI no longer pays 0.3 s for it), so it is imported here.
    "mlflow",
    "mlflow.tracking",
)
for _name in _REAL_MODULES:
    try:
        importlib.import_module(_name)
    except Exception:  # pragma: no cover - best effort; absent deps stay absent
        pass


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


HAS_PYSPARK = _has("pyspark")
HAS_POLARS = _has("polars")
HAS_SQLGLOT = _has("sqlglot")


def pytest_collection_modifyitems(config, items):
    """Run the Delta tests first; auto-skip Spark-marked tests without pyspark.

    Delta's jar joins the JVM classpath only when the JVM starts, and the JVM
    outlives ``SparkSession.stop()``. Once any earlier test has started Spark,
    the Delta session cannot load — so in a full run (CI's) the Delta tests
    always skipped. Moved to the front, they get the first JVM; their fixture
    stops its session, and later tests start their own.
    """
    items.sort(key=lambda item: item.path.name != "test_delta_merge.py")
    if HAS_PYSPARK:
        return
    skip_spark = pytest.mark.skip(reason="pyspark not installed")
    for item in items:
        if "spark" in item.keywords:
            item.add_marker(skip_spark)


@pytest.fixture(autouse=True)
def _forget_project_modules(tmp_path_factory):
    """Drop the modules a test imported from a project it generated under tmp.

    Every template names its package ``pipelines``. A test that imports the
    medallion project's ``pipelines`` leaves it in ``sys.modules``, and the next
    test's streaming project then resolves ``pipelines.transforms`` against the
    wrong folder — a node fails to start and the test fails only in a full run.
    """
    before = set(sys.modules)
    yield
    base = os.path.realpath(tmp_path_factory.getbasetemp())
    for name in set(sys.modules) - before:
        module = sys.modules.get(name)
        locations = [getattr(module, "__file__", None) or ""]
        locations += list(getattr(module, "__path__", None) or [])
        if any(loc and os.path.realpath(loc).startswith(base) for loc in locations):
            del sys.modules[name]


@pytest.fixture(autouse=True, scope="session")
def _silence_loguru_atexit():
    """Loguru's default stderr sink raises 'I/O operation on closed file' when
    background atexit handlers (e.g. SparkSessionManager cleanup) log during
    interpreter shutdown. Remove the sink at the end of the session so the noise
    never pollutes test output.
    """
    yield
    try:
        from loguru import logger

        logger.remove()
    except Exception:
        pass


@pytest.fixture
def fake_spark():
    """A stand-in SparkSession good enough for Context construction.

    Passing this as ``spark_session=`` to :class:`~ducta.setting.contexts.Context`
    avoids the real ``SparkSessionFactory.get_session`` call (which would import
    pyspark). It exposes just the attributes Ducta touches defensively.
    """

    class _FakeCatalog:
        def clearCache(self):  # noqa: N802 - Spark API name
            return None

    class _FakeSparkContext:
        def setLocalProperty(self, *_args, **_kwargs):  # noqa: N802
            return None

    class _FakeSpark:
        version = "fake-3.5.0"
        catalog = _FakeCatalog()
        sparkContext = _FakeSparkContext()

    return _FakeSpark()
