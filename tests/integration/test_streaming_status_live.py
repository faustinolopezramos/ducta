"""The streaming status of a real running stream, read the way the API reads it."""

from __future__ import annotations

import time

import pytest

from ducta.api.services.streaming_status import streaming_status


@pytest.fixture
def engine(spark, tmp_path, monkeypatch):
    from ducta.console.template import TemplateGenerator, TemplateType
    from ducta.core.executors import PipelineExecutor
    from ducta.setting.project_loader import load_project_v2

    root = tmp_path / "sb"
    TemplateGenerator(root).generate_project(TemplateType.STREAMING_BASIC, "sb")
    monkeypatch.chdir(root)
    monkeypatch.syspath_prepend(str(root))
    from ducta.api.execution.runner import normalize_execution_context_paths

    context = load_project_v2(root, "dev")
    # As the API runner does: relative paths would resolve against the shared
    # Spark JVM's working directory, not this test's.
    normalize_execution_context_paths(context, root)
    engine = PipelineExecutor(context)
    yield engine
    engine.shutdown()


def test_a_running_stream_reports_its_queries_and_throughput(engine):
    assert streaming_status("api-1", engine).pipelines == []  # nothing streaming yet

    engine.run_streaming_pipeline("events_stream", mode="async")
    deadline = time.time() + 60
    while time.time() < deadline:
        resp = streaming_status("api-1", engine)
        nodes = [n for p in resp.pipelines for n in p.nodes]
        if nodes and any(n.processed_rows_per_second is not None for n in nodes):
            break
        time.sleep(0.5)
    else:
        pytest.fail(f"no progress reported within 60s: {resp.model_dump()}")

    (pipeline,) = resp.pipelines
    assert pipeline.pipeline_name == "events_stream"
    assert pipeline.status == "running" and pipeline.active_queries == pipeline.total_queries
    assert {n.node for n in pipeline.nodes} == {"ingest_events", "clean_events"}
    assert all(n.state == "active" for n in pipeline.nodes)
    resp.model_dump_json()  # serializable as the API returns it


def test_a_stream_that_failed_to_start_is_reported_not_hidden(engine, tmp_path):
    import shutil

    shutil.rmtree(tmp_path / "sb" / "data" / "events")  # the file stream's source
    engine.run_streaming_pipeline("events_stream", mode="async")
    deadline = time.time() + 30
    while time.time() < deadline:
        resp = streaming_status("api-1", engine)
        if resp.pipelines and resp.pipelines[0].status not in ("starting", "running"):
            break
        time.sleep(0.5)
    (pipeline,) = resp.pipelines
    assert pipeline.status in ("partial_failure", "failed", "error")
    failed = [n for n in pipeline.nodes if n.state == "failed"]
    assert failed and "events" in (failed[0].error or "")
