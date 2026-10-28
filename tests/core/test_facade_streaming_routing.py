"""A stream started by the hybrid executor is found, stopped and read through the facade."""

from __future__ import annotations

from types import SimpleNamespace

from ducta.core.executors.facade import PipelineExecutor


class _Manager:
    def __init__(self, running):
        self.running = list(running)
        self.stopped = []

    def list_running_pipelines(self):
        return [{"execution_id": i} for i in self.running]

    def has_execution(self, execution_id):
        return execution_id in self.running

    def stop_pipeline(self, execution_id, graceful, timeout_seconds):
        self.stopped.append(execution_id)
        return True

    def get_pipeline_status(self, execution_id):
        return {"execution_id": execution_id}


def _facade(streaming=None, hybrid=None):
    facade = object.__new__(PipelineExecutor)
    facade._streaming_executor = SimpleNamespace(streaming_manager=streaming) if streaming else None
    facade._hybrid_executor = SimpleNamespace(streaming_manager=hybrid) if hybrid else None
    return facade


def test_running_ids_include_the_hybrid_ones():
    facade = _facade(streaming=_Manager(["s1"]), hybrid=_Manager(["h1", "s1"]))
    assert facade.get_running_execution_ids() == ["s1", "h1"]


def test_nothing_streamed_means_no_ids():
    assert _facade().get_running_execution_ids() == []


def test_a_hybrid_stream_is_stopped_by_its_own_manager():
    streaming, hybrid = _Manager(["s1"]), _Manager(["h1"])
    facade = _facade(streaming=streaming, hybrid=hybrid)
    assert facade.stop_streaming_pipeline("h1") is True
    assert (hybrid.stopped, streaming.stopped) == (["h1"], [])
    assert facade.get_streaming_pipeline_status("h1") == {"execution_id": "h1"}


def test_other_ids_still_go_to_the_streaming_executor():
    streaming, hybrid = _Manager(["s1"]), _Manager(["h1"])
    facade = _facade(streaming=streaming, hybrid=hybrid)
    assert facade.stop_streaming_pipeline("s1") is True
    assert (hybrid.stopped, streaming.stopped) == ([], ["s1"])
