"""``ducta.runtime_check``: version combinations known to fail, said before a run.

Every rule here was seen failing: Spark 3.5 on Python 3.14 (RecursionError while
pickling), Spark 4 on Java 11 (does not start), pandas 3 (None reaches Spark as
the text 'NaN'), Arrow on Spark 3.5 with Java 21.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from ducta import runtime_check
from ducta.runtime_check import Stack, problems

GOOD = Stack(python=(3, 13), pyspark="4.2.0", pandas="2.3.3", delta="4.4.1", java=17)


def _one(stack: Stack) -> str:
    [found] = problems(stack)
    return found


def test_a_supported_stack_has_no_problems():
    assert problems(GOOD) == []
    assert problems(Stack(python=(3, 11), pyspark="3.5.9", pandas="2.2.0", java=17)) == []


def test_without_pyspark_nothing_spark_related_is_reported():
    assert problems(Stack(python=(3, 14), pandas="3.1.1")) == []


def test_spark_3_on_python_3_14():
    found = _one(Stack(python=(3, 14), pyspark="3.5.9", java=17))
    assert "Python 3.14" in found and "PySpark 4.2" in found


def test_spark_4_on_an_old_java():
    found = _one(Stack(python=(3, 13), pyspark="4.2.0", java=11))
    assert "Java 17 or 21" in found and "11" in found


def test_no_java_at_all():
    assert "no Java was found" in _one(Stack(python=(3, 13), pyspark="4.2.0", java=None))


def test_arrow_on_spark_3_with_java_21():
    assert "Arrow" in _one(Stack(python=(3, 13), pyspark="3.5.9", java=21))


def test_pandas_3():
    found = _one(Stack(python=(3, 13), pyspark="4.2.0", pandas="3.1.1", java=17))
    assert "'NaN'" in found and "pandas<3" in found


def test_a_delta_build_for_another_spark():
    found = _one(Stack(python=(3, 13), pyspark="4.2.0", delta="3.3.3", java=17))
    assert "delta-spark 3.3.3" in found and "ducta[delta]" in found


@pytest.mark.parametrize(
    "output, major",
    [
        ('openjdk version "17.0.12" 2024-07-16', 17),
        ('java version "1.8.0_402"', 8),
        ('openjdk version "21" 2023-09-19', 21),
        ("no version here", None),
    ],
)
def test_java_major_parses_java_version(monkeypatch, tmp_path, output, major):
    java = tmp_path / "bin" / "java"
    java.parent.mkdir()
    java.write_text("")
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=output, stdout="")
    )
    assert runtime_check._java_major() == major


def test_no_java_on_the_machine(monkeypatch):
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setattr(runtime_check.shutil, "which", lambda name: None)
    assert runtime_check._java_major() is None


def test_java_is_not_looked_for_without_pyspark(monkeypatch):
    monkeypatch.setattr(runtime_check, "_version", lambda name: None)
    monkeypatch.setattr(
        runtime_check, "_java_major", lambda: pytest.fail("ran java without pyspark")
    )
    assert runtime_check.detect().java is None


def test_the_real_environment_is_read_once():
    runtime_check.stack_warnings.cache_clear()
    first = runtime_check.stack_warnings()
    assert runtime_check.stack_warnings() is first
    assert all(isinstance(w, str) for w in first)


# ── Spark defaults a project leaves unset ───────────────────────────────────────
# Seen 2026-11-06: on Spark 4.2 CAST('abc' AS INT), 1/0 and CAST(300 AS TINYINT)
# stop the run; Spark 3.5 returned NULL, NULL and 44. The session time zone is the
# machine's unless the project sets it.

ANSI = runtime_check.ANSI_KEY
ZONE = runtime_check.TIMEZONE_KEY


def test_spark_4_without_the_ansi_key_says_so():
    found = runtime_check.spark_config_problems("4.2.0", {ZONE: "UTC"})
    [ansi] = found
    assert ANSI in ansi and "Spark 3.5" in ansi


@pytest.mark.parametrize("value", ["true", "false", True])
def test_setting_the_ansi_key_to_any_value_silences_it(value):
    assert runtime_check.spark_config_problems("4.2.0", {ANSI: value, ZONE: "UTC"}) == []


def test_spark_3_is_not_told_about_ansi():
    assert runtime_check.spark_config_problems("3.5.9", {ZONE: "UTC"}) == []


def test_an_unset_time_zone_names_this_machines_zone():
    [zone] = runtime_check.spark_config_problems("3.5.9", {}, local_zone="CST")
    assert ZONE in zone and "(CST)" in zone


def test_both_are_said_on_spark_4_with_no_spark_config():
    found = runtime_check.spark_config_problems("4.2.0", None)
    assert len(found) == 2


def test_without_pyspark_nothing_is_said():
    assert runtime_check.spark_config_problems(None, {}) == []


def test_config_warnings_reads_the_installed_pyspark(monkeypatch):
    monkeypatch.setattr(runtime_check, "_version", lambda name: "4.2.0")
    monkeypatch.setattr(runtime_check, "local_zone", lambda: "UTC")
    found = runtime_check.config_warnings({})
    assert any(ANSI in w for w in found) and any("(UTC)" in w for w in found)
