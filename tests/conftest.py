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

import pytest

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
    "ducta.core",
    "ducta.core.utils",
    "ducta.core.dependency_inference",
    "ducta.core.pipeline_dependency_resolver",
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
    """Auto-skip Spark-marked tests when pyspark is not installed."""
    if HAS_PYSPARK:
        return
    skip_spark = pytest.mark.skip(reason="pyspark not installed")
    for item in items:
        if "spark" in item.keywords:
            item.add_marker(skip_spark)


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
