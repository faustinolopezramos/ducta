"""Unit tests for ducta.core.sweep."""

from __future__ import annotations

import json

import pytest

from ducta.core.sweep import SweepError, expand_sweep, load_sweep_spec, new_sweep_id


class TestNewSweepId:
    def test_format(self):
        sid = new_sweep_id()
        assert sid.startswith("sweep-")
        assert len(sid) > len("sweep-")

    def test_unique(self):
        assert new_sweep_id() != new_sweep_id()


class TestExpandSweep:
    def test_scalar_only_single_combo(self):
        combos = expand_sweep({"lr": 0.1, "n": 10})
        assert combos == [{"lr": 0.1, "n": 10}]

    def test_cartesian_product(self):
        combos = expand_sweep({"lr": [0.1, 0.2], "n": [10]})
        assert len(combos) == 2
        assert {"lr": 0.1, "n": 10} in combos
        assert {"lr": 0.2, "n": 10} in combos

    def test_fixed_and_swept_mixed(self):
        combos = expand_sweep({"lr": [0.1, 0.2], "seed": 42})
        assert all(c["seed"] == 42 for c in combos)
        assert len(combos) == 2

    def test_exceeding_max_runs_raises(self):
        spec = {"a": list(range(10)), "b": list(range(10))}  # 100 combos
        with pytest.raises(SweepError):
            expand_sweep(spec, max_runs=50)

    def test_explicit_max_runs_above_default_is_honored(self):
        # Regression: both the CLI and the API used to call expand_sweep(spec)
        # with no max_runs=, so a caller-side limit configured above the
        # library default of 50 never had any effect — the grid was truncated
        # during expansion before the caller's own check could apply.
        spec = {"a": list(range(10)), "b": list(range(10))}  # 100 combos
        combos = expand_sweep(spec, max_runs=100)
        assert len(combos) == 100


class TestLoadSweepSpec:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(SweepError, match="not found"):
            load_sweep_spec(str(tmp_path / "nope.json"))

    def test_load_json(self, tmp_path):
        p = tmp_path / "sweep.json"
        p.write_text(json.dumps({"lr": [0.1, 0.2]}), encoding="utf-8")
        spec = load_sweep_spec(str(p))
        assert spec == {"lr": [0.1, 0.2]}

    def test_empty_spec_raises(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("{}", encoding="utf-8")
        with pytest.raises(SweepError, match="non-empty"):
            load_sweep_spec(str(p))
