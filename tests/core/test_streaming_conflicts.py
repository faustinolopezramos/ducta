"""Resource-conflict detection between a starting and an already-running pipeline.

`_check_resource_conflicts` compared the new pipeline against the dicts returned
by `list_running_pipelines()`. Those are *status snapshots*: they carry the
pipeline definition under "pipeline_config" and have no top-level "nodes" key, so
`extract_pipeline_nodes` returned an empty list, every running pipeline
contributed no resources, and the intersections were always empty. The check had
never reported a conflict.

It had no tests either, which is why nobody noticed.
"""

from __future__ import annotations

import pytest

from ducta.core.executors.streaming import StreamingExecutor
from tests.core.fakes import FakeContext


def _executor(nodes_config):
    """A StreamingExecutor with only the two attributes these methods touch."""
    executor = StreamingExecutor.__new__(StreamingExecutor)
    executor.context = FakeContext(nodes_config=nodes_config)
    return executor


def _kafka_node(topic):
    return {"input": {"format": "kafka", "options": {"subscribe": topic}}}


def _file_node(path):
    return {"input": {"format": "file_stream", "path": path}}


def _delta_out_node(path):
    return {"output": {"format": "delta", "path": path}}


def _running(nodes):
    """The shape `StreamingPipelineManager.get_pipeline_status` actually returns."""
    return {
        "execution_id": "exec-1",
        "pipeline_name": "other",
        "status": "running",
        "start_time": 0.0,
        "pipeline_config": {"nodes": nodes},
    }


class TestConflictsAreDetected:
    def test_a_shared_kafka_topic_conflicts(self):
        executor = _executor({"a": _kafka_node("orders"), "b": _kafka_node("orders")})

        conflicts = executor._check_resource_conflicts({"nodes": ["a"]}, [_running(["b"])])

        assert len(conflicts) == 1
        assert "orders" in conflicts[0]
        assert "Kafka" in conflicts[0]

    def test_a_shared_file_path_conflicts(self):
        executor = _executor({"a": _file_node("/data/in"), "b": _file_node("/data/in")})

        conflicts = executor._check_resource_conflicts({"nodes": ["a"]}, [_running(["b"])])

        assert any("File path conflict" in c for c in conflicts)

    def test_a_shared_delta_table_conflicts(self):
        executor = _executor({"a": _delta_out_node("/lake/t"), "b": _delta_out_node("/lake/t")})

        conflicts = executor._check_resource_conflicts({"nodes": ["a"]}, [_running(["b"])])

        assert any("Delta table conflict" in c for c in conflicts)

    def test_a_comma_separated_subscribe_is_split_into_topics(self):
        executor = _executor({"a": _kafka_node("orders,events"), "b": _kafka_node("events")})

        conflicts = executor._check_resource_conflicts({"nodes": ["a"]}, [_running(["b"])])

        assert len(conflicts) == 1
        assert "events" in conflicts[0]


class TestNonConflicts:
    def test_disjoint_resources_do_not_conflict(self):
        executor = _executor({"a": _kafka_node("orders"), "b": _kafka_node("shipments")})

        assert executor._check_resource_conflicts({"nodes": ["a"]}, [_running(["b"])]) == []

    def test_nothing_running_means_nothing_to_conflict_with(self):
        executor = _executor({"a": _kafka_node("orders")})

        assert executor._check_resource_conflicts({"nodes": ["a"]}, []) == []

    def test_a_snapshot_without_a_pipeline_config_is_tolerated(self):
        # Defensive: an older or partial status record must not raise.
        executor = _executor({"a": _kafka_node("orders")})
        snapshot = {"execution_id": "exec-1", "status": "running"}

        assert executor._check_resource_conflicts({"nodes": ["a"]}, [snapshot]) == []


class TestExtractionReadsTheDefinition:
    def test_resources_come_from_the_nested_pipeline_config(self):
        # The regression itself: passing the snapshot instead of its
        # "pipeline_config" yielded no nodes and therefore no resources.
        executor = _executor({"b": _kafka_node("orders")})
        snapshot = _running(["b"])

        from_snapshot = executor._extract_pipeline_resources(snapshot)
        from_config = executor._extract_pipeline_resources(snapshot["pipeline_config"])

        assert from_snapshot["kafka_topics"] == set()
        assert from_config["kafka_topics"] == {"orders"}
