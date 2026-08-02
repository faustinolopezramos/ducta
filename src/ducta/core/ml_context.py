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

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Iterator, List, Optional

from ducta.mlrun.hyperparams import HyperparamConfig


@dataclass
class MLNodeContext(Mapping):
    """Typed, discoverable context delivered to ML nodes as ``ml_context``."""

    # Model / experiment identity
    model_version: Optional[str] = None
    hyperparams: Dict[str, Any] = field(default_factory=dict)

    # Structured hyperparameter config (HyperparamConfig or None)
    hyperparams_config: Optional[HyperparamConfig] = None

    # Reproducibility
    seed: Optional[int] = None
    node_seed: Optional[int] = None
    split: Optional[Dict[str, Any]] = None

    # Configuration snapshots
    node_config: Dict[str, Any] = field(default_factory=dict)
    pipeline_config: Dict[str, Any] = field(default_factory=dict)
    execution_metadata: Dict[str, Any] = field(default_factory=dict)

    # MLOps tracking handles
    mlops_context: Any = None
    mlops_run_id: Optional[str] = None

    # Engine handle (present only when Spark is available)
    spark: Any = None

    # ------------------------------------------------------------------
    # Mapping interface — keeps dict-style access working for existing nodes.
    # ------------------------------------------------------------------
    def _keys(self) -> List[str]:
        return [f.name for f in fields(self)]

    def __getitem__(self, key: str) -> Any:
        if key in self._keys():
            return getattr(self, key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys())

    def __len__(self) -> int:
        return len(self._keys())

    def __contains__(self, key: object) -> bool:
        return key in self._keys()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default) if key in self._keys() else default

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict copy (e.g. for serialization or legacy callers)."""
        return {name: getattr(self, name) for name in self._keys()}
