"""The Delta jar a local session loads must be the build for the installed Spark."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from ducta.setting.session import local_delta_configs


@pytest.mark.parametrize(
    "pyspark, package",
    [
        ("4.2.1", "io.delta:delta-spark_4.2_2.13:4.4.1"),
        ("4.1.1", "io.delta:delta-spark_4.1_2.13:4.4.1"),
        ("4.0.2", "io.delta:delta-spark_2.13:4.0.1"),
        ("3.5.9", "io.delta:delta-spark_2.12:3.2.1"),
    ],
)
def test_each_spark_minor_gets_its_build(monkeypatch, pyspark, package):
    monkeypatch.setitem(sys.modules, "pyspark", SimpleNamespace(__version__=pyspark))
    assert local_delta_configs()["spark.jars.packages"] == package


def test_an_unknown_spark_gets_no_delta(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyspark", SimpleNamespace(__version__="4.3.0"))
    assert local_delta_configs() == {}


def test_an_explicit_package_wins(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyspark", SimpleNamespace(__version__="4.2.1"))
    assert local_delta_configs("io.delta:x:1")["spark.jars.packages"] == "io.delta:x:1"
