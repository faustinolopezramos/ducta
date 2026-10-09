"""Sample runs: the first N rows in, everything written kept out of the real datasets."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.api.execution.runner import redirect_to_scratch
from ducta.gate.input import sample


def test_sample_takes_the_first_rows_of_pandas():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"a": range(10)})
    assert len(sample(df, 3)) == 3
    assert sample(None, 3) is None
    assert sample([1, 2], 1) == [1, 2]  # not a frame: left alone


def test_everything_a_sample_run_writes_goes_to_the_scratch(tmp_path):
    out = tmp_path / "data"
    ctx = SimpleNamespace(
        output_path=str(out),
        global_config={
            "output_path": str(out),
            "quality": {"output": {"base_path": str(out / "dev" / "quality"), "format": "json"}},
        },
        nodes_config={
            "n": {
                "data_quality": {
                    "checks": {"row_count": {"min": 350}},
                    "quality_gate": {"max_errors": 0},
                },
                "sanity_checks": {
                    "inputs": {"raw": {"checks": {}, "quality_gate": {"max_errors": 0}}}
                },
            }
        },
        output_config={
            "silver.x.y": {"filepath": str(out / "dev" / "silver" / "x" / "y")},
            "elsewhere": {"filepath": "/abs/other/place"},
            "remote": {"filepath": "s3://bucket/t"},
            "conventional.a.b": {"format": "parquet"},
        },
    )
    scratch = redirect_to_scratch(ctx, "dev", 25)
    assert scratch == out / "dev" / ".ducta" / "scratch"
    assert ctx.sample_rows == 25
    assert ctx.output_path == ctx.global_config["output_path"] == str(scratch)
    oc = ctx.output_config
    assert oc["silver.x.y"]["filepath"] == str(scratch / "dev" / "silver" / "x" / "y")
    assert oc["elsewhere"]["filepath"] == str(scratch / "elsewhere")
    assert oc["remote"]["filepath"] == str(scratch / "remote")  # never the real bucket
    assert "filepath" not in oc["conventional.a.b"]  # derived from output_path: already redirected
    assert Path(ctx.global_config["run_certificate_dir"]).is_relative_to(scratch)
    assert Path(ctx.global_config["chain"]["state_dir"]).is_relative_to(scratch)
    assert ctx.global_config["quality"]["output"] == {
        "base_path": str(scratch / "quality"),
        "format": "json",
    }
    node = ctx.nodes_config["n"]
    assert node["data_quality"]["quality_gate"] == {"max_errors": 0, "behavior": "warn_only"}
    assert node["sanity_checks"]["inputs"]["raw"]["quality_gate"]["behavior"] == "warn_only"
