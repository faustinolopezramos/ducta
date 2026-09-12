"""Regression: a config typo cost a JVM startup before anyone looked at the config.

`PipelineExecutor.run_pipeline` read the pipeline config through
`self.batch_executor`, and that property builds `BatchExecutor` →
`DataOutputManager` → `UnityCatalogManager`, whose constructor asked the session
whether Unity Catalog was enabled. So a one-character typo in `nodes.yaml` paid
for a full Spark session and printed a Spark banner *before* the preflight error
— about 10s instead of 1s, on a project that never touches Unity Catalog. The
README's promise that "the session is created lazily on first genuine access"
did not hold for any project.

Two changes, both asserted here: `UnityCatalogManager` resolves lazily, and
preflight runs before anything constructs an executor.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ducta.core.errors import PreflightError
from ducta.gate.output.unity_catalog import UnityCatalogManager


class TestUnityCatalogDoesNotTouchSparkAtConstruction:
    def test_constructing_it_asks_for_no_session(self):
        context = MagicMock()
        # A property that explodes if anyone reads it: constructing the manager
        # must not.
        type(context).spark = property(
            lambda _self: pytest.fail("constructor created a Spark session")
        )

        manager = UnityCatalogManager(context)

        assert manager._enabled is None

    def test_the_answer_is_resolved_and_cached_on_first_use(self):
        context = SimpleNamespace(spark=None)
        manager = UnityCatalogManager(context)
        calls = []

        def _check():
            calls.append(1)
            return False

        manager._check_enabled = _check

        assert manager.is_enabled() is False
        assert manager.is_enabled() is False
        assert len(calls) == 1, "is_enabled must cache, not re-ask the session each time"


class TestPreflightRunsBeforeTheExecutorIsBuilt:
    def test_a_failing_preflight_never_reaches_batch_executor(self, monkeypatch):
        from ducta.core.executors.facade import PipelineExecutor

        # monkeypatch, not a bare `type(executor).x = ...` + `del`: `del` would
        # remove the real property from the class for the rest of the session.
        monkeypatch.setattr(
            PipelineExecutor,
            "batch_executor",
            property(lambda _self: pytest.fail("batch_executor was built before preflight ran")),
        )
        executor = object.__new__(PipelineExecutor)
        executor._run_preflight = MagicMock(
            side_effect=PreflightError(pipeline="etl", errors=["bad input key"])
        )

        with pytest.raises(PreflightError):
            executor.run_pipeline("etl")

        executor._run_preflight.assert_called_once_with("etl")
