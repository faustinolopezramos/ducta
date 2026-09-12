"""In-memory handoff for pandas DataFrames.

The handoff store existed but only accepted Spark frames (it required
`.persist()` and `.rdd`), so in-memory handoff did nothing for ML pipelines —
which are pandas end to end (split_dataframe requires pandas, sklearn trains on
it) and are exactly where a memory→parquet→memory round trip between feature
engineering and training costs the most.

pandas needs the opposite treatment to Spark: Spark frames are immutable and
can be shared as-is, while a shared mutable pandas frame would let one node's
in-place edit change what a concurrently running node reads.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.gate import handoff


class FakeContext:
    def __init__(self, enabled: bool = True):
        self.global_config = {"in_memory_handoff": enabled}


@pytest.fixture
def frame():
    return pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})


class TestPandasIsCached:
    def test_offer_then_take_round_trips_the_frame(self, frame):
        context = FakeContext()
        handoff.offer(context, "/out/clean", frame, "overwrite")
        assert handoff.take(context, "/out/clean").equals(frame)

    def test_disabled_by_default_nothing_is_cached(self, frame):
        context = FakeContext(enabled=False)
        handoff.offer(context, "/out/clean", frame, "overwrite")
        assert handoff.take(context, "/out/clean") is None

    def test_only_overwrite_mode_is_eligible(self, frame):
        """An append write does not produce the full dataset, so caching it
        would serve a partial frame to downstream nodes."""
        context = FakeContext()
        handoff.offer(context, "/out/appended", frame, "append")
        assert handoff.take(context, "/out/appended") is None

    def test_a_missing_path_returns_none(self):
        assert handoff.take(FakeContext(), "/out/never-written") is None

    def test_clear_drops_everything(self, frame):
        context = FakeContext()
        handoff.offer(context, "/out/clean", frame, "overwrite")
        handoff.clear(context)
        assert handoff.take(context, "/out/clean") is None

    def test_clear_does_not_choke_on_frames_without_unpersist(self, frame):
        """pandas has no unpersist(); clearing must not raise on it."""
        context = FakeContext()
        handoff.offer(context, "/out/clean", frame, "overwrite")
        handoff.clear(context)  # must not raise


class TestMutationIsolation:
    def test_mutating_a_taken_frame_does_not_corrupt_the_cache(self, frame):
        context = FakeContext()
        handoff.offer(context, "/out/clean", frame, "overwrite")

        taken = handoff.take(context, "/out/clean")
        taken.loc[0, "a"] = 999

        assert handoff.take(context, "/out/clean").loc[0, "a"] == 1

    def test_mutating_a_taken_frame_does_not_corrupt_the_producer(self, frame):
        context = FakeContext()
        handoff.offer(context, "/out/clean", frame, "overwrite")

        taken = handoff.take(context, "/out/clean")
        taken.loc[0, "a"] = 999

        assert frame.loc[0, "a"] == 1

    def test_mutating_the_producer_after_offering_does_not_change_the_cache(self, frame):
        """offer() snapshots, so a producing node that keeps editing its frame
        after returning cannot retroactively change what consumers read."""
        context = FakeContext()
        handoff.offer(context, "/out/clean", frame, "overwrite")

        frame.loc[0, "a"] = 999

        assert handoff.take(context, "/out/clean").loc[0, "a"] == 1

    def test_concurrent_consumers_get_independent_objects(self, frame):
        """The DAG coordinator runs ready nodes in parallel, so two consumers
        of the same upstream dataset can hold their frames at once."""
        context = FakeContext()
        handoff.offer(context, "/out/clean", frame, "overwrite")

        first = handoff.take(context, "/out/clean")
        second = handoff.take(context, "/out/clean")

        assert first is not second
        first.loc[0, "a"] = 999
        assert second.loc[0, "a"] == 1


class TestNonDataFrames:
    def test_a_plain_object_is_not_cached(self):
        context = FakeContext()
        handoff.offer(context, "/out/thing", {"not": "a frame"}, "overwrite")
        assert handoff.take(context, "/out/thing") is None

    def test_none_is_not_cached(self):
        context = FakeContext()
        handoff.offer(context, "/out/nothing", None, "overwrite")
        assert handoff.take(context, "/out/nothing") is None
