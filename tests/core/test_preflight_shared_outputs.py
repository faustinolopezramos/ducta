"""Two datasets on one path used to pass validation and collide at run time."""

from __future__ import annotations

from types import SimpleNamespace

from ducta.core.preflight import PreflightReport, _check_shared_output_paths


def _context(output_config, pipelines=None, nodes=None):
    return SimpleNamespace(
        execution_mode="local",
        output_path="out",
        output_config=output_config,
        pipelines=pipelines or {},
        nodes_config=nodes or {},
        global_config={"env": "dev"},
    )


def _check(context, node_configs, pipeline="p"):
    report = PreflightReport(pipeline_name=pipeline)
    _check_shared_output_paths(report, context, pipeline, node_configs)
    return report


NODES = {"a": {"output": ["s.t.a"]}, "b": {"output": ["s.t.b"]}}


def test_two_outputs_on_one_path_are_an_error():
    report = _check(
        _context({"s.t.a": {"filepath": "out/shared"}, "s.t.b": {"filepath": "out/shared/"}}),
        NODES,
    )
    assert len(report.errors) == 1
    assert "s.t.a, s.t.b" in report.errors[0] and "out/shared" in report.errors[0]


def test_different_paths_are_fine():
    report = _check(
        _context({"s.t.a": {"filepath": "out/a"}, "s.t.b": {"filepath": "out/b"}}), NODES
    )
    assert report.errors == [] and report.warnings == []


def test_keys_without_a_filepath_do_not_collide():
    assert _check(_context({"s.t.a": {}, "s.t.b": {}}), NODES).errors == []


def test_only_appending_is_a_warning():
    shared = {"filepath": "out/log", "write_mode": "append"}
    report = _check(_context({"s.t.a": shared, "s.t.b": dict(shared)}), NODES)
    assert report.errors == []
    assert "collide" in report.warnings[0]


def test_one_overwrite_among_appends_is_an_error():
    report = _check(
        _context(
            {
                "s.t.a": {"filepath": "out/log", "write_mode": "append"},
                "s.t.b": {"filepath": "out/log"},
            }
        ),
        NODES,
    )
    assert len(report.errors) == 1


def test_another_pipeline_writing_the_path_is_a_warning():
    nodes = {"a": {"output": ["s.t.a"]}, "z": {"output": ["s.t.z"]}}
    context = _context(
        {"s.t.a": {"filepath": "out/shared"}, "s.t.z": {"filepath": "out/shared"}},
        pipelines={"p": {"nodes": ["a"]}, "other": {"nodes": ["z"]}},
        nodes=nodes,
    )
    report = _check(context, {"a": nodes["a"]})
    assert report.errors == []
    assert "'other'" in report.warnings[0]


def test_a_stream_node_is_not_looked_at():
    nodes = {"a": {"output": ["s.t.a"]}, "b": {"output": ["s.t.b"], "streaming": {"trigger": "5s"}}}
    report = _check(
        _context({"s.t.a": {"filepath": "out/x"}, "s.t.b": {"filepath": "out/x"}}), nodes
    )
    assert report.errors == []
