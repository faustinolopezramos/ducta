"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0
"""

from typing import Any, Dict

from loguru import logger  # type: ignore

from ducta.check.storage import DEFAULT_PIPELINE_NAME, StorageBackend


def _percentile(values: list, pct: float) -> float:
    """Nearest-rank percentile of *values* (0.0 <= pct <= 1.0). Assumes non-empty."""
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[idx]


class ThresholdAdvisor:
    """Analyzes historical metrics to propose optimal quality thresholds."""

    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage

    def analyze_history(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> Dict[str, Any]:
        """Analyze history and return proposed thresholds."""
        try:
            history = self.storage.load_history(dataset_name, pipeline_name)
            if not history or len(history) < 5:
                return {"ready": False, "message": "Insufficient history (min 5 runs)"}

            row_counts = [
                h["row_count"] for h in history if isinstance(h.get("row_count"), (int, float))
            ]

            # Anchoring to the historical minimum (or averaging in blocked/failed
            # runs) ratchets thresholds down every time a bad run happens — a bad
            # run makes the *next* proposal more permissive instead of flagging
            # the regression. Anchor to the 10th percentile of runs that
            # actually passed instead, excluding anything the gate blocked or
            # that had check failures.
            passing_scores = [
                h["score"]
                for h in history
                if isinstance(h.get("score"), (int, float))
                and h.get("gate_action") != "block"
                and not h.get("errors_count")
            ]

            if not passing_scores:
                return {"ready": False, "message": "No passing runs found in history"}

            # Calculate basic stats (from passing runs only, for the same reason)
            avg_score = sum(passing_scores) / len(passing_scores)
            p10_score = _percentile(passing_scores, 0.10)

            # Propose block_threshold as p10 - 5% (buffer)
            proposed_block = max(0.0, p10_score * 0.95)
            # Propose warn_threshold as avg_score * 0.98
            proposed_warn = max(proposed_block + 0.01, avg_score * 0.98)

            result = {
                "ready": True,
                "runs_analyzed": len(history),
                "proposed_thresholds": {
                    "block_threshold": round(proposed_block, 4),
                    "warn_threshold": round(proposed_warn, 4),
                    "score_threshold": round(proposed_block, 4),  # Alias for block_threshold
                },
                "stats": {
                    "avg_score": round(avg_score, 4),
                    "min_score": round(min(passing_scores), 4),
                    "p10_score": round(p10_score, 4),
                    "avg_row_count": (
                        round(sum(row_counts) / len(row_counts), 0) if row_counts else 0
                    ),
                },
            }

            logger.info(
                "Advisor: Proposed thresholds for '{}' based on {} runs: block={}, warn={}",
                dataset_name,
                len(history),
                result["proposed_thresholds"]["block_threshold"],
                result["proposed_thresholds"]["warn_threshold"],
            )

            return result

        except Exception as e:
            logger.error(f"Failed to analyze history for '{dataset_name}': {e}")
            return {"ready": False, "error": str(e)}
