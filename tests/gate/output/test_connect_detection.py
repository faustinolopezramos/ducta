"""Spark Connect DataFrames are recognised without importing ``pyspark.sql.connect``.

On Spark 4 without the ``connect`` extra, importing it calls ``sys.exit(0)`` when
``__main__`` has no file: ``python -c``, ``python -m`` and spawned workers ended
with success having done nothing.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

from ducta.gate.output import dataframes

SRC = str(Path(__file__).resolve().parents[3] / "src")


def test_importing_the_module_does_not_import_spark_connect():
    code = (
        f"import sys; sys.path.insert(0, {SRC!r}); import ducta.gate.output.dataframes; "
        "print('pyspark.sql.connect' in sys.modules)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "False"


def test_a_connect_dataframe_is_a_spark_dataframe(monkeypatch):
    connect = types.new_class("DataFrame")
    module = types.ModuleType("pyspark.sql.connect.dataframe")
    module.DataFrame = connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyspark.sql.connect.dataframe", module)

    assert dataframes._connect_dataframe_class() is connect
    assert dataframes._DataFrameManager({}).is_spark_dataframe(connect()) is True


def test_nothing_is_a_connect_dataframe_when_connect_is_not_loaded(monkeypatch):
    monkeypatch.delitem(sys.modules, "pyspark.sql.connect.dataframe", raising=False)
    assert dataframes._connect_dataframe_class() is None
