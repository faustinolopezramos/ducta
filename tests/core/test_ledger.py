"""RunLedger: the run's evidence protocol, named instead of implied.

Six underscore attributes stashed on the shared Context with setattr and read
back with getattr, appended to from parallel worker threads with per-call-site
(or missing) locking. A typo in any spelling degraded silently to "no evidence
recorded" — which for a run certificate means one that is quietly missing the
thing it exists to attest.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from ducta.core.ledger import RunLedger, ledger_for


def _ctx(**attrs):
    return SimpleNamespace(**attrs)


class TestLifecycle:
    def test_start_stamps_the_run_id(self):
        ledger = RunLedger.start(_ctx(), "abc123")
        assert ledger.run_id == "abc123"

    def test_start_clears_the_previous_run(self):
        # A single executor drives several pipelines in a chain; without the
        # reset, one pipeline's trace leaks into the next one's certificate.
        context = _ctx()
        first = RunLedger.start(context, "run-1")
        first.record_node("a", "success")

        second = RunLedger.start(context, "run-2")

        assert second.node_details == []
        assert second.run_id == "run-2"

    def test_reset_leaves_fingerprints_alone(self):
        # Fingerprints are written by ducta.gate as IO happens, not by the run's
        # own bookkeeping.
        context = _ctx(_input_fingerprints={"in": "sha1"}, _output_fingerprints={"out": "sha2"})
        ledger = RunLedger.start(context, "run-1")

        assert ledger.input_fingerprints == {"in": "sha1"}
        assert ledger.output_fingerprints == {"out": "sha2"}


class TestNodeTrace:
    def test_a_recorded_node_round_trips(self):
        ledger = RunLedger.start(_ctx(), "r")
        ledger.record_node("extract", "success", duration_seconds=1.2345, outputs=["a.b.c"])

        (record,) = ledger.node_details
        assert record["name"] == "extract"
        assert record["status"] == "success"
        assert record["duration_seconds"] == 1.234  # rounded to ms
        assert record["outputs"] == ["a.b.c"]
        assert record["error"] is None

    def test_node_details_returns_a_snapshot_copy(self):
        ledger = RunLedger.start(_ctx(), "r")
        ledger.record_node("a", "success")

        snapshot = ledger.node_details
        snapshot.append({"name": "injected"})

        assert [r["name"] for r in ledger.node_details] == ["a"]

    def test_the_wire_format_stays_on_the_context(self):
        # ducta.gate and the API still read these attributes directly, so both
        # views must agree while those layers migrate.
        context = _ctx()
        RunLedger.start(context, "r").record_node("a", "success")

        assert [r["name"] for r in context._run_node_details] == ["a"]
        assert context._run_id == "r"


class TestQuality:
    def test_quality_entries_accumulate(self):
        ledger = RunLedger.start(_ctx(), "r")
        ledger.record_quality({"node": "a", "phase": "sanity", "passed": True})
        ledger.record_quality({"node": "a", "phase": "data_quality", "passed": False})

        assert [e["phase"] for e in ledger.quality_results] == ["sanity", "data_quality"]


class TestThreadSafety:
    def test_concurrent_node_records_are_not_lost(self):
        # Nodes run on a thread pool; every append must survive.
        ledger = RunLedger.start(_ctx(), "r")

        def record(start: int):
            for i in range(50):
                ledger.record_node(f"n{start}_{i}", "success")

        threads = [threading.Thread(target=record, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ledger.node_details) == 400
        assert len({r["name"] for r in ledger.node_details}) == 400

    def test_concurrent_quality_records_are_not_lost(self):
        ledger = RunLedger.start(_ctx(), "r")

        def record(start: int):
            for i in range(50):
                ledger.record_quality({"node": f"n{start}_{i}"})

        threads = [threading.Thread(target=record, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ledger.quality_results) == 400


class TestResilience:
    def test_recording_never_raises_on_a_hostile_context(self):
        class Locked:
            __slots__ = ()  # setattr raises

        ledger = RunLedger(Locked())
        # Best-effort by design: bookkeeping must not be why a pipeline fails.
        ledger.record_node("a", "success")
        ledger.record_quality({"node": "a"})

        assert ledger.node_details == []

    def test_a_dict_context_is_supported(self):
        context: dict = {}
        ledger = RunLedger.start(context, "r")
        ledger.record_node("a", "success")

        assert context["_run_id"] == "r"
        assert [r["name"] for r in context["_run_node_details"]] == ["a"]

    def test_missing_attributes_read_as_empty(self):
        ledger = RunLedger(_ctx())

        assert ledger.node_details == []
        assert ledger.quality_results == []
        assert ledger.input_fingerprints == {}
        assert ledger.run_id is None


class TestLedgerFor:
    def test_it_creates_and_caches_one_ledger_per_context(self):
        context = _ctx()

        first = ledger_for(context)
        second = ledger_for(context)

        assert first is second
        assert context.run_ledger is first

    def test_an_existing_ledger_is_reused(self):
        context = _ctx()
        ledger = RunLedger.start(context, "r")
        context.run_ledger = ledger

        assert ledger_for(context) is ledger

    def test_concurrent_first_calls_all_get_the_same_instance(self):
        """Regression: ledger_for()'s getattr/setattr check-then-act had no
        lock of its own, so N threads racing to call it on a fresh context
        before any of them had cached one could each construct and setattr
        a *different* RunLedger — every caller thinking it holds "the"
        ledger while some of them silently write to one nobody else sees."""
        context = _ctx()
        barrier = threading.Barrier(16)
        results: list = [None] * 16

        def call(i: int):
            barrier.wait(timeout=2.0)
            results[i] = ledger_for(context)

        threads = [threading.Thread(target=call, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert all(r is results[0] for r in results)
        assert context.run_ledger is results[0]

    def test_a_read_only_context_still_gets_a_working_ledger(self):
        class Locked:
            __slots__ = ()

        ledger = ledger_for(Locked())
        assert isinstance(ledger, RunLedger)
