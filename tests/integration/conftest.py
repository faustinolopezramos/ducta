"""Fixtures for tests that run against a real, JVM-backed Spark session.

Everything here is marked ``spark`` and skips when pyspark is absent (see the
root conftest). These are deliberately the only tests in the suite that do *not*
mock Spark: the rest of the suite is engine-light and fast, but that means it
cannot see anything about how Ducta behaves against genuine Spark objects. The
gap was not theoretical — a grouped ``try/except ImportError`` silently replaced
``pyspark.sql.DataFrame`` with a dummy class on Python 3.12+, and every mocked
test kept passing because the mock stood in for the very class that was broken.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

pyspark = pytest.importorskip("pyspark", reason="integration tests require pyspark")

# Pin the workers to the interpreter running the tests. Spark otherwise launches
# workers with whatever `python3` is first on PATH, which on macOS is the system
# 3.9 — every Python-side operation then dies with PYTHON_VERSION_MISMATCH, and
# the failure looks like a Ducta bug rather than an environment one.
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)


@pytest.fixture(scope="session")
def spark():
    """A minimal local Spark session, shared across the integration tests.

    Single-threaded and stripped of the UI/shuffle-parallelism defaults, because
    session startup dominates the runtime of these tests.
    """
    from pyspark.sql import SparkSession

    session = (
        SparkSession.builder.master("local[1]")
        .appName("ducta-integration-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.default.parallelism", "1")
        .config("spark.sql.adaptive.enabled", "false")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture
def people_df(spark):
    """A small, typed DataFrame used by the gate round-trip tests."""
    return spark.createDataFrame(
        [(1, "ana", 10), (2, "bo", 20), (3, "cy", 30)],
        "id INT, name STRING, value INT",
    )


@pytest.fixture
def project_dir(tmp_path_factory):
    """An isolated directory for scaffold-and-run tests."""
    path = tmp_path_factory.mktemp("ducta_project")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session")
def ducta_cli() -> list:
    """Argv prefix that invokes the Ducta CLI in this interpreter."""
    import sys

    return [sys.executable, "-c", "from ducta.console.wrapper import main; main()"]


def find_written_files(root: Path, suffix: str) -> list:
    """Collect data files Spark wrote under *root*, ignoring _SUCCESS/.crc markers."""
    return [
        p for p in root.rglob(f"*{suffix}") if not p.name.startswith((".", "_")) and p.is_file()
    ]
