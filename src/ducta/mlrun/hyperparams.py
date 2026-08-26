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

import itertools
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from loguru import logger


class HyperparamConfigError(ValueError):
    """Raised when the hyperparameter configuration is invalid."""


ParamGrid = Dict[str, Sequence[Union[str, int, float]]]
"""sklearn-style param_grid: ``{param_name: [values]}``."""

Distribution = Dict[str, Any]
"""sklearn-style distribution dict for RandomizedSearchCV."""


class HyperparamConfig:
    """Validated hyperparameter search configuration.
    """

    VALID_ALGORITHMS = ("grid", "random", "bayesian")
    VALID_PRUNERS = ("median", "hyperband", "none")

    def __init__(
        self,
        algorithm: str = "grid",
        cv_folds: int = 5,
        n_trials: Optional[int] = None,
        objective: Optional[Dict[str, str]] = None,
        search_space: Optional[Dict[str, Any]] = None,
        storage: Optional[str] = None,
        pruner: Optional[str] = None,
        study_name: Optional[str] = None,
    ) -> None:
        algorithm = algorithm.lower()
        if algorithm not in self.VALID_ALGORITHMS:
            raise HyperparamConfigError(
                f"Unknown algorithm '{algorithm}'. Valid: {self.VALID_ALGORITHMS}"
            )
        self.algorithm = algorithm
        self.cv_folds = cv_folds
        self.n_trials = n_trials or {"grid": 1, "random": 30, "bayesian": 50}.get(algorithm, 30)
        self.objective = objective or {"metric": "", "type": "minimize"}
        self.search_space = dict(search_space or {})
        self.storage = storage
        self.study_name = study_name


        self.pruner: Optional[str] = None
        if pruner is not None:
            pruner_normalized = pruner.lower()
            if pruner_normalized not in self.VALID_PRUNERS:
                raise HyperparamConfigError(
                    f"Unknown pruner '{pruner}'. Valid: {self.VALID_PRUNERS}"
                )
            self.pruner = pruner_normalized
        if self.pruner is not None and algorithm != "bayesian":
            logger.warning(
                "pruner='{}' has no effect for algorithm='{}': pruning is only "
                "wired up for the Optuna-backed 'bayesian' strategy.",
                self.pruner,
                algorithm,
            )

        if algorithm == "bayesian":
            try:
                import optuna  # noqa: F401
            except ImportError:
                raise HyperparamConfigError(
                    "Bayesian search requires 'optuna'. Install with: pip install optuna"
                )

        self._validate_dependencies()


    @classmethod
    def from_dict(cls, data: dict) -> "HyperparamConfig":
        """Build from a dict (loaded from YAML or JSON)."""
        return cls(
            algorithm=data.get("algorithm", "grid"),
            cv_folds=int(data.get("cv_folds", 5)),
            n_trials=data.get("n_trials"),
            objective=data.get("objective"),
            search_space=data.get("search_space"),
            storage=data.get("storage"),
            pruner=data.get("pruner"),
            study_name=data.get("study_name"),
        )

    @classmethod
    def from_yaml(cls, path: Union[str, Path], key: str) -> Optional["HyperparamConfig"]:
        """Load one pipeline's hyperparameter config from a YAML file.
        """
        import yaml  # type: ignore

        p = Path(path)
        if not p.exists():
            logger.warning("Hyperparams YAML not found: {}", p)
            return None
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if key not in data:
            logger.warning("Key '{}' not found in hyperparams file '{}'", key, p)
            return None
        return cls.from_dict(data[key])


    @staticmethod
    def _is_conditional(spec: Any) -> bool:
        """Return True if this spec defines a conditional parameter (has ``depends_on``)."""
        return isinstance(spec, dict) and "depends_on" in spec

    def _get_dependency_parents(self) -> set:
        """Return the set of parent param names referenced in conditional specs."""
        parents: set = set()
        for spec in self.search_space.values():
            if self._is_conditional(spec):
                dep = spec["depends_on"]
                if isinstance(dep, dict):
                    parents.add(dep.get("param", ""))
        return parents

    def _get_conditional_params(self) -> List[str]:
        """Return names of params that have ``depends_on``."""
        return [n for n, s in self.search_space.items() if self._is_conditional(s)]

    def _get_unconditional_params(self) -> List[str]:
        """Return names of params without ``depends_on``."""
        return [n for n, s in self.search_space.items() if not self._is_conditional(s)]

    def _validate_dependencies(self) -> None:
        """Validate that all dependency references are resolvable."""
        for name, spec in self.search_space.items():
            if not self._is_conditional(spec):
                continue
            dep = spec["depends_on"]
            if not isinstance(dep, dict):
                raise HyperparamConfigError(
                    f"Param '{name}': 'depends_on' must be a dict with 'param' and 'mapping'"
                )
            parent = dep.get("param")
            if not parent:
                raise HyperparamConfigError(f"Param '{name}': 'depends_on.param' is required")
            if parent not in self.search_space:
                raise HyperparamConfigError(
                    f"Param '{name}' depends on '{parent}' which is not in search_space"
                )
            if self._is_conditional(self.search_space[parent]):
                raise HyperparamConfigError(
                    f"Param '{name}' depends on '{parent}' which is itself conditional "
                    f"— only one level of nesting is supported"
                )
            mapping = dep.get("mapping")
            if not isinstance(mapping, dict):
                raise HyperparamConfigError(f"Param '{name}': 'depends_on.mapping' must be a dict")
            parent_values = self._values_for(parent)
            for pv in parent_values:
                if pv not in mapping:
                    raise HyperparamConfigError(
                        f"Param '{name}': missing mapping for parent '{parent}' = {pv!r}"
                    )


    @staticmethod
    def _is_range_spec(v: Any) -> bool:
        return isinstance(v, dict) and "min" in v and "max" in v and "depends_on" not in v

    def _values_for(self, name: str) -> list:
        """Return the discrete list of values for a parameter, expanding range specs.
        """
        spec = self.search_space.get(name)
        if spec is None:
            return []
        if self._is_conditional(spec):
            mapping = spec["depends_on"]["mapping"]
            seen: set = set()
            result = []
            for vals in mapping.values():
                for v in vals:
                    if v not in seen:
                        seen.add(v)
                        result.append(v)
            return result
        if self._is_range_spec(spec):
            step = spec.get("step", 1)
            if isinstance(step, float) or isinstance(spec.get("min"), float):
                return self._frange(spec["min"], spec["max"], step)
            return list(range(int(spec["min"]), int(spec["max"]) + 1, int(step)))
        return list(spec)

    def _allowed_values_for(self, name: str, parent_values: Dict[str, Any]) -> list:
        """Return the values allowed for a conditional param given resolved parent values.
        """
        spec = self.search_space.get(name)
        if not self._is_conditional(spec):
            return self._values_for(name)

        dep = spec["depends_on"]
        parent = dep["param"]
        pv = parent_values.get(parent)

        mapping = dep["mapping"]
        if pv in mapping:
            return list(mapping[pv])
        return list(mapping.get(None, []))

    @staticmethod
    def _frange(start: float, stop: float, step: float) -> list:
        n = int(math.ceil((stop - start) / step)) if step > 0 else 0
        stop_r = round(stop, 10)
        values = []
        for i in range(n + 1):
            v = round(start + i * step, 10)
            if v <= stop_r:
                values.append(v)
        return values

    def has_conditional_params(self) -> bool:
        """Return True if any parameter has a ``depends_on`` clause."""
        return any(self._is_conditional(s) for s in self.search_space.values())

    # ------------------------------------------------------------------
    # builders
    # ------------------------------------------------------------------
    def build_param_grid(self) -> Union[ParamGrid, List[ParamGrid]]:
        """Build an sklearn-style ``param_grid``.
        """
        if self.algorithm != "grid":
            logger.warning(
                "build_param_grid() called for algorithm='{}'. "
                "Use build_distributions() for non-grid algorithms.",
                self.algorithm,
            )

        if not self.has_conditional_params():
            return {name: self._values_for(name) for name in self.search_space}

        return self._build_conditional_grids()

    def _build_conditional_grids(self) -> List[ParamGrid]:
        """Build one sub-grid per parent-value combination.
        """
        unconditional = self._get_unconditional_params()
        conditional = self._get_conditional_params()
        parents = self._get_dependency_parents()

        base_grid: ParamGrid = {n: self._values_for(n) for n in unconditional}

        parent_grid: ParamGrid = {n: self._values_for(n) for n in parents}

        parent_keys = list(parent_grid.keys())
        parent_combos = (
            [
                dict(zip(parent_keys, combo))
                for combo in itertools.product(*(parent_grid[k] for k in parent_keys))
            ]
            if parent_keys
            else [{}]
        )

        grids: List[ParamGrid] = []
        for parent_vals in parent_combos:
            sub_grid = dict(base_grid)
            for pname, pval in parent_vals.items():
                sub_grid[pname] = [pval]
            for cname in conditional:
                allowed = self._allowed_values_for(cname, parent_vals)
                sub_grid[cname] = allowed
            grids.append(sub_grid)

        return grids

    def build_distributions(self) -> Distribution:
        """Build a dict suitable for sklearn's ``RandomizedSearchCV``.
        """
        if self.has_conditional_params():
            logger.warning(
                "build_distributions() called with conditional params (depends_on). "
                "RandomizedSearchCV does not support conditional spaces natively. "
                "Consider using build_param_grid() or Optuna instead."
            )

        dists: Distribution = {}
        needs_scipy = any(self._is_range_spec(s) for s in self.search_space.values())
        if needs_scipy:
            try:
                from scipy.stats import loguniform, uniform  # type: ignore
            except ImportError:
                raise HyperparamConfigError(
                    "Range-spec ('min'/'max') parameters require 'scipy'. "
                    "Install with: pip install scipy"
                )

        for name, spec in self.search_space.items():
            if self._is_range_spec(spec):
                if spec.get("log", False):
                    dists[name] = loguniform(spec["min"], spec["max"])
                else:
                    dists[name] = uniform(spec["min"], spec["max"] - spec["min"])
            else:
                dists[name] = self._values_for(name)
        return dists

    def build_optuna_space(self) -> Dict[str, dict]:
        """Build an Optuna-compatible space definition.
        """
        try:
            import optuna  # noqa: F401
        except ImportError:
            raise HyperparamConfigError(
                "Bayesian search requires 'optuna'. Install with: pip install optuna"
            )

        space: Dict[str, dict] = {}
        for name, spec in self.search_space.items():
            if self._is_conditional(spec):
                dep = spec["depends_on"]
                parent = dep["param"]
                mapping = dep["mapping"]
                all_choices = self._values_for(name)
                space[name] = {
                    "type": "conditional",
                    "args": {
                        "depends_on": parent,
                        "mapping": {str(k): list(v) for k, v in mapping.items()},
                        "choices": all_choices,
                    },
                }
            elif self._is_range_spec(spec):
                if spec.get("log", False):
                    space[name] = {
                        "type": "float",
                        "args": {"low": spec["min"], "high": spec["max"], "log": True},
                    }
                else:
                    space[name] = {
                        "type": "float",
                        "args": {"low": spec["min"], "high": spec["max"]},
                    }
            else:
                values = list(spec)
                if all(isinstance(v, bool) for v in values):
                    space[name] = {
                        "type": "categorical",
                        "args": {"choices": list(values)},
                    }
                elif all(isinstance(v, int) for v in values):
                    space[name] = {"type": "int", "args": {"low": min(values), "high": max(values)}}
                elif all(isinstance(v, float) for v in values):
                    space[name] = {
                        "type": "float",
                        "args": {"low": min(values), "high": max(values)},
                    }
                else:
                    space[name] = {
                        "type": "categorical",
                        "args": {"choices": list(values)},
                    }
        return space

    def suggest_params(self, trial: Any) -> Dict[str, Any]:
        """Sample a set of parameters from an Optuna trial.
        """
        params: Dict[str, Any] = {}

        if not self.has_conditional_params():
            # Fast path — no dependencies, any order is fine
            for name, spec in self.search_space.items():
                params[name] = self._suggest_one(trial, name, spec)
            return params

        parents = self._get_dependency_parents()
        conditional = self._get_conditional_params()

        for name in self._get_unconditional_params():
            if name not in parents:
                params[name] = self._suggest_one(trial, name, self.search_space[name])

        for name in parents:
            params[name] = self._suggest_one(trial, name, self.search_space[name])


        for name in conditional:
            allowed = self._allowed_values_for(name, params)
            params[name] = trial.suggest_categorical(name, allowed)

        return params

    def _suggest_one(self, trial: Any, name: str, spec: Any) -> Any:
        """Suggest a single parameter value from an Optuna trial."""
        if self._is_range_spec(spec):
            if spec.get("log", False):
                return trial.suggest_float(name, spec["min"], spec["max"], log=True)
            return trial.suggest_float(name, spec["min"], spec["max"])

        return trial.suggest_categorical(name, list(spec))


    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "cv_folds": self.cv_folds,
            "n_trials": self.n_trials,
            "objective": dict(self.objective),
            "search_space": dict(self.search_space),
        }


class SweepLimitError(ValueError):
    """Raised when a sweep spec expands beyond the maximum number of runs."""


def expand_sweep_grid(
    params: Dict[str, Any],
    max_runs: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Expand a flat config into a cartesian product of hyperparameter combos.
    """
    cleaned = dict(params)
    max_runs = int(cleaned.pop("max_runs", max_runs or 50))

    swept = {k: v for k, v in cleaned.items() if isinstance(v, list)}
    fixed = {k: v for k, v in cleaned.items() if not isinstance(v, list)}
    if not swept:
        return [dict(fixed)]

    total = 1
    for key, values in swept.items():
        if not values:
            raise SweepLimitError(f"Swept key '{key}' has an empty list")
        total *= len(values)
    if total > max_runs:
        raise SweepLimitError(
            f"Sweep expands to {total} runs, above the limit of {max_runs}. "
            f"Reduce the grid or set 'max_runs: {total}' explicitly."
        )

    keys = list(swept.keys())
    combos = []
    for values in itertools.product(*(swept[k] for k in keys)):
        combo = dict(fixed)
        combo.update(dict(zip(keys, values)))
        combos.append(combo)
    return combos


def load_hyperparams_config(
    source: Union[str, Path, Dict[str, Any]],
    pipeline_key: Optional[str] = None,
) -> Optional["HyperparamConfig"]:
    """Load a hyperparameter configuration from a YAML file or dict.
    """
    if isinstance(source, dict):
        data = source
    else:
        import yaml  # type: ignore

        p = Path(source)
        if not p.exists():
            logger.warning("Hyperparams file not found: {}", p)
            return None
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    if not data:
        return None

    if pipeline_key is None:
        if len(data) == 1:
            pipeline_key = next(iter(data))
        else:
            logger.error(
                "pipeline_key is required when the hyperparams file has {} top-level keys",
                len(data),
            )
            return None

    entry = data.get(pipeline_key)
    if entry is None:
        logger.warning("Key '{}' not found in hyperparams config", pipeline_key)
        return None

    return HyperparamConfig.from_dict(entry)
