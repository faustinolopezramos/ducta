"""Dataset contracts: `sanity_checks.inputs.<dataset>` validates each input.

Before, `sanity_checks` validated exactly one input, chosen by `input_index`.
Format 2 declares checks on the dataset in the catalog; they compile to one
block per input here, and a dataset read by several nodes is checked once per
run, with the same verdict for every consumer.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.check.core import QualityCheckError
from ducta.core.errors import SanityCheckFailedError
from ducta.core.execution.quality import QualityCheckExecutor
from ducta.core.ledger import ledger_for
from tests.core.fakes import FakeContext

#: How a failing fail_fast sanity check surfaces (same as the single-input form).
_FAILED = (QualityCheckError, SanityCheckFailedError)

GOOD = pd.DataFrame({"id": [1, 2, 3]})
EMPTY = pd.DataFrame({"id": []})


def _node(inputs, contracts):
    return {"input": inputs, "sanity_checks": {"inputs": contracts}}


def _executor(ctx=None):
    return QualityCheckExecutor(ctx or FakeContext())


def test_each_input_is_checked_against_its_own_contract():
    ex = _executor()
    node = _node(
        ["orders", "customers"],
        {
            "orders": {"checks": {"empty_dataset": {}}},
            "customers": {"checks": {"row_count": {"min": 2}}},
        },
    )
    reports = ex.run_sanity_checks([GOOD, GOOD], node, "n")
    assert len(reports) == 2 and all(r.passed for r in reports)


def test_the_second_input_is_really_checked_not_just_input_zero():
    """The old form only ever looked at one input."""
    ex = _executor()
    node = _node(["orders", "customers"], {"customers": {"checks": {"empty_dataset": {}}}})
    with pytest.raises(_FAILED):
        ex.run_sanity_checks([GOOD, EMPTY], node, "n")


def test_named_inputs_map_parameters_to_datasets():
    ex = _executor()
    node = _node(
        {"left": "orders", "right": "customers"}, {"customers": {"checks": {"empty_dataset": {}}}}
    )
    with pytest.raises(_FAILED):
        ex.run_sanity_checks([GOOD, EMPTY], node, "n")


def test_a_contract_is_checked_once_per_run_and_every_consumer_gets_its_verdict():
    ctx = FakeContext()
    ledger_for(ctx).run_id = "run-1"
    contracts = {"orders": {"checks": {"empty_dataset": {}}}}

    with pytest.raises(_FAILED):
        _executor(ctx).run_sanity_checks([EMPTY], _node(["orders"], contracts), "first")
    # A second consumer is blocked by the same verdict, even handed good data:
    # the dataset was judged once for this run.
    with pytest.raises(_FAILED):
        _executor(ctx).run_sanity_checks([GOOD], _node(["orders"], contracts), "second")

    quality = [q for q in ledger_for(ctx).quality_results if q.get("phase") == "contract"]
    # judged once: at most the first consumer's verdict is recorded
    assert len(quality) <= 1


def test_a_new_run_judges_the_dataset_again():
    ctx = FakeContext()
    contracts = {"orders": {"checks": {"empty_dataset": {}}}}
    ledger_for(ctx).run_id = "run-1"
    with pytest.raises(_FAILED):
        _executor(ctx).run_sanity_checks([EMPTY], _node(["orders"], contracts), "n")
    ledger_for(ctx).run_id = "run-2"
    assert _executor(ctx).run_sanity_checks([GOOD], _node(["orders"], contracts), "n")


def test_contract_results_reach_the_certificate_with_their_dataset():
    ctx = FakeContext()
    ledger_for(ctx).run_id = "run-cert"
    _executor(ctx).run_sanity_checks(
        [GOOD], _node(["orders"], {"orders": {"checks": {"empty_dataset": {}}}}), "n"
    )
    entry = [q for q in ledger_for(ctx).quality_results if q.get("phase") == "contract"][0]
    assert entry["dataset"] == "orders" and entry["passed"] is True


def test_the_single_input_form_still_works():
    ex = _executor()
    node = {
        "input": ["a", "b"],
        "sanity_checks": {"input_index": 1, "checks": {"empty_dataset": {}}},
    }
    with pytest.raises(_FAILED):
        ex.run_sanity_checks([GOOD, EMPTY], node, "n")
