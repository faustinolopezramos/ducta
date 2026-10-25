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


class TestPipelinesWithoutNodeCode:
    """A pipeline of declarative nodes (a JDBC ingestion) has no module to hash.

    `_code_fingerprint` answered None for it, the marker recorded
    `"code_fingerprint": null`, and every later run refused to reuse it as
    "written by an older Ducta" — so a chain starting with one never reused
    anything, however often it re-ran.
    """

    @staticmethod
    def _fingerprint(nodes_config):
        from unittest.mock import MagicMock

        batch = MagicMock()
        batch._get_pipeline_config.return_value = {"nodes": list(nodes_config)}
        executor = object.__new__(PipelineExecutor)
        executor.context = type("Ctx", (), {"nodes_config": nodes_config})()
        executor._batch_executor = batch
        return executor._code_fingerprint("bronze.ingestion")

    def test_it_has_a_stable_fingerprint(self):
        declarative = {"bronze.orders": {"ingest": {"source": "erp", "table": "orders"}}}

        first = self._fingerprint(declarative)

        assert first is not None
        assert first == self._fingerprint(declarative)

    def test_its_marker_can_be_reused(self):
        fingerprint = self._fingerprint({"bronze.orders": {"ingest": {"source": "erp"}}})
        executor = _executor("cfg-1", fingerprint)

        assert executor._provenance_still_matches("bronze", _state(code_fp=fingerprint)) is True
