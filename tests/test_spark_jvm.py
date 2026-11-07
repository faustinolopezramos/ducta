"""``ducta.spark_jvm``: PySpark's private JVM handles, or None when there are none."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta import spark_jvm


class _ConnectSession:
    """Spark Connect: no ``_jvm``, and ``sparkContext`` raises."""

    version = "4.2.0"

    @property
    def sparkContext(self):
        raise RuntimeError("[JVM_ATTRIBUTE_NOT_SUPPORTED] sparkContext")


@pytest.mark.parametrize(
    "version, major", [("3.5.9", 3), ("4.2.0", 4), ("", 0), ("unknown", 0), (None, 0)]
)
def test_spark_major(version, major):
    assert spark_jvm.spark_major(SimpleNamespace(version=version)) == major
    if isinstance(version, str):
        assert spark_jvm.spark_major(version) == major


def test_spark_4_packages_are_scala_2_13():
    assert spark_jvm.scala_suffix("4.2.0") == "2.13"
    assert spark_jvm.scala_suffix("3.5.0") == "2.12"


def test_jvm_from_a_session_or_its_context():
    gateway = object()
    assert spark_jvm.jvm(SimpleNamespace(_jvm=gateway)) is gateway
    assert spark_jvm.jvm(SimpleNamespace(sparkContext=SimpleNamespace(_jvm=gateway))) is gateway


def test_no_jvm_under_spark_connect():
    session = _ConnectSession()
    assert spark_jvm.jvm(session) is None
    assert spark_jvm.hadoop_configuration(session) is None
    assert spark_jvm.java_version(session) is None
    assert spark_jvm.jvm_has_package(session, "com.databricks.spark.xml") is False


def test_a_missing_java_package_is_false():
    class Gateway:
        def __getattr__(self, name):
            if name == "xml":
                raise AttributeError(name)
            return self

    assert (
        spark_jvm.jvm_has_package(SimpleNamespace(_jvm=Gateway()), "com.databricks.spark.xml")
        is False
    )


def test_java_version_reads_the_system_property():
    system = SimpleNamespace(
        getProperty=lambda key: "17" if key == "java.specification.version" else None
    )
    gateway = SimpleNamespace(java=SimpleNamespace(lang=SimpleNamespace(System=system)))
    assert spark_jvm.java_version(SimpleNamespace(_jvm=gateway)) == "17"


def test_schema_tree_prefers_the_public_api():
    df = SimpleNamespace(schema=SimpleNamespace(treeString=lambda: "root\n |-- id: long"))
    assert spark_jvm.schema_tree(df) == "root\n |-- id: long"


def test_schema_tree_falls_back_to_the_jvm_then_to_nothing():
    tree = SimpleNamespace(treeString=lambda: "root")
    df = SimpleNamespace(schema=object(), _jdf=SimpleNamespace(schema=lambda: tree))
    assert spark_jvm.schema_tree(df) == "root"
    assert spark_jvm.schema_tree(SimpleNamespace(schema=object())) == ""
