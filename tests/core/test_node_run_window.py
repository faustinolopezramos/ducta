"""The run window reaches a node function only when the function asks for it.

Every node was called with ``start_date=``/``end_date=`` keywords, so a plain
``def clean(orders): ...`` — the natural way to write a transformation, and what
the docs show — failed with "unexpected keyword argument 'start_date'", while
preflight insisted on the parameters whenever a pipeline required dates. The
window is now passed to functions that declare it (or take ``**kwargs``).
"""

from __future__ import annotations

from ducta.core.commands import MLNodeCommand, NodeCommand


def _run(func, inputs=("df",), names=None):
    return NodeCommand(
        func, list(inputs), "2026-01-01", "2026-01-31", "node", input_names=names
    ).execute()


def test_a_function_without_the_window_gets_only_its_data():
    assert _run(lambda orders: orders, names=["orders"]) == "df"


def test_a_function_declaring_the_window_receives_it():
    assert _run(lambda df, start_date, end_date: (start_date, end_date)) == (
        "2026-01-01",
        "2026-01-31",
    )


def test_a_function_declaring_one_bound_receives_only_that_one():
    assert _run(lambda df, end_date=None: end_date) == "2026-01-31"


def test_kwargs_receive_the_window():
    assert _run(lambda df, **kw: sorted(kw)) == ["end_date", "start_date"]


def test_ml_nodes_follow_the_same_rule():
    cmd = MLNodeCommand(
        lambda features, ml_context=None: features,
        ["df"],
        "2026-01-01",
        "2026-01-31",
        "train",
        model_version="1",
        input_names=["features"],
    )
    assert cmd.execute() == "df"


def test_preflight_accepts_a_function_without_the_window(tmp_path, monkeypatch):
    """A pipeline that requires dates no longer forces them on every function."""
    from ducta.core.preflight import PreflightReport, _check_node_function

    module = tmp_path / "plain_nodes.py"
    module.write_text("def clean(orders):\n    return orders\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    class Loader:
        def load(self, node):
            import plain_nodes

            return plain_nodes.clean

    report = PreflightReport("p")
    _check_node_function(
        report, Loader(), "clean", {"module": "plain_nodes", "function": "clean"}, True
    )
    assert report.errors == []
