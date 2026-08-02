"""Regression tests for ducta.check.advisor.ThresholdAdvisor.

`analyze_history` used to propose `block_threshold = min(all_scores) * 0.95`,
including runs the gate had already blocked or that had check failures. That
ratchets thresholds down every time a bad run happens — a regression makes
the *next* proposal more permissive instead of flagging it. It now anchors to
the 10th percentile of only the runs that actually passed.
"""

from __future__ import annotations

from ducta.check.advisor import ThresholdAdvisor
from ducta.check.storage import FileStorageBackend


def _seed_history(storage, dataset_name, entries):
    for entry in entries:
        storage.append_history(dataset_name, entry)


class TestAnalyzeHistoryExcludesBlockedAndFailedRuns:
    def test_a_single_bad_run_does_not_ratchet_the_threshold_down(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        good_entries = [
            {"row_count": 100, "score": s, "errors_count": 0, "gate_action": "pass"}
            for s in [0.95, 0.96, 0.94, 0.97, 0.95, 0.96]
        ]
        # One bad run: gate blocked it, score cratered.
        bad_entry = {"row_count": 100, "score": 0.10, "errors_count": 3, "gate_action": "block"}
        _seed_history(storage, "ds", good_entries + [bad_entry])

        advisor = ThresholdAdvisor(storage)
        result = advisor.analyze_history("ds")

        assert result["ready"] is True
        # Anchored to the passing runs only — nowhere near the 0.10 outlier.
        assert result["proposed_thresholds"]["block_threshold"] > 0.5
        assert result["stats"]["min_score"] >= 0.94

    def test_errors_count_alone_excludes_a_run_even_without_an_explicit_block(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        good_entries = [
            {"row_count": 100, "score": s, "errors_count": 0, "gate_action": "none"}
            for s in [0.9, 0.91, 0.92, 0.93, 0.9]
        ]
        failed_entry = {
            "row_count": 100,
            "score": 0.2,
            "errors_count": 5,
            "gate_action": "none",
        }
        _seed_history(storage, "ds", good_entries + [failed_entry])

        advisor = ThresholdAdvisor(storage)
        result = advisor.analyze_history("ds")

        assert result["ready"] is True
        assert result["stats"]["min_score"] >= 0.9

    def test_not_ready_when_no_passing_runs_exist(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        all_blocked = [
            {"row_count": 100, "score": 0.3, "errors_count": 2, "gate_action": "block"}
            for _ in range(6)
        ]
        _seed_history(storage, "ds", all_blocked)

        advisor = ThresholdAdvisor(storage)
        result = advisor.analyze_history("ds")

        assert result["ready"] is False

    def test_not_ready_with_insufficient_history(self, tmp_path):
        storage = FileStorageBackend(str(tmp_path))
        _seed_history(
            storage,
            "ds",
            [{"row_count": 100, "score": 0.9, "errors_count": 0, "gate_action": "pass"}] * 2,
        )

        advisor = ThresholdAdvisor(storage)
        result = advisor.analyze_history("ds")

        assert result["ready"] is False
