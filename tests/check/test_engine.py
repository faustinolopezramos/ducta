"""Unit tests for ducta.check.engine: SanityPhaseRunner and ValidationPhaseRunner."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from ducta.check.core import QualityChecksFailed, QualityConfigError
from ducta.check.engine import SanityPhaseRunner, ValidationPhaseRunner
from ducta.check.storage import FileStorageBackend


class TestRunPreflightChecks:
    def test_node_fail_fast_override_does_not_abort_entire_preflight(self):
        """Regression: a node's own sanity_checks.fail_fast=true must only fail
        that node, not abort scanning the rest of the pipeline, when the runner
        itself was constructed with fail_fast=False."""
        pipeline_config = {
            "nodes": {
                "strict_node": {
                    "sanity_checks": {
                        "enabled": True,
                        "fail_fast": True,
                        "checks": {"empty_dataset": {}},
                    },
                },
                "other_node": {
                    "sanity_checks": {
                        "enabled": True,
                        "checks": {"empty_dataset": {}},
                    },
                },
            }
        }
        runner = SanityPhaseRunner(fail_fast=False)

        with patch("ducta.gate.input.InputLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load_inputs.return_value = [pd.DataFrame()]
            reports = runner.run_preflight_checks(pipeline_config, context=object())

        assert set(reports.keys()) == {"strict_node", "other_node"}
        assert reports["strict_node"].passed is False
        assert reports["other_node"].passed is False

    def test_unknown_check_type_fails_the_report_instead_of_being_skipped(self):
        """Regression: a check referenced by a name/type not in
        QUALITY_CHECKS_REGISTRY (typo, or a quality extension that failed to
        load) used to just log a warning and `continue` — dropped from the
        report entirely, so `report.passed` never reflected it."""
        pipeline_config = {
            "nodes": {
                "node_a": {
                    "sanity_checks": {
                        "enabled": True,
                        "checks": {"bogus_check": {"type": "does_not_exist"}},
                    },
                },
            }
        }
        runner = SanityPhaseRunner(fail_fast=False)

        with patch("ducta.gate.input.InputLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load_inputs.return_value = [pd.DataFrame()]
            reports = runner.run_preflight_checks(pipeline_config, context=object())

        report = reports["node_a"]
        assert report.passed is False
        assert any("does_not_exist" in r.message for r in report.results)

    def test_runner_fail_fast_still_aborts(self):
        """When the runner itself is fail_fast, a failing node still aborts
        the whole preflight (unchanged behavior)."""
        pipeline_config = {
            "nodes": {
                "a": {
                    "sanity_checks": {"enabled": True, "checks": {"empty_dataset": {}}},
                },
                "b": {
                    "sanity_checks": {"enabled": True, "checks": {"empty_dataset": {}}},
                },
            }
        }
        runner = SanityPhaseRunner(fail_fast=True)

        with patch("ducta.gate.input.InputLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load_inputs.return_value = [pd.DataFrame()]
            with pytest.raises(Exception):
                runner.run_preflight_checks(pipeline_config, context=object())


class TestValidationPhaseRunnerFailFast:
    def test_fail_fast_report_score_reflects_failure(self, tmp_path):
        """Regression: a report persisted during a fail-fast abort must not be
        stuck at the QualityReport dataclass default score of 1.0."""
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=True)
        df = pd.DataFrame({"id": [1, 2, 3]})

        with pytest.raises(QualityChecksFailed) as exc_info:
            runner.run(
                dataset_name="ds",
                df=df,
                config={"checks": {"row_count": {"min": 1000}}},
            )

        saved = storage.load_report(exc_info.value.run_id, "ds")
        assert saved is not None
        assert saved["score"] < 1.0


class TestValidationPhaseRunnerUnknownCheckType:
    def test_unknown_check_type_fails_the_report(self, tmp_path):
        # ERROR-severity results always raise QualityChecksFailed once all
        # checks finish, even outside fail_fast (see the trailing
        # `if not self.fail_fast: ... if errors: raise` in engine.py) — the
        # point under test is that the unknown-type result is an ERROR that
        # reaches that check at all, instead of being silently skipped.
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        with pytest.raises(QualityChecksFailed) as exc_info:
            runner.run(
                dataset_name="ds",
                df=df,
                config={"checks": {"bogus_check": {"type": "does_not_exist"}}},
            )

        assert any("does_not_exist" in r.message for r in exc_info.value.results)

    def test_unknown_check_type_aborts_immediately_under_fail_fast(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=True)
        df = pd.DataFrame({"id": [1, 2, 3]})

        with pytest.raises(QualityChecksFailed):
            runner.run(
                dataset_name="ds",
                df=df,
                config={"checks": {"bogus_check": {"type": "does_not_exist"}}},
            )


class TestValidationPhaseRunnerGateFailsClosed:
    def test_malformed_gate_config_fails_the_node_instead_of_passing_silently(self, tmp_path):
        """Regression: `max_errors: null` (a plausible typo for "disable this")
        used to raise a bare TypeError inside QualityGateEvaluator.from_config
        that engine.py swallowed with `except Exception: logger.exception(...)`
        (no re-raise) — dq_gate_result stayed None and the node proceeded as if
        the gate had passed. A gate the user explicitly configured must fail
        closed, not open, when it can't be evaluated."""
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        with pytest.raises(QualityConfigError):
            runner.run(
                dataset_name="ds",
                df=df,
                config={"checks": {}, "quality_gate": {"max_errors": None}},
            )


class TestValidationPhaseRunnerPersistenceFailureVisibility:
    """Regression: a persistence failure (report/baseline/history) only
    logged a warning — invisible to whatever reads the execution response.
    Not a check failure (the DQ result itself is still valid), but a real
    operational problem that was easy to miss."""

    def test_report_save_failure_is_visible_on_the_returned_report(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        storage.save_report = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        report = runner.run(dataset_name="ds", df=df, config={"checks": {}})

        assert any("disk full" in w for w in report.persistence_warnings)
        assert report.passed is True  # a persistence failure isn't a DQ failure

    def test_clean_run_has_no_persistence_warnings(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        report = runner.run(dataset_name="ds", df=df, config={"checks": {}})

        assert report.persistence_warnings == []


class TestValidationPhaseRunnerPipelineScoping:
    def test_same_dataset_name_different_pipelines_do_not_collide(self, tmp_path):
        """Regression: two pipelines with a node of the same name must persist
        independent reports/history, not overwrite one another."""
        storage = FileStorageBackend(str(tmp_path))
        runner = ValidationPhaseRunner(storage_backend=storage, fail_fast=False)
        df = pd.DataFrame({"id": [1, 2, 3]})

        report_a = runner.run(
            dataset_name="ds",
            df=df,
            config={"checks": {}},
            run_id="run1",
            pipeline_name="pipe_a",
        )
        report_b = runner.run(
            dataset_name="ds",
            df=df,
            config={"checks": {}},
            run_id="run1",
            pipeline_name="pipe_b",
        )

        assert report_a.run_id == report_b.run_id == "run1"
        assert storage.load_report("run1", "ds", pipeline_name="pipe_a") is not None
        assert storage.load_report("run1", "ds", pipeline_name="pipe_b") is not None
        history_a = storage.load_history("ds", pipeline_name="pipe_a")
        history_b = storage.load_history("ds", pipeline_name="pipe_b")
        assert len(history_a) == 1
        assert len(history_b) == 1
