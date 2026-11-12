"""Every cloud scheme keeps its ``//`` (review 2026-11-11).

``s3a://`` was missing from the gate's list: the derived dataset path became
``s3a:/bucket/…`` and a local folder named ``s3a:`` was created.
"""

from __future__ import annotations

import pytest

from ducta.gate.constants import CLOUD_URI_PREFIXES, is_cloud_path, join_path
from ducta.gate.output.paths import _PathManager
from ducta.gate.validators import ConfigValidator
from ducta.stream.checkpoints import CheckpointManager

SCHEMES = ["s3", "s3a", "s3n", "gs", "abfs", "abfss", "wasb", "wasbs", "hdfs"]


@pytest.mark.parametrize("scheme", SCHEMES)
def test_scheme_is_cloud(scheme):
    assert is_cloud_path(f"{scheme}://bucket/x")


def test_one_list_for_gate_and_stream():
    for prefix in CLOUD_URI_PREFIXES:
        assert CheckpointManager.is_cloud_path(prefix + "bucket/x")


@pytest.mark.parametrize("local", ["data/out", "/abs/out", "C:/data/out", "file:///tmp/x"])
def test_local_paths_are_not_cloud(local):
    assert not is_cloud_path(local)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_derived_output_path_keeps_the_scheme(scheme):
    class Ctx:
        output_path = f"{scheme}://bucket/out"
        global_config = {"output_path": output_path, "mode": "local"}

    paths = _PathManager(Ctx(), ConfigValidator())
    resolved = paths.resolve_output_path({}, "silver.orders.clean", "prod")
    assert resolved.startswith(f"{scheme}://bucket/out/")
    assert resolved.endswith("/silver/orders/clean")


def test_join_path():
    assert join_path("s3a://bucket/out/", "prod", "x") == "s3a://bucket/out/prod/x"
    assert join_path("data", "prod", "x") == "data/prod/x"


@pytest.mark.parametrize("scheme", ["s3a", "abfs", "hdfs"])
def test_quality_store_on_a_new_scheme_stays_remote(scheme, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from ducta.check.storage import ContextAwareStorageBackend

    monkeypatch.chdir(tmp_path)
    ctx = SimpleNamespace(global_config={}, output_path=f"{scheme}://bucket/out")
    store = ContextAwareStorageBackend(ctx, format="parquet", base_path=f"{scheme}://bucket/q")
    assert str(store._reports_dir("orders", "etl")) == f"{scheme}://bucket/q/etl/orders/reports"
    assert list(tmp_path.iterdir()) == []  # no local `s3a:` folder
