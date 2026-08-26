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

import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from ducta.mlrun.hyperparams import SweepLimitError, expand_sweep_grid


class SweepError(ValueError):
    """Raised when a sweep spec is invalid or too large."""


def load_sweep_spec(path: str) -> Dict[str, Any]:
    """Load a sweep spec from a YAML or JSON file."""
    spec_path = Path(path)
    if not spec_path.is_file():
        raise SweepError(f"Sweep spec not found: {path}")

    text = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        spec = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise SweepError("YAML sweep specs require PyYAML (pip install PyYAML)") from e
        spec = yaml.safe_load(text)

    if not isinstance(spec, dict) or not spec:
        raise SweepError(f"Sweep spec must be a non-empty mapping, got: {type(spec).__name__}")
    return spec


def expand_sweep(spec: Dict[str, Any], max_runs: int = 50) -> List[Dict[str, Any]]:
    """Expand list values into the cartesian product of hyperparameter dicts."""
    try:
        return expand_sweep_grid(spec, max_runs=max_runs)
    except SweepLimitError as e:
        raise SweepError(str(e)) from e


def new_sweep_id() -> str:
    """Readable, unique sweep identifier."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"sweep-{stamp}-{uuid4().hex[:6]}"


@dataclass
class TrialOutcome:
    """What one search trial produced."""

    index: int
    params: Dict[str, Any]
    score: Optional[float]
    failed: bool = False
    reason: Optional[str] = None


@dataclass
class SearchOutcome:
    """Aggregate result of a driven hyperparameter search."""

    search_id: str
    metric: str
    direction: str
    trials: List[TrialOutcome] = dataclass_field(default_factory=list)
    best_params: Optional[Dict[str, Any]] = None
    best_score: Optional[float] = None

    @property
    def failures(self) -> int:
        return sum(1 for t in self.trials if t.failed)

    @property
    def succeeded(self) -> int:
        return len(self.trials) - self.failures


def new_search_id() -> str:
    """Readable, unique search identifier."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"search-{stamp}-{uuid4().hex[:6]}"


def run_search(
    strategy: Any,
    metric: str,
    run_trial: Callable[[Dict[str, Any], int], Any],
    search_id: Optional[str] = None,
) -> SearchOutcome:
    """Drive ``strategy`` to completion, executing each trial via ``run_trial``.
    """
    search_id = search_id or new_search_id()
    outcome = SearchOutcome(
        search_id=search_id, metric=metric, direction=getattr(strategy, "direction", "maximize")
    )

    index = 0
    while True:
        params = strategy.ask()
        if params is None:
            break
        index += 1

        score: Optional[float] = None
        failed = False
        reason: Optional[str] = None
        try:
            result = run_trial(params, index)
            gate_blocked = getattr(result, "gate_blocked", None) or {}
            if gate_blocked:
                failed = True
                reason = f"blocked by quality gate: {', '.join(sorted(gate_blocked))}"
            else:
                metrics = getattr(result, "metrics", None) or {}
                if metric in metrics:
                    score = float(metrics[metric])
                else:
                    failed = True
                    reason = (
                        f"run logged no '{metric}' metric "
                        f"(logged: {', '.join(sorted(metrics)) or 'none'})"
                    )
        except Exception as e:  # noqa: BLE001 — one bad trial must not end the search
            failed = True
            reason = str(e)

        strategy.tell(params, score)
        outcome.trials.append(
            TrialOutcome(index=index, params=params, score=score, failed=failed, reason=reason)
        )

    best = getattr(strategy, "best", None)
    if best is not None:
        outcome.best_params, outcome.best_score = best
    return outcome
