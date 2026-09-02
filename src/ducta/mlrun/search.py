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

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from itertools import product
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ducta.mlrun.hyperparams import HyperparamConfig, HyperparamConfigError

MAXIMIZE = "maximize"
MINIMIZE = "minimize"


class SearchError(ValueError):
    """Raised when a search strategy cannot be built or driven."""


class SearchStrategy(ABC):
    """Proposes hyperparameter sets and records how each one scored."""

    def __init__(self, direction: str = MAXIMIZE, n_trials: int = 10) -> None:
        direction = (direction or MAXIMIZE).lower()
        if direction not in (MAXIMIZE, MINIMIZE):
            raise SearchError(
                f"Unknown objective direction '{direction}'. Valid: maximize, minimize"
            )
        self.direction = direction
        self.n_trials = int(n_trials)
        self._history: List[Tuple[Dict[str, Any], Optional[float]]] = []

    @abstractmethod
    def ask(self) -> Optional[Dict[str, Any]]:
        """Next hyperparameter set to try, or ``None`` when the search is done."""

    def tell(self, params: Dict[str, Any], score: Optional[float]) -> None:
        """Record the objective value a proposed set achieved."""
        self._history.append((params, score))

    @property
    def history(self) -> List[Tuple[Dict[str, Any], Optional[float]]]:
        return list(self._history)

    @property
    def best(self) -> Optional[Tuple[Dict[str, Any], float]]:
        """Best ``(params, score)`` seen so far, or ``None`` if nothing scored."""
        scored = [(p, s) for p, s in self._history if s is not None and math.isfinite(s)]
        if not scored:
            return None
        pick = max if self.direction == MAXIMIZE else min
        return pick(scored, key=lambda item: item[1])


class GridSearch(SearchStrategy):
    """Exhaustive cartesian product, driven by ``build_param_grid()``."""

    def __init__(self, config: HyperparamConfig, max_trials: Optional[int] = None) -> None:
        grid = config.build_param_grid()
        sub_grids = grid if isinstance(grid, list) else [grid]

        combos: List[Dict[str, Any]] = []
        for sub in sub_grids:
            names = list(sub.keys())
            if not names:
                continue
            for values in product(*(sub[name] for name in names)):
                combos.append(dict(zip(names, values)))

        # Deduplicate while preserving order: overlapping conditional sub-grids
        # can propose the same combination twice.
        seen = set()
        unique: List[Dict[str, Any]] = []
        for combo in combos:
            key = tuple(sorted(combo.items(), key=lambda kv: kv[0]))
            if key not in seen:
                seen.add(key)
                unique.append(combo)

        if max_trials is not None and len(unique) > max_trials:
            raise SearchError(
                f"Grid search would run {len(unique)} trials, over the limit of {max_trials}. "
                "Narrow the search_space, or use algorithm='random'/'bayesian' with n_trials."
            )

        self._combos = unique
        self._index = 0
        super().__init__(
            direction=(config.objective or {}).get("type", MAXIMIZE), n_trials=len(unique)
        )

    def ask(self) -> Optional[Dict[str, Any]]:
        if self._index >= len(self._combos):
            return None
        combo = self._combos[self._index]
        self._index += 1
        return dict(combo)


class RandomSearch(SearchStrategy):
    """Random sampling over the declared space, capped at ``n_trials``."""

    def __init__(
        self, config: HyperparamConfig, n_trials: Optional[int] = None, seed: Optional[int] = None
    ) -> None:
        super().__init__(
            direction=(config.objective or {}).get("type", MAXIMIZE),
            n_trials=int(n_trials or config.n_trials),
        )
        if config.has_conditional_params():
            logger.warning(
                "Random search over a space with conditional params (depends_on) can "
                "propose invalid parent/child combinations. Use algorithm='grid' or "
                "'bayesian' for conditional spaces."
            )
        self._distributions = config.build_distributions()
        self._asked = 0
        import random

        self._rng = random.Random(seed)

    def ask(self) -> Optional[Dict[str, Any]]:
        if self._asked >= self.n_trials:
            return None
        self._asked += 1

        params: Dict[str, Any] = {}
        for name, dist in self._distributions.items():
            if hasattr(dist, "rvs"):
                params[name] = float(dist.rvs(random_state=self._rng.randint(0, 2**31 - 1)))
            else:
                params[name] = self._rng.choice(list(dist))
        return params


class OptunaSearch(SearchStrategy):
    """Bayesian (TPE) search backed by an Optuna study."""

    def __init__(
        self,
        config: HyperparamConfig,
        n_trials: Optional[int] = None,
        seed: Optional[int] = None,
        study_name: Optional[str] = None,
    ) -> None:
        super().__init__(
            direction=(config.objective or {}).get("type", MAXIMIZE),
            n_trials=int(n_trials or config.n_trials),
        )
        try:
            import optuna
        except ImportError as e:
            raise SearchError(
                "Bayesian search requires 'optuna'. Install with: pip install optuna, "
                "or use algorithm='grid'/'random'."
            ) from e

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        self._config = config
        self._optuna = optuna
        self._study = optuna.create_study(
            direction=self.direction,
            study_name=study_name,
            storage=config.storage,
            load_if_exists=bool(config.storage and study_name),
            sampler=optuna.samplers.TPESampler(seed=seed),
            pruner=self._build_pruner(optuna, config.pruner),
        )
        self._asked = 0
        self._pending: Dict[int, Any] = {}
        self._trial_by_params: Dict[str, int] = {}

    @staticmethod
    def _build_pruner(optuna: Any, pruner_name: Optional[str]) -> Optional[Any]:
        """Map a validated pruner name to an Optuna pruner instance."""
        if pruner_name is None:
            return None
        if pruner_name == "none":
            return optuna.pruners.NopPruner()
        if pruner_name == "median":
            return optuna.pruners.MedianPruner()
        if pruner_name == "hyperband":
            return optuna.pruners.HyperbandPruner()
        raise SearchError(f"Unknown pruner '{pruner_name}'. Valid: median, hyperband, none")

    @staticmethod
    def _key(params: Dict[str, Any]) -> str:
        return repr(sorted(params.items(), key=lambda kv: kv[0]))

    def ask(self) -> Optional[Dict[str, Any]]:
        if self._asked >= self.n_trials:
            return None
        self._asked += 1
        trial = self._study.ask()
        params = self._config.suggest_params(trial)
        self._pending[trial.number] = trial
        self._trial_by_params[self._key(params)] = trial.number
        return params

    def tell(self, params: Dict[str, Any], score: Optional[float]) -> None:
        super().tell(params, score)
        number = self._trial_by_params.pop(self._key(params), None)
        if number is None:
            logger.debug("OptunaSearch.tell called with params it never proposed: {}", params)
            return
        self._pending.pop(number, None)
        if score is None or not math.isfinite(score):
            self._study.tell(number, state=self._optuna.trial.TrialState.FAIL)
            return
        self._study.tell(number, float(score))


def build_search_strategy(
    config: HyperparamConfig,
    n_trials: Optional[int] = None,
    seed: Optional[int] = None,
    max_grid_trials: Optional[int] = None,
    study_name: Optional[str] = None,
) -> SearchStrategy:
    """Build the strategy ``config.algorithm`` asks for."""
    if not config.search_space:
        raise SearchError(
            "Cannot build a search strategy: 'search_space' is empty. Declare the "
            "parameters to search under hyperparams_config.search_space."
        )

    algorithm = config.algorithm
    if algorithm == "grid":
        return GridSearch(config, max_trials=max_grid_trials)
    if algorithm == "random":
        return RandomSearch(config, n_trials=n_trials, seed=seed)
    if algorithm == "bayesian":
        return OptunaSearch(config, n_trials=n_trials, seed=seed, study_name=study_name)
    raise SearchError(
        f"Unknown algorithm '{algorithm}'. Valid: {HyperparamConfig.VALID_ALGORITHMS}"
    )


def resolve_objective(config: HyperparamConfig) -> Tuple[str, str]:
    """Return ``(metric_name, direction)`` for the configured objective."""
    objective = config.objective or {}
    metric = (objective.get("metric") or "").strip()
    if not metric:
        raise HyperparamConfigError(
            "Search requires an objective metric: set hyperparams_config.objective."
            "metric to the name of the metric your training node logs (e.g. val_f1). "
            "Point it at a validation metric, never a test one."
        )
    direction = (objective.get("type") or MAXIMIZE).lower()
    if direction not in (MAXIMIZE, MINIMIZE):
        raise HyperparamConfigError(
            f"objective.type must be 'maximize' or 'minimize', got '{direction}'"
        )
    return metric, direction
