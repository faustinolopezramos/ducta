"""The API runner makes a run's relative paths absolute before Spark sees them.

Spark resolves a relative path against the JVM's working directory, which is
fixed when the server's first session starts — not the project a run belongs to.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ducta.api.execution.runner import normalize_execution_context_paths


def _ctx(nodes):
    return SimpleNamespace(
        input_path="data",
        output_path="s3://lake/out",
        global_config={},
        input_config={"raw": {"filepath": "data/raw.csv"}},
        output_config={},
        nodes_config=nodes,
    )


def test_a_stream_nodes_inline_paths_become_absolute(tmp_path: Path):
    stream = {
        "type": "streaming",
        "input": {"format": "file_stream", "options": {"path": "data/events"}},
        "output": {"format": "parquet", "path": "out/events"},
        "streaming": {"checkpoint_location": "out/_ckpt"},
    }
    ctx = _ctx({"ingest": stream})
    normalize_execution_context_paths(ctx, tmp_path)

    root = tmp_path.resolve()
    assert stream["input"]["options"]["path"] == str(root / "data/events")
    assert stream["output"]["path"] == str(root / "out/events")
    assert stream["streaming"]["checkpoint_location"] == str(root / "out/_ckpt")
    assert ctx.input_config["raw"]["filepath"] == str(root / "data/raw.csv")
    assert ctx.output_path == "s3://lake/out"  # a URI is left alone


def test_batch_nodes_and_placeholders_are_left_alone(tmp_path: Path):
    batch = {"type": "batch", "module": "pipelines.etl", "path": "not/a/dataset"}
    stream = {"type": "streaming", "output": {"path": "${output_path}/events"}}
    normalize_execution_context_paths(_ctx({"b": batch, "s": stream}), tmp_path)
    assert batch["path"] == "not/a/dataset"
    assert stream["output"]["path"] == "${output_path}/events"
