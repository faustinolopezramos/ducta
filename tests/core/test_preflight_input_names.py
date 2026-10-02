"""``inputs: {param: dataset}`` binds by keyword, so each key must be a parameter.

Without this check a misspelt key fails only when the node runs, after every earlier
node has already written its output.
"""

from __future__ import annotations

from ducta.core import preflight
from ducta.core.preflight import PreflightReport


class _Loader:
    def __init__(self, func):
        self._func = func

    def load(self, node):
        return self._func


def _check(func, inputs):
    report = PreflightReport(pipeline_name="p")
    node = {"module": "m", "function": "f", "input": inputs}
    preflight._check_node_function(report, _Loader(func), "n", node, requires_dates=False)
    return report


def transform(raw_data, start_date=None, end_date=None):
    return raw_data


def two(left, right):
    return left


def anything(**kwargs):
    return None


def test_a_matching_key_passes():
    assert _check(transform, {"raw_data": "ds"}).ok


def test_a_misspelt_key_is_an_error_naming_the_parameters():
    report = _check(transform, {"raw_dat": "ds"})
    assert not report.ok
    message = report.errors[0]
    assert "inputs key 'raw_dat' is not a parameter" in message
    assert "did you mean 'raw_data'" in message
    assert "would fail when it runs" in message


def test_every_wrong_key_is_reported():
    report = _check(two, {"left": "a", "rigth": "b", "middle": "c"})
    assert len([e for e in report.errors if "inputs key" in e]) == 2


def test_the_injected_dates_are_not_offered_as_inputs():
    report = _check(transform, {"raw_dta": "ds"})
    assert "(raw_data)" in report.errors[0]


def test_a_function_taking_kwargs_accepts_any_key():
    assert _check(anything, {"whatever": "ds"}).ok


def test_the_list_form_binds_by_position_and_is_not_judged_by_name():
    assert _check(two, ["a", "b"]).ok
