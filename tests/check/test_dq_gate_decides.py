"""A declared data-quality gate decides, as the sanity gate does: with
``behavior: warn_only`` failing checks are reported and the node carries on."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.check.core import QualityChecksFailed, QualityGateBlocked
from ducta.core.execution.quality import QualityCheckExecutor


class _Ctx:
    nodes_config: dict = {}

    def __init__(self, out: str) -> None:
        self.global_config = {"output_path": out}


@pytest.fixture
def executor(tmp_path) -> QualityCheckExecutor:
    # Reports are written under output_path, here the test's own folder.
    return QualityCheckExecutor(_Ctx(str(tmp_path)))


FRAME = pd.DataFrame({"id": [1, 2, 3]})
FAILING = {"row_count": {"min": 1000}}


def _run(executor, dq):
    return executor.run_dq_checks(FRAME, {"data_quality": dq}, "n")


def test_warn_only_reports_and_carries_on(executor):
    report = _run(
        executor, {"checks": FAILING, "quality_gate": {"max_errors": 0, "behavior": "warn_only"}}
    )
    assert report is not None and not report.passed


def test_a_blocking_gate_still_blocks(executor):
    with pytest.raises(QualityGateBlocked):
        _run(
            executor,
            {"checks": FAILING, "quality_gate": {"max_errors": 0, "behavior": "skip_downstream"}},
        )


def test_without_a_gate_failures_still_fail_the_node(executor):
    with pytest.raises(QualityChecksFailed):
        _run(executor, {"checks": FAILING})


# ── where a pipeline run's reports go (Ducta storage convention) ─────────────


def test_reports_default_to_visible_quality_dir(executor, tmp_path):
    _run(executor, {"checks": {"row_count": {"min": 1}}})
    assert (tmp_path / "base" / "quality").is_dir()
    assert not (tmp_path / "base" / ".quality").exists()


def test_an_existing_legacy_dir_keeps_its_history(executor, tmp_path):
    (tmp_path / "base" / ".quality").mkdir(parents=True)
    _run(executor, {"checks": {"row_count": {"min": 1}}})
    assert any((tmp_path / "base" / ".quality").iterdir())
    assert not (tmp_path / "base" / "quality").exists()
