"""A ``${...}`` that no variable defines must be reported by the preflight.

``${paths.inpt}`` (a typo of ``${paths.input}``) stays in the path as written.
``ducta check`` passed, and the run ended "skipped for missing inputs" without
naming the path that was never going to exist.
"""

from __future__ import annotations

from ducta.core.preflight import PreflightReport, _check_unresolved_placeholders


def _check(node, inputs=None, outputs=None):
    report = PreflightReport(pipeline_name="p")
    _check_unresolved_placeholders(report, "n", node, inputs or {}, outputs or {})
    return report


NODE = {"input": {"df": "raw.orders"}, "output": ["silver.orders"]}


def test_a_leftover_placeholder_in_a_path_is_an_error():
    report = _check(NODE, inputs={"raw.orders": {"filepath": "${paths.inpt}/orders.csv"}})
    assert len(report.errors) == 1
    assert "${paths.inpt}" in report.errors[0] and "raw.orders" in report.errors[0]
    assert "filepath" in report.errors[0]


def test_an_output_path_is_checked_too():
    report = _check(NODE, outputs={"silver.orders": {"path": "${paths.outpt}/silver"}})
    assert len(report.errors) == 1 and "${paths.outpt}" in report.errors[0]


def test_resolved_paths_say_nothing():
    report = _check(
        NODE,
        inputs={"raw.orders": {"filepath": "data/orders.csv"}},
        outputs={"silver.orders": {"path": "data/dev/silver"}},
    )
    assert not report.errors and not report.warnings


def test_a_placeholder_in_an_option_is_a_warning_not_an_error():
    # It may be meant literally (a query, a pattern): only a location is certainly broken.
    report = _check(NODE, inputs={"raw.orders": {"options": {"query": "select '${today}'"}}})
    assert not report.errors
    assert len(report.warnings) == 1 and "${today}" in report.warnings[0]


def test_a_streaming_nodes_inline_paths_are_checked():
    node = {"type": "streaming", "stream": {"input": {"options": {"path": "${paths.x}/e"}}}}
    report = _check(node)
    assert len(report.errors) == 1 and "${paths.x}" in report.errors[0]


def test_a_dataset_the_catalog_does_not_have_is_left_to_the_io_key_check():
    assert not _check(NODE).errors
