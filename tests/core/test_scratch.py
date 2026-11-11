"""Runs that must not touch the real datasets: sample runs and reproductions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.core import certificate as cert_mod
from ducta.core.scratch import (
    pin_served_models,
    prepare_reproduction,
    redirect_writes,
    reproduction_dir,
    reproduction_window,
)


def _ctx(out: Path) -> SimpleNamespace:
    return SimpleNamespace(
        execution_mode="local",
        output_path=str(out),
        global_config={"output_path": str(out)},
        output_config={
            "bronze.a.raw": {"format": "parquet"},
            "silver.a.clean": {"format": "parquet", "filepath": str(out / "dev" / "x" / "clean")},
        },
        input_config={
            # produced by the run: read where the run writes it
            "bronze.a.raw": {"format": "parquet", "filepath": str(out / "dev" / "bronze/a/raw")},
            "silver.a.clean": {"format": "parquet", "filepath": str(out / "dev" / "x" / "clean")},
            # not produced by the run: read where it is
            "source": {"format": "csv", "filepath": "/landing/source.csv"},
        },
        nodes_config={},
    )


class TestRedirectWrites:
    def test_downstream_nodes_read_what_the_run_wrote(self, tmp_path):
        """They read the real dataset before: a sample run's nodes computed on old data."""
        out, target = tmp_path / "data", tmp_path / "scratch"
        ctx = _ctx(out)
        redirect_writes(ctx, target, "dev", certificates=True)
        assert ctx.input_config["bronze.a.raw"]["filepath"] == str(
            target / "dev" / "bronze" / "a" / "raw"
        )
        assert ctx.input_config["silver.a.clean"]["filepath"] == str(target / "dev" / "x" / "clean")
        assert ctx.input_config["source"]["filepath"] == "/landing/source.csv"

    def test_a_dataset_the_run_does_not_produce_falls_back_to_the_real_one(self, tmp_path):
        """A single node of a sample run still reads its upstream."""
        out = tmp_path / "data"
        ctx = _ctx(out)
        redirect_writes(ctx, tmp_path / "scratch", "dev", certificates=True)
        assert ctx._read_fallback_paths == [str(out)]
        assert ctx.global_config["_read_fallback_paths"] == [str(out)]

    def test_certificates_move_only_when_asked(self, tmp_path):
        ctx = _ctx(tmp_path / "data")
        redirect_writes(ctx, tmp_path / "scratch", "dev", certificates=False)
        assert "run_certificate_dir" not in ctx.global_config


class TestPrepareReproduction:
    def test_a_fresh_folder_of_its_own_and_the_certificate_with_the_real_ones(self, tmp_path):
        out = tmp_path / "data"
        ctx = _ctx(out)
        real_runs = cert_mod.certificate_dir(ctx, "x").parent
        stale = out / "dev" / ".ducta" / "reproduce" / "r1" / "leftover"
        stale.mkdir(parents=True)

        target = prepare_reproduction(ctx, "dev", "r1")

        assert target == out / "dev" / ".ducta" / "reproduce" / "r1"
        assert not stale.exists()  # an appending output must not add to the last one's rows
        assert ctx.output_path == str(target)
        assert ctx.reproduction_of == "r1"
        assert cert_mod.certificate_dir(ctx, "new") == real_runs / "new"


class TestReproductionWindow:
    CERT = {"run_window": {"start_date": "2026-01-01", "end_date": "2026-01-31"}}

    def test_the_recorded_dates_by_default(self):
        assert reproduction_window(self.CERT, None, None) == ("2026-01-01", "2026-01-31")

    def test_given_dates_win_and_a_difference_is_warned(self):
        from loguru import logger

        messages: list = []
        sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
        logger.enable("ducta")  # ducta disables its own logger at import
        try:
            window = reproduction_window(self.CERT, "2026-02-01", "2026-02-28")
        finally:
            logger.disable("ducta")
            logger.remove(sink)
        assert window == ("2026-02-01", "2026-02-28")
        assert any("will most likely not match" in m for m in messages)

    def test_a_certificate_without_a_window(self):
        assert reproduction_window({}, None, None) == (None, None)


class TestCertificateFields:
    def _cert(self, **kw):
        base = dict(
            run_id="r",
            pipeline="p",
            environment_name="dev",
            status="success",
            started_at="t0",
            ended_at="t1",
            ducta_version="0",
        )
        return cert_mod.RunCertificate(**base, **kw)

    def test_absent_when_unset_so_older_hashes_hold(self):
        content = self._cert().content()
        assert "run_window" not in content and "reproduction_of" not in content

    def test_present_and_hashed_when_set(self):
        plain = self._cert()
        cert = self._cert(
            run_window={"start_date": "2026-01-01", "end_date": None}, reproduction_of="r0"
        )
        assert cert.content()["run_window"] == {"start_date": "2026-01-01", "end_date": None}
        assert cert.content()["reproduction_of"] == "r0"
        assert cert.compute_hash() != plain.compute_hash()
        assert cert_mod.verify_certificate_data(cert.sealed()).ok


class TestReproductionStaysInItsFolder:
    """The run id comes from the certificate's JSON, and the folder is emptied first.

    An unsigned certificate with a recomputed hash verifies, so an id that is a
    path deleted whatever folder it named.
    """

    @pytest.mark.parametrize("run_id", ["{victim}", "../../../victim", "..", "", "a/b", "-x"])
    def test_an_id_that_is_not_a_run_id_is_refused_and_nothing_is_deleted(self, tmp_path, run_id):
        victim = tmp_path / "victim"
        (victim / "keep").mkdir(parents=True)
        ctx = _ctx(tmp_path / "data")
        with pytest.raises(ValueError):
            prepare_reproduction(ctx, "dev", run_id.format(victim=victim))
        assert (victim / "keep").exists()

    @pytest.mark.parametrize("env", ["../victim", "a/b", ""])
    def test_an_environment_that_is_a_path_is_refused(self, tmp_path, env):
        with pytest.raises(ValueError):
            reproduction_dir(_ctx(tmp_path / "data"), env, "r1")

    def test_a_uuid_run_id_is_accepted(self, tmp_path):
        run_id = "0f3c9a5e7b2d4c1e8f6a0b9d3e5c7a1f"
        target = reproduction_dir(_ctx(tmp_path / "data"), "dev", run_id)
        assert target == tmp_path / "data" / "dev" / ".ducta" / "reproduce" / run_id


class TestTheModelStoreIsRedirectedToo:
    """A reproduced training run registered a new version and promoted it to production."""

    def test_registry_and_tracking_move_and_serving_keeps_the_real_store(self, tmp_path):
        out = tmp_path / "data"
        ctx = _ctx(out)
        ctx.global_config["mlops_path"] = str(tmp_path / "mlops_data")
        target = prepare_reproduction(ctx, "dev", "r1")
        assert ctx.global_config["mlops_path"] == str(target / ".ducta" / "mlops")
        assert ctx.serving_mlops_path == str(tmp_path / "mlops_data")

    def test_without_mlops_path_the_real_store_is_resolved_before_the_output_moves(self, tmp_path):
        out = tmp_path / "data"
        ctx = _ctx(out)
        ctx.environment = "dev"
        redirect_writes(ctx, tmp_path / "scratch", "dev", certificates=True)
        assert str(out) in ctx.serving_mlops_path
        assert ctx.global_config["mlops_path"].startswith(str(tmp_path / "scratch"))


class TestPinServedModels:
    CERT = {
        "nodes": [
            {"name": "score", "ml": {"model": {"source": "ducta", "name": "churn", "version": 3}}},
            {"name": "train", "ml": {"stage": "training"}},
            {"name": "m", "ml": {"model": {"source": "mlflow", "name": "x", "version": 1}}},
        ]
    }

    def test_the_versions_the_run_served_are_pinned(self, tmp_path):
        ctx = _ctx(tmp_path)
        assert pin_served_models(ctx, self.CERT) == {"churn": 3}
        assert ctx.pinned_models == {"churn": 3}

    def test_no_served_model_pins_nothing(self, tmp_path):
        ctx = _ctx(tmp_path)
        assert pin_served_models(ctx, {"nodes": [{"name": "a"}]}) == {}
        assert not hasattr(ctx, "pinned_models")
