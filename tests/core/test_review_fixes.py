"""Regression tests for the run-evidence and scheduling defects found in review.

Each test here pins one behaviour that used to be wrong in a way nothing
surfaced: the certificate looked complete, the run reported success, or the DAG
scheduled a node before whatever feeds it.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from loguru import logger

from ducta.core.execution.runner import NodeExecutor
from ducta.core.ledger import RunLedger, ledger_for
from ducta.gate.exceptions import MissingDependencyError
from ducta.setting.dependency_inference import extract_input_keys


@contextmanager
def captured_warnings():
    """Collect loguru WARNING records from ``ducta``.

    Two wrinkles: loguru does not feed pytest's ``caplog``, and ``ducta``
    disables its own logger at import (the standard library pattern — the CLI
    and API re-enable it), so a sink alone would see nothing.
    """
    records: list = []
    sink_id = logger.add(lambda msg: records.append(msg), level="WARNING", format="{message}")
    logger.enable("ducta")
    try:
        yield records
    finally:
        logger.disable("ducta")
        logger.remove(sink_id)


class TestLedgerIsCachedOnDictContexts:
    """`ledger_for` used to build a fresh ledger per call for dict contexts.

    `getattr`/`setattr` do not reach into a dict, and the `setattr` failure was
    swallowed — so every caller got its own instance. `_record_failures` lives
    per instance, which made `evidence_complete` permanently True and discarded
    every gap: the exact failure RunLedger exists to prevent, on the one context
    shape where it silently did not apply.
    """

    def test_same_ledger_is_returned(self):
        ctx: dict = {}
        assert ledger_for(ctx) is ledger_for(ctx)

    def test_gaps_recorded_through_one_handle_are_visible_from_another(self):
        ctx: dict = {}
        ledger_for(ctx).note_gap("output 'gold' not written")

        later = ledger_for(ctx)
        assert later.evidence_complete is False
        assert "output 'gold' not written" in later.record_failures[0]

    def test_object_contexts_are_unaffected(self):
        class Ctx:
            pass

        ctx = Ctx()
        assert ledger_for(ctx) is ledger_for(ctx)

    def test_note_gap_does_not_duplicate_the_same_reason(self):
        ledger = RunLedger({})
        ledger.note_gap("same reason")
        ledger.note_gap("same reason")
        assert ledger.record_failures == ["same reason"]


class TestSkipsSurviveAFailingRun:
    """`gate_blocked`/`skipped` were assigned after the try/finally.

    `coordinate`/`cleanup` raise on any node failure, so on exactly the runs
    where "which branch was skipped" matters most, both dicts stayed empty and
    the CLI/API reported a bare failure that mentioned neither the gate nor the
    skipped branch.
    """

    @staticmethod
    def _executor() -> NodeExecutor:
        ctx = MagicMock()
        ctx.nodes_config = {"a": {}, "b": {}}
        ctx.is_ml_layer = False
        ctx.global_config = {}
        return NodeExecutor(
            ctx, input_loader=MagicMock(), output_manager=MagicMock(), max_workers=2
        )

    def test_a_skipped_node_is_reported_even_though_another_node_failed(self):
        node_executor = self._executor()

        def fake_exec(node_name, start, end, ml_info):
            if node_name == "a":
                raise MissingDependencyError("Node 'a' has missing input(s): ds1")
            raise RuntimeError("boom in b")

        node_executor._coordinator._execute_single_node = fake_exec

        with pytest.raises(Exception):
            node_executor.execute_nodes_parallel(
                ["a", "b"], {"a": {}, "b": {}}, {"a": set(), "b": set()}, "d1", "d2", {}
            )

        assert "a" in node_executor.skipped
        assert "missing inputs" in node_executor.skipped["a"]


class TestMalformedDatasetDeclarationsAreNotSilent:
    """A dict `input` whose values are not dataset keys erased every edge.

    `gate.input._get_input_keys` raises ConfigurationError on the same value, so
    the DAG ran the node concurrently with its producer and only then failed.
    Inference still cannot raise (it runs in read-only paths), but it no longer
    stays quiet.
    """

    def test_a_named_map_with_a_non_string_value_warns(self):
        cfg = {"input": {"sales": "ds1", "threshold": 10}}
        with captured_warnings() as warnings:
            assert extract_input_keys(cfg, node="consumer") == []
        assert any("consumer" in str(w) for w in warnings)

    def test_a_well_formed_named_map_still_resolves(self):
        cfg = {"input": {"sales": "ds1", "returns": "ds2"}}
        assert extract_input_keys(cfg, node="consumer") == ["ds1", "ds2"]

    def test_an_inline_connector_config_is_not_read_as_dataset_keys(self):
        """`{format: csv, path: ...}` values are a format and a path, not datasets."""
        cfg = {"input": {"format": "file_stream", "path": "/data/in"}}
        with captured_warnings() as warnings:
            assert extract_input_keys(cfg, node="streamer") == []
        assert warnings == []  # a known shape, not a mistake to warn about


class TestOnMissingInputNamesTheDecision:
    """`fail_fast: true` was the setting that made a node *not* fail.

    It raises MissingDependencyError, which the coordinator treats as a skip
    ("Never a failure"). `fail_fast` decides whether to pre-check; it never
    decided what a missing input means. `on_missing_input` does.
    """

    @staticmethod
    def _loader(**global_config):
        from ducta.gate.input import InputLoader

        ctx = {
            "input_config": {},  # nothing resolves → every input is "missing"
            "global_config": global_config,
        }
        return InputLoader(ctx)

    def test_default_is_a_skip(self):
        loader = self._loader()
        with pytest.raises(MissingDependencyError):
            loader.load_inputs({"input": ["absent_ds"]}, "consumer")

    def test_explicit_skip_is_a_skip(self):
        loader = self._loader()
        with pytest.raises(MissingDependencyError):
            loader.load_inputs({"input": ["absent_ds"], "on_missing_input": "skip"}, "consumer")

    def test_fail_aborts_the_run_instead(self):
        from ducta.gate.exceptions import ReadOperationError

        loader = self._loader()
        with pytest.raises(ReadOperationError) as excinfo:
            loader.load_inputs({"input": ["absent_ds"], "on_missing_input": "fail"}, "consumer")
        assert "on_missing_input=fail" in str(excinfo.value)
        assert not isinstance(excinfo.value, MissingDependencyError)

    def test_an_unknown_value_falls_back_to_skip_and_says_so(self):
        loader = self._loader()
        with captured_warnings() as warnings:
            with pytest.raises(MissingDependencyError):
                loader.load_inputs({"input": ["absent_ds"], "on_missing_input": "halt"}, "consumer")
        assert any("on_missing_input" in str(w) for w in warnings)


class TestCodeFingerprintHashesContent:
    """`_code_fingerprint` returned the newest mtime among a pipeline's modules.

    An mtime is a property of the filesystem, not of the code: it does not
    survive a clone or a container rebuild (so reuse never fires), and anything
    that restores timestamps — `rsync -t`, `tar -p`, a restored backup — can put
    *different* code on disk under a timestamp the marker still recognises,
    which reuses outputs the code on disk would not produce.
    """

    @staticmethod
    def _fingerprint(tmp_path, module_name: str, source: str, mtime: float):
        import importlib
        import os
        import sys
        from contextlib import contextmanager

        from ducta.core.executors.facade import PipelineExecutor

        tmp_path.mkdir(parents=True, exist_ok=True)
        module = tmp_path / f"{module_name}.py"
        module.write_text(source)
        os.utime(module, (mtime, mtime))

        @contextmanager
        def temporary_sys_path(paths):
            sys.path[:0] = [str(p) for p in paths]
            importlib.invalidate_caches()
            try:
                yield
            finally:
                for p in paths:
                    sys.path.remove(str(p))

        loader = MagicMock()
        loader._gather_search_paths.return_value = [tmp_path]
        loader.secure_importer.temporary_sys_path = temporary_sys_path

        batch = MagicMock()
        batch._get_pipeline_config.return_value = {"nodes": ["n"]}
        batch.node_executor._function_loader = loader

        executor = object.__new__(PipelineExecutor)
        executor.context = type("Ctx", (), {"nodes_config": {"n": {"module": module_name}}})()
        # Seed the lazy property's backing field rather than replacing the
        # property: patching it on the class would leak into every later test.
        executor._batch_executor = batch
        return executor._code_fingerprint("p")

    def test_identical_source_under_different_mtimes_is_the_same_fingerprint(self, tmp_path):
        a = self._fingerprint(tmp_path / "a", "same_src", "def f():\n    return 1\n", 1_000_000.0)
        b = self._fingerprint(tmp_path / "b", "same_src", "def f():\n    return 1\n", 2_000_000.0)
        assert a is not None and a == b
        assert a.startswith("sha256:")

    def test_changed_source_under_the_same_mtime_is_a_different_fingerprint(self, tmp_path):
        """The case an mtime marker misses: restored timestamps, different code."""
        a = self._fingerprint(tmp_path / "a", "diff_src", "def f():\n    return 1\n", 1_000_000.0)
        b = self._fingerprint(tmp_path / "b", "diff_src", "def f():\n    return 2\n", 1_000_000.0)
        assert a is not None and a != b

    def test_a_marker_from_the_old_mtime_scheme_no_longer_matches(self):
        """Fails closed: one recomputation beats one unnoticed stale result."""
        from ducta.core.executors.facade import PipelineExecutor
        from ducta.core.settings import CoreSettings

        executor = object.__new__(PipelineExecutor)
        executor.settings = CoreSettings()
        executor._config_fingerprint = lambda: "cfg-1"
        executor._code_fingerprint = lambda _p: "sha256:abc"
        state = {"config_fingerprint": "cfg-1", "code_fingerprint": "mtime:1700000000.000000"}

        assert executor._provenance_still_matches("bronze", state) is False
