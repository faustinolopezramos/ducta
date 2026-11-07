"""Which data source reads XML: Spark 4's own, or the spark-xml package on 3.5."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ducta.gate.readers import XMLReader, spark_xml_available, xml_format


def _jvm_with_xml(present: bool):
    class Gateway:
        def __getattr__(self, name):
            if name == "xml" and not present:
                raise AttributeError(name)
            return self

    return Gateway()


def test_spark_4_reads_xml_without_a_package():
    spark = SimpleNamespace(version="4.2.0", _jvm=_jvm_with_xml(False))
    assert xml_format(spark) == "xml"
    assert spark_xml_available(spark) is True


def test_spark_3_needs_spark_xml():
    assert xml_format(SimpleNamespace(version="3.5.9", _jvm=_jvm_with_xml(True))) == (
        "com.databricks.spark.xml"
    )
    assert xml_format(SimpleNamespace(version="3.5.9", _jvm=_jvm_with_xml(False))) is None


def test_the_reader_uses_spark_4s_source():
    spark = MagicMock()
    spark.version = "4.2.0"
    XMLReader({"spark": spark}).read("/data/a.xml", {"rowTag": "item"})
    spark.read.format.assert_called_once_with("xml")
