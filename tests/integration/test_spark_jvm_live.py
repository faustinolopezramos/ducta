"""``ducta.spark_jvm`` against a real session: every handle Ducta relies on is there."""

from __future__ import annotations

import pytest

from ducta import spark_jvm

pytestmark = pytest.mark.spark


def test_the_handles_exist_on_a_real_session(spark):
    assert spark_jvm.spark_major(spark) >= 3
    assert spark_jvm.java_version(spark)
    assert spark_jvm.hadoop_configuration(spark) is not None
    assert "id" in spark_jvm.schema_tree(spark.range(1))


def test_a_class_that_is_not_on_the_classpath_is_not_found(spark):
    """py4j answers any dotted name with a JavaPackage: only loading the class tells."""
    assert spark_jvm.jvm_has_class(spark, "java.lang.String") is True
    assert spark_jvm.jvm_has_class(spark, "com.nonexistent.zzz.Missing") is False
