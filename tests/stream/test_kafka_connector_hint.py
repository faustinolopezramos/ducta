"""The Kafka connector Ducta suggests must exist for the running Spark.

Spark 4 is built for Scala 2.13: ``spark-sql-kafka-0-10_2.12:4.2.0`` is not on
Maven Central, so the hint has to follow the session's version.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.stream.readers import KafkaStreamingReader

MISSING = "Failed to find data source: kafka."


@pytest.mark.parametrize(
    "version, package",
    [
        ("4.2.1", "org.apache.spark:spark-sql-kafka-0-10_2.13:4.2.0"),
        ("3.5.9", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0"),
    ],
)
def test_the_hint_names_the_connector_for_this_spark(version, package):
    reader = KafkaStreamingReader({"spark": SimpleNamespace(version=version)})
    assert package in reader._augment_kafka_missing_datasource_message(MISSING)


def test_other_errors_are_left_alone():
    reader = KafkaStreamingReader({"spark": SimpleNamespace(version="4.2.1")})
    assert reader._augment_kafka_missing_datasource_message("boom") == "boom"
