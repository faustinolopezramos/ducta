"""Unit tests for ducta.check.profiles: resolve_checks_config and apply_auto_tune."""

from __future__ import annotations

import pytest

from ducta.check.core import QualityConfigError
from ducta.check.profiles import QualityProfile, apply_auto_tune, resolve_checks_config
from ducta.check.storage import FileStorageBackend


class TestResolveChecksConfigUnknownProfile:
    """Regression: a typo'd profile name used to silently fall back to the
    node's own checks (with only a warning log) — every check the profile
    was meant to add was silently dropped, with no visible failure."""

    def test_unknown_profile_raises_instead_of_falling_back(self):
        profiles = {"strict": QualityProfile(name="strict", checks={"row_count": {}})}
        with pytest.raises(QualityConfigError, match="strick"):
            resolve_checks_config({}, "strick", profiles)

    def test_no_profile_name_returns_node_checks_unchanged(self):
        node_checks = {"row_count": {"min": 10}}
        assert resolve_checks_config(node_checks, None, {}) == node_checks

    def test_known_profile_merges_normally(self):
        profiles = {"strict": QualityProfile(name="strict", checks={"row_count": {"min": 5}})}
        merged = resolve_checks_config({"schema": {}}, "strict", profiles)
        assert merged["row_count"] == {"min": 5}
        assert "schema" in merged


class TestApplyAutoTune:
    def test_creates_gate_cfg_when_node_has_none(self, tmp_path):
        """Regression: a node without its own quality_gate block (gate_cfg=None)
        must still get an auto-tuned score_threshold when the profile has
        auto_tune=true and there's enough history — not silently no-op."""
        storage = FileStorageBackend(str(tmp_path))
        for i in range(5):
            storage.append_history("ds", {"score": 0.9, "row_count": 100 + i})

        profile = QualityProfile(name="p", auto_tune=True)
        result = apply_auto_tune(profile, None, "ds", storage)

        assert result is not None
        assert "score_threshold" in result

    def test_non_dict_gate_cfg_returned_unchanged(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        profile = QualityProfile(name="p", auto_tune=True)
        sentinel = object()
        assert apply_auto_tune(profile, sentinel, "ds", storage) is sentinel

    def test_no_auto_tune_returns_gate_cfg_unchanged(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        profile = QualityProfile(name="p", auto_tune=False)
        assert apply_auto_tune(profile, None, "ds", storage) is None

    def test_insufficient_history_returns_empty_dict_not_none(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        profile = QualityProfile(name="p", auto_tune=True)
        result = apply_auto_tune(profile, None, "ds", storage)
        assert result == {}

    def test_history_scoped_per_pipeline(self, tmp_path):
        """Regression: auto_tune must analyze only the requesting pipeline's own
        history for a dataset, not history contributed by a different pipeline
        that happens to have a same-named node."""
        storage = FileStorageBackend(str(tmp_path))
        for i in range(5):
            storage.append_history(
                "ds", {"score": 0.9, "row_count": 100 + i}, pipeline_name="pipe_a"
            )
        # pipe_b has no history at all for "ds".
        profile = QualityProfile(name="p", auto_tune=True)

        result_a = apply_auto_tune(profile, None, "ds", storage, pipeline_name="pipe_a")
        result_b = apply_auto_tune(profile, None, "ds", storage, pipeline_name="pipe_b")

        assert "score_threshold" in result_a
        assert result_b == {}
