"""A cloud checkpoint base is handed to Spark with its scheme (review 2026-11-11).

``_scope_by_environment`` and the ``output_path`` fallback joined through ``Path``:
``s3a://bucket/chk`` became ``s3a:/bucket/chk/prod/…``, a local folder.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ducta.stream.checkpoints import CheckpointManager


def _location(gs, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = SimpleNamespace(global_config=gs, output_path=gs["output_path"], env="prod")
    return CheckpointManager(ctx).get_checkpoint_location(None, "orders", "sink")


@pytest.mark.parametrize(
    ("gs", "expected"),
    [
        (
            {"checkpoints_base": "s3a://bucket/chk", "output_path": "s3a://bucket/out"},
            "s3a://bucket/chk/prod/orders/sink",
        ),
        (
            {"output_path": "s3a://bucket/out"},
            "s3a://bucket/out/prod/streaming_checkpoints/orders/sink",
        ),
        (
            {"checkpoints_base": "abfss://c@acc/chk/${environment}", "output_path": "x"},
            "abfss://c@acc/chk/prod/orders/sink",
        ),
    ],
)
def test_cloud_checkpoint_keeps_its_scheme(gs, expected, tmp_path, monkeypatch):
    assert _location(gs, tmp_path, monkeypatch) == expected
    assert not any(p.name.endswith(":") for p in tmp_path.iterdir())  # no local `s3a:` folder


def test_local_checkpoint_unchanged(tmp_path, monkeypatch):
    location = _location({"output_path": "data"}, tmp_path, monkeypatch)
    assert location == "data/prod/streaming_checkpoints/orders/sink"
    assert (tmp_path / location).is_dir()
