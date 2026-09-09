"""Regression: --reuse-upstream reused outputs produced by different code.

`_pipeline_is_up_to_date` answered only "do the outputs exist (and match the
date range)". Editing a node's transformation and re-running with
`--reuse-upstream` therefore skipped the ancestor and fed its stale output
downstream — exit 0, certificate `success`, and no indication anywhere that
the numbers came from code that no longer exists.
"""

from __future__ import annotations

from ducta.core.executors.facade import PipelineExecutor
from ducta.core.settings import CoreSettings


def _executor(config_fp, code_fp) -> PipelineExecutor:
    """A facade whose two fingerprint helpers return fixed values."""
    executor = object.__new__(PipelineExecutor)
    executor.settings = CoreSettings()
    executor._config_fingerprint = lambda: config_fp
    executor._code_fingerprint = lambda _pipeline: code_fp
    return executor


def _state(config_fp="cfg-1", code_fp="mtime:1.0"):
    return {
        "pipeline": "bronze",
        "start_date": None,
        "end_date": None,
        "config_fingerprint": config_fp,
        "code_fingerprint": code_fp,
    }


class TestProvenance:
    def test_unchanged_config_and_code_may_be_reused(self):
        executor = _executor("cfg-1", "mtime:1.0")

        assert executor._provenance_still_matches("bronze", _state()) is True

    def test_changed_node_code_blocks_reuse(self):
        executor = _executor("cfg-1", "mtime:2.0")

        assert executor._provenance_still_matches("bronze", _state()) is False

    def test_changed_configuration_blocks_reuse(self):
        executor = _executor("cfg-2", "mtime:1.0")

        assert executor._provenance_still_matches("bronze", _state()) is False


class TestFailsClosed:
    def test_a_marker_from_an_older_ducta_blocks_reuse(self):
        # No fingerprints recorded: nothing can be compared, so nothing is
        # vouched for. One recomputation beats one unnoticed stale result.
        executor = _executor("cfg-1", "mtime:1.0")
        legacy = {"pipeline": "bronze", "start_date": None, "end_date": None}

        assert executor._provenance_still_matches("bronze", legacy) is False

    def test_a_missing_marker_blocks_reuse(self):
        executor = _executor("cfg-1", "mtime:1.0")

        assert executor._provenance_still_matches("bronze", None) is False

    def test_an_unresolvable_fingerprint_blocks_reuse(self):
        # _code_fingerprint returns None when a node's module cannot be located.
        executor = _executor("cfg-1", None)

        assert executor._provenance_still_matches("bronze", _state()) is False


class TestStalenessDefault:
    def test_the_freshness_check_is_on_by_default(self):
        # Reuse is already opt-in, so once a user asks for it the check that
        # keeps it honest should not also need asking for.
        assert CoreSettings.from_context({}).chain_staleness_check is True

    def test_it_can_still_be_turned_off(self):
        settings = CoreSettings.from_context({"chain": {"staleness_check": False}})

        assert settings.chain_staleness_check is False
