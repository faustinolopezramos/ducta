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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
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
