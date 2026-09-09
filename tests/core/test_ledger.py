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

    def test_start_clears_the_previous_runs_fingerprints(self):
        # Regression: these used to survive a reset because ducta.gate writes
        # them. One executor drives every pipeline in a chain and the gate
        # accumulates into the same context dicts, so pipeline N+1's certificate
        # claimed N's inputs and outputs as its own — and `certify verify`
        # passed on it, because the hash covers the wrong answer just as
        # happily as the right one.
        context = _ctx(_input_fingerprints={"in": "sha1"}, _output_fingerprints={"out": "sha2"})

        ledger = RunLedger.start(context, "run-2")

        assert ledger.input_fingerprints == {}
        assert ledger.output_fingerprints == {}

    def test_start_leaves_the_previous_runs_input_fingerprints_alone(self):
        # A different attribute with a different owner: the *previous*
        # successful run's fingerprints, loaded by core.mlops_integration and
        # read by gate.input's fingerprint_policy. Clearing it would silently
        # disable that policy.
        context = _ctx(_previous_input_fingerprints={"in": {"fingerprint": "sha1"}})

        ledger = RunLedger.start(context, "run-2")

        assert ledger.previous_input_fingerprints == {"in": {"fingerprint": "sha1"}}


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


class _ReadOnlyContext:
    """A context whose ledger attributes cannot be written.

    Stands in for whatever makes a real context reject a setattr — a frozen
    dataclass, a __slots__ class, a proxy. What matters is that recording
    fails and the ledger has to survive it.
    """

    __slots__ = ("run_ledger",)


class TestEvidenceCompleteness:
    def test_a_clean_run_reports_complete_evidence(self):
        ledger = RunLedger.start(_ctx(), "run-1")
        ledger.record_node("a", "success")
        ledger.record_quality({"node": "a", "passed": True})

        assert ledger.evidence_complete is True
        assert ledger.record_failures == []

    def test_a_failed_write_marks_the_evidence_incomplete(self):
        ledger = RunLedger(_ReadOnlyContext())

        ledger.record_node("a", "success")

        assert ledger.evidence_complete is False
        assert any("node trace for 'a'" in gap for gap in ledger.record_failures)

    def test_a_failed_write_does_not_raise(self):
        # Bookkeeping must never be the reason a pipeline fails.
        ledger = RunLedger(_ReadOnlyContext())
        ledger.record_node("a", "success")
        ledger.record_quality({"node": "a", "passed": False})

    def test_recording_failure_does_not_deadlock(self):
        # `_append` holds the lock while calling `_set`, and both route failures
        # through `_note_failure`, which takes it again. With a non-reentrant
        # lock this hangs forever rather than failing.
        ledger = RunLedger(_ReadOnlyContext())
        done = threading.Event()

        def _record():
            ledger.record_node("a", "success")
            done.set()

        worker = threading.Thread(target=_record, daemon=True)
        worker.start()
        assert done.wait(timeout=5), "recording a failure deadlocked"

    def test_a_non_list_bucket_is_reported_rather_than_ignored(self):
        # The wire format is a plain context attribute, so anything can land in
        # it. Appending used to no-op silently when it was not a list.
        context = _ctx(_run_node_details="not a list")
        ledger = RunLedger(context)

        ledger.record_node("a", "success")

        assert ledger.evidence_complete is False

    def test_reset_clears_failures_from_the_previous_pipeline(self):
        # One executor drives several pipelines in a chain; pipeline N's gap
        # must not mark pipeline N+1's certificate incomplete.
        context = _ctx(_run_node_details="not a list")
        ledger = RunLedger(context)
        ledger.record_node("a", "success")
        assert ledger.evidence_complete is False

        context._run_node_details = []
        ledger.reset()

        assert ledger.evidence_complete is True
        assert ledger.record_failures == []
