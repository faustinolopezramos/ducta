"""run_summary: one table that joins tracked runs, registered models and certificates.

Everything runs against a real tracker and registry on the local backend, so what is
asserted is what a leaderboard pipeline would write.
"""

from __future__ import annotations

import json
import pickle
from types import SimpleNamespace

import pandas as pd
import pytest

from ducta.core.certificate import RunCertificate, write_certificate
from ducta.mlrun.experiment_tracking import ExperimentTracker, RunStatus
from ducta.mlrun.model_registry import ModelRegistry
from ducta.mlrun.storage import LocalStorageBackend
from ducta.mlrun.summary import BASE_COLUMNS, run_summary


@pytest.fixture
def stores(tmp_path):
    storage = LocalStorageBackend(base_path=str(tmp_path / "mlops"))
    tracker = ExperimentTracker(storage=storage)
    registry = ModelRegistry(storage=storage, validate_artifacts=False)
    return SimpleNamespace(
        tracker=tracker,
        registry=registry,
        context=SimpleNamespace(
            mlops_context=SimpleNamespace(experiment_tracker=tracker, model_registry=registry)
        ),
        path=str(tmp_path / "mlops"),
        tmp=tmp_path,
    )


def _run(stores, experiment="churn", params=None, metrics=None, tags=None, model=None):
    """One finished run; ``model`` registers a version of that name against it."""
    experiments = {e["name"]: e["experiment_id"] for e in stores.tracker.list_experiments()}
    experiment_id = (
        experiments.get(experiment) or stores.tracker.create_experiment(experiment).experiment_id
    )
    run = stores.tracker.start_run(
        experiment_id=experiment_id, name="r", parameters=params or {}, tags=tags or {}
    )
    for key, value in (metrics or {}).items():
        stores.tracker.log_metric(run.run_id, key, value)
    stores.tracker.end_run(run.run_id, RunStatus.COMPLETED)
    if model:
        artifact = stores.tmp / f"{run.run_id}.pkl"
        artifact.write_bytes(pickle.dumps({"w": 1}))
        stores.registry.register_model(
            name=model,
            artifact_path=str(artifact),
            artifact_type="pickle",
            framework="sklearn",
            metrics={"auc": 0.5},
            experiment_run_id=run.run_id,
        )
    return run.run_id


class TestTheJoin:
    def test_a_run_gets_its_params_metrics_and_model_in_one_row(self, stores):
        run_id = _run(
            stores,
            params={"max_depth": 6},
            metrics={"auc": 0.91},
            tags={"sweep_id": "sw-1", "model_version": "1.0.0"},
            model="churn-model",
        )

        frame = run_summary(stores.context, pipeline="churn")

        assert len(frame) == 1
        row = frame.iloc[0]
        assert row["run_id"] == run_id and row["pipeline"] == "churn"
        assert row["status"] == "COMPLETED" and row["sweep_id"] == "sw-1"
        assert row["param_max_depth"] == 6 and row["metric_auc"] == pytest.approx(0.91)
        assert row["model_name"] == "churn-model" and row["model_version"] == 1
        assert row["model_label"] == "1.0.0"
        assert row["artifact_sha256"]

    def test_columns_are_the_base_ones_then_params_then_metrics(self, stores):
        _run(stores, params={"b": 1, "a": 2}, metrics={"z": 1.0, "m": 2.0}, model="churn-model")

        columns = list(run_summary(stores.context, pipeline="churn").columns)

        leading = [c for c in BASE_COLUMNS if c in columns]
        assert columns[: len(leading)] == leading
        # "auc" is the registered model's own metric (see the fallback test below).
        assert columns[len(leading) :] == [
            "param_a",
            "param_b",
            "metric_auc",
            "metric_m",
            "metric_z",
        ]

    def test_a_run_without_a_model_has_empty_model_columns(self, stores):
        _run(stores, metrics={"auc": 0.7})
        _run(stores, metrics={"auc": 0.8}, model="churn-model")

        frame = run_summary(stores.context, pipeline="churn").sort_values("metric_auc")

        assert frame["model_name"].isna().tolist() == [True, False]

    def test_metrics_of_a_run_that_logged_none_come_from_its_model(self, stores):
        # A run recorded before persist_model logged metrics to the run itself.
        _run(stores, model="churn-model")

        frame = run_summary(stores.context, pipeline="churn")

        assert frame.iloc[0]["metric_auc"] == pytest.approx(0.5)

    def test_the_run_wins_over_its_model_when_both_have_a_metric(self, stores):
        _run(stores, metrics={"auc": 0.99}, model="churn-model")

        assert run_summary(stores.context, pipeline="churn").iloc[0]["metric_auc"] == pytest.approx(
            0.99
        )


class TestWhichRuns:
    def test_only_the_named_pipelines_runs(self, stores):
        _run(stores, experiment="churn", metrics={"auc": 0.9})
        _run(stores, experiment="other", metrics={"auc": 0.1})

        assert set(run_summary(stores.context, pipeline="churn")["pipeline"]) == {"churn"}
        assert set(run_summary(stores.context)["pipeline"]) == {"churn", "other"}

    def test_an_unknown_pipeline_is_an_empty_table_that_says_what_exists(self, stores):
        from loguru import logger

        _run(stores, experiment="churn")
        messages = []
        logger.enable("ducta")
        sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
        try:
            frame = run_summary(stores.context, pipeline="nope")
        finally:
            logger.remove(sink)
            logger.disable("ducta")

        assert frame.empty and list(frame.columns) == BASE_COLUMNS
        assert "found: churn" in str(messages[0])

    def test_no_runs_at_all_is_an_empty_table_with_the_base_columns(self, stores):
        assert list(run_summary(stores.context).columns) == BASE_COLUMNS


class TestStores:
    def test_it_reads_a_path_when_there_is_no_ml_context(self, stores):
        _run(stores, metrics={"auc": 0.9}, model="churn-model")

        frame = run_summary(pipeline="churn", mlops_path=stores.path)

        assert len(frame) == 1 and frame.iloc[0]["model_name"] == "churn-model"

    def test_without_a_context_or_a_path_it_says_what_is_missing(self):
        with pytest.raises(ValueError, match="mlops_path"):
            run_summary()


class TestOrdering:
    def test_newest_first_by_default(self, stores):
        first = _run(stores, metrics={"auc": 0.9})
        second = _run(stores, metrics={"auc": 0.1})

        assert run_summary(stores.context, pipeline="churn")["run_id"].tolist() == [second, first]

    def test_sort_by_a_metric_best_first(self, stores):
        _run(stores, metrics={"auc": 0.5})
        _run(stores, metrics={"auc": 0.9})
        _run(stores, metrics={"auc": 0.7})

        frame = run_summary(stores.context, pipeline="churn", sort_by="metric_auc")

        assert frame["metric_auc"].tolist() == pytest.approx([0.9, 0.7, 0.5])

    def test_sort_by_ascending(self, stores):
        _run(stores, metrics={"auc": 0.9})
        _run(stores, metrics={"auc": 0.5})

        frame = run_summary(stores.context, pipeline="churn", sort_by="metric_auc", ascending=True)

        assert frame["metric_auc"].tolist() == pytest.approx([0.5, 0.9])

    def test_sorting_by_a_column_that_is_not_there_lists_the_columns(self, stores):
        _run(stores, metrics={"auc": 0.9})

        with pytest.raises(ValueError, match="metric_auc"):
            run_summary(stores.context, pipeline="churn", sort_by="auc")


class TestAColumnTheFormatsAccept:
    def test_a_column_nothing_filled_is_left_out(self, stores):
        _run(stores, metrics={"auc": 0.9})

        frame = run_summary(stores.context, pipeline="churn")

        assert "certificate_ok" not in frame.columns  # nobody checked a certificate
        assert "model_name" not in frame.columns  # no run registered a model

    def test_a_hyperparameter_with_mixed_types_becomes_text(self, stores):
        _run(stores, params={"max_depth": 6})
        _run(stores, params={"max_depth": "None"})

        frame = run_summary(stores.context, pipeline="churn")

        assert set(frame["param_max_depth"]) == {"6", "None"}

    def test_a_numeric_hyperparameter_stays_numeric(self, stores):
        _run(stores, params={"max_depth": 6})
        _run(stores, params={"max_depth": 3})

        assert pd.api.types.is_numeric_dtype(run_summary(stores.context)["param_max_depth"])

    def test_parameters_that_ducta_keeps_for_itself_are_not_columns(self, stores):
        _run(stores, params={"max_depth": 6, "_environment_snapshot": "{...}"})

        columns = run_summary(stores.context).columns
        assert "param_max_depth" in columns
        assert not any("environment_snapshot" in c for c in columns)

    def test_the_table_survives_a_parquet_roundtrip(self, stores, tmp_path):
        pytest.importorskip("pyarrow")
        _run(stores, params={"max_depth": 6}, metrics={"auc": 0.9}, model="churn-model")
        _run(stores, params={"max_depth": "None"}, metrics={"auc": 0.8})

        frame = run_summary(stores.context, pipeline="churn")
        frame.to_parquet(tmp_path / "runs.parquet")

        assert len(pd.read_parquet(tmp_path / "runs.parquet")) == 2


class TestEvidenceTheRunCarries:
    def test_code_data_and_split_come_from_what_the_run_logged(self, stores):
        fingerprints = {"customers": {"fingerprint": "abc"}, "orders": {"raw_file_hash": "def"}}
        _run(
            stores,
            params={
                "_code_hash": "sha256:code",
                "_input_fingerprints": json.dumps(fingerprints),
                "_split_applied": "true",
            },
            tags={"ducta_run_id": "cert-1", "git_commit": "abc123"},
        )

        row = run_summary(stores.context).iloc[0]

        assert row["code_hash"] == "sha256:code"
        assert row["data_hash"].startswith("sha256:")
        assert row["split_applied"] is True or row["split_applied"] == True  # noqa: E712
        assert row["certificate_id"] == "cert-1" and row["git_commit"] == "abc123"

    def test_the_same_inputs_give_the_same_data_hash_and_other_inputs_another(self, stores):
        same = json.dumps({"c": {"fingerprint": "abc"}})
        _run(stores, params={"_input_fingerprints": same})
        _run(stores, params={"_input_fingerprints": same})
        _run(stores, params={"_input_fingerprints": json.dumps({"c": {"fingerprint": "xyz"}})})

        hashes = run_summary(stores.context)["data_hash"].tolist()

        assert len(set(hashes)) == 2 and sorted(hashes)[0] != sorted(hashes)[1]

    def test_an_unreadable_fingerprint_is_no_hash_not_an_error(self, stores):
        _run(stores, params={"_input_fingerprints": "not json"})

        assert "data_hash" not in run_summary(stores.context).columns


class TestCertificates:
    def _certificate(self, directory, run_id, tamper=False):
        cert = RunCertificate(
            run_id=run_id,
            pipeline="churn",
            environment_name="dev",
            status="success",
            started_at="2026-01-01T00:00:00+00:00",
            ended_at="2026-01-01T00:01:00+00:00",
            ducta_version="1.0.0",
        )
        cert.certificate_hash = cert.compute_hash()
        path = write_certificate(cert, directory / "dev" / run_id)
        if tamper:
            data = json.loads(path.read_text())
            data["status"] = "failed"
            path.write_text(json.dumps(data))

    def test_a_certificate_on_disk_and_intact_is_ok(self, stores):
        _run(stores, tags={"ducta_run_id": "cert-ok"})
        self._certificate(stores.tmp / "runs", "cert-ok")

        frame = run_summary(stores.context, certificates_dir=str(stores.tmp / "runs"))

        assert bool(frame.iloc[0]["certificate_ok"]) is True

    def test_an_altered_certificate_is_not_ok(self, stores):
        _run(stores, tags={"ducta_run_id": "cert-bad"})
        self._certificate(stores.tmp / "runs", "cert-bad", tamper=True)

        frame = run_summary(stores.context, certificates_dir=str(stores.tmp / "runs"))

        assert bool(frame.iloc[0]["certificate_ok"]) is False

    def test_a_missing_certificate_is_not_ok(self, stores):
        _run(stores, tags={"ducta_run_id": "cert-gone"})
        (stores.tmp / "runs").mkdir()

        frame = run_summary(stores.context, certificates_dir=str(stores.tmp / "runs"))

        assert bool(frame.iloc[0]["certificate_ok"]) is False

    def test_without_a_directory_nothing_is_claimed(self, stores):
        _run(stores, tags={"ducta_run_id": "cert-1"})

        assert "certificate_ok" not in run_summary(stores.context).columns


class TestACallerSuppliesItsOwnCertificateCheck:
    """The API looks for a certificate in more places than one directory."""

    def test_the_check_decides_certificate_ok_from_the_runs_certificate_id(self, stores):
        _run(stores, tags={"ducta_run_id": "cert-ok"})
        _run(stores, tags={"ducta_run_id": "cert-bad"})
        _run(stores)  # no certificate at all

        frame = run_summary(
            stores.context, pipeline="churn", certificate_check=lambda cid: cid == "cert-ok"
        )

        by_id = dict(zip(frame["certificate_id"], frame["certificate_ok"]))
        assert bool(by_id["cert-ok"]) is True
        assert bool(by_id["cert-bad"]) is False
        # A run with no certificate id is not asked about: the column stays empty for it.
        assert frame["certificate_ok"].isna().sum() == 1

    def test_the_check_wins_over_a_certificates_dir(self, stores):
        _run(stores, tags={"ducta_run_id": "cert-1"})

        frame = run_summary(
            stores.context,
            pipeline="churn",
            certificates_dir=str(stores.tmp / "nowhere"),
            certificate_check=lambda cid: True,
        )

        assert bool(frame.iloc[0]["certificate_ok"]) is True
