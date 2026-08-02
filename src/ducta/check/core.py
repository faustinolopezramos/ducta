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

import importlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from loguru import logger  # type: ignore

# --- REGISTRY ---
QUALITY_CHECKS_REGISTRY: Dict[str, type] = {}


def register_check(name: str) -> Callable:
    """Decorator to auto-register a quality check class under *name*."""

    def wrapper(cls: type) -> type:
        existing = QUALITY_CHECKS_REGISTRY.get(name)
        if existing is not None and existing is not cls:
            logger.warning(
                "Quality check '{}' is already registered to {}.{} — {}.{} is replacing it",
                name,
                existing.__module__,
                existing.__qualname__,
                cls.__module__,
                cls.__qualname__,
            )
        QUALITY_CHECKS_REGISTRY[name] = cls
        return cls

    return wrapper


def load_quality_extensions(module_paths: List[str]) -> List[str]:
    """Import user-defined modules that register custom quality checks."""
    newly_registered: List[str] = []

    for module_path in module_paths:
        before = set(QUALITY_CHECKS_REGISTRY.keys())
        try:
            importlib.import_module(module_path)
            added = set(QUALITY_CHECKS_REGISTRY.keys()) - before
            for check_name in added:
                logger.info(
                    "Loaded custom quality check '{}' from '{}'",
                    check_name,
                    module_path,
                )
            newly_registered.extend(sorted(added))
        except ImportError as exc:
            raise QualityConfigError(
                f"Cannot import quality extension module '{module_path}': {exc}.  "
                "Ensure the module path is correct and the Python path is configured."
            ) from exc
        except Exception as exc:
            raise QualityConfigError(
                f"Error loading quality extension module '{module_path}': {exc}"
            ) from exc

    return newly_registered


class QualityError(Exception):
    pass


class QualityEngineError(QualityError):
    def __init__(self, message: str, engine_type: Optional[str] = None) -> None:
        self.message = message
        self.engine_type = engine_type
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": "QualityEngineError",
            "message": self.message,
            "engine_type": self.engine_type,
        }


class QualityConfigError(QualityError):
    pass


class QualityCheckError(QualityError):
    def __init__(
        self,
        check_name: str,
        message: str,
        node_name: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> None:
        self.check_name = check_name
        self.message = message
        self.node_name = node_name
        self.severity = severity
        super().__init__(
            f"Check '{check_name}' failed: {message}"
            + (f" (node: {node_name})" if node_name else "")
        )


class QualityChecksFailed(QualityError):
    def __init__(self, results: list, dataset_name: str, run_id: Optional[str] = None) -> None:
        self.results = results
        self.dataset_name = dataset_name
        self.run_id = run_id
        super().__init__(
            f"Quality checks failed for '{dataset_name}': {self.errors_count} errors, {self.warnings_count} warnings"
            + (f" (run_id: {run_id})" if run_id else "")
        )

    @property
    def errors_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == CheckSeverity.ERROR)

    @property
    def warnings_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == CheckSeverity.WARNING)

    def to_dict(self) -> dict:
        return {
            "error": "QualityChecksFailed",
            "dataset_name": self.dataset_name,
            "run_id": self.run_id,
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count,
            "results": [r.to_dict() if hasattr(r, "to_dict") else r for r in self.results],
        }


class QualityGateBlocked(QualityError):
    def __init__(self, gate_result: Any, dataset_name: str, run_id: Optional[str] = None) -> None:
        self.gate_result = gate_result
        self.dataset_name = dataset_name
        self.run_id = run_id
        self.skip_retry: bool = True
        triggered = getattr(gate_result, "triggered_rules", [])
        super().__init__(
            f"Quality gate '{getattr(gate_result, 'gate_name', 'gate')}' blocked dataset '{dataset_name}': "
            + ("; ".join(triggered) if triggered else "no detail")
            + (f" (run_id: {run_id})" if run_id else "")
        )

    def to_dict(self) -> dict:
        return {
            "error": "QualityGateBlocked",
            "dataset_name": self.dataset_name,
            "run_id": self.run_id,
            "gate_result": (
                self.gate_result.to_dict()
                if hasattr(self.gate_result, "to_dict")
                else self.gate_result
            ),
        }


class DFAdapter:
    def __init__(self, df: Any) -> None:
        self.df = df
        self.engine = self._detect_engine()

    def _detect_engine(self) -> str:
        mod = type(self.df).__module__
        if "pyspark" in mod:
            return "spark"
        if "pandas" in mod:
            return "pandas"
        if hasattr(self.df, "rdd"):
            return "spark"
        if hasattr(self.df, "iloc"):
            return "pandas"
        raise QualityEngineError(
            f"Unsupported DataFrame type: {type(self.df)}", engine_type="unknown"
        )

    def _spark(self):
        from pyspark.sql import functions as f  # type: ignore

        return f

    def count(self) -> int:
        return self.df.count() if self.engine == "spark" else len(self.df)

    def get_columns(self) -> List[str]:
        return self.df.columns if self.engine == "spark" else list(self.df.columns)

    def get_schema(self) -> Dict[str, str]:
        """Return {column_name: type_as_string}, comparable across pandas/Spark."""
        if self.engine == "spark":
            return {field.name: str(field.dataType) for field in self.df.schema.fields}
        return {col: str(dtype) for col, dtype in self.df.dtypes.items()}

    def null_count(self, column: str) -> int:
        if self.engine == "spark":
            F = self._spark()

            dtype = dict(self.df.dtypes).get(column)
            is_numeric = dtype in ("double", "float")

            if is_numeric:
                return self.df.filter(F.isnull(column) | F.isnan(column)).count()
            return self.df.filter(F.isnull(column)).count()
        return int(self.df[column].isna().sum())

    def min_max(self, column: str) -> Tuple[Optional[float], Optional[float]]:
        if self.engine == "spark":
            F = self._spark()
            r = self.df.select(F.min(column), F.max(column)).collect()[0]
            return r[0], r[1]
        import pandas as pd

        min_val = self.df[column].min()
        max_val = self.df[column].max()
        if pd.isna(min_val):
            min_val = None
        if pd.isna(max_val):
            max_val = None
        if min_val is None or max_val is None:
            return min_val, max_val
        try:
            return float(min_val), float(max_val)
        except (ValueError, TypeError):
            # If column is not numeric (e.g., Timestamp, string), return as-is for comparison
            return min_val, max_val

    def percentile(self, column: str, percentile: float) -> Optional[float]:
        if self.engine == "spark":
            F = self._spark()
            r = self.df.select(F.percentile_approx(column, percentile / 100.0)).collect()[0][0]
            return float(r) if r is not None else None
        return float(self.df[column].quantile(percentile / 100.0))

    def mean_std(self, column: str) -> Tuple[Optional[float], Optional[float]]:
        if self.engine == "spark":
            F = self._spark()
            r = self.df.select(F.avg(column), F.stddev(column)).collect()[0]
            return r[0], r[1]
        return float(self.df[column].mean()), float(self.df[column].std())

    def distinct_values(self, column: str, limit: Optional[int] = 1000) -> List[Any]:
        if self.engine == "spark":
            q = self.df.select(column).distinct()
            vals = q.limit(limit).collect() if limit is not None else q.collect()
            return [r[0] for r in vals]
        vals = self.df[column].unique()
        return vals[:limit].tolist() if limit is not None else vals.tolist()

    def value_counts(self, column: str, topk: int = 100) -> dict:
        if self.engine == "spark":
            F = self._spark()
            rows = (
                self.df.groupBy(column)
                .agg(F.count("*").alias("cnt"))
                .orderBy(F.col("cnt").desc())
                .limit(topk)
                .collect()
            )
            return {r[column]: r["cnt"] for r in rows}
        return self.df[column].value_counts().head(topk).to_dict()

    def filter_antijoin(self, column: str, reference_values: List[Any]) -> int:
        if self.engine == "spark":
            return self.df.filter(~self._spark().col(column).isin(reference_values)).count()
        return len(self.df[~self.df[column].isin(reference_values)])

    def anti_join(
        self, column: str, other: "DFAdapter", other_column: str, allow_null: bool = False
    ) -> int:
        """Perform an anti-join and return the count of rows not found in *other*."""
        source_df = self.df
        if allow_null:
            if self.engine == "spark":
                source_df = source_df.filter(source_df[column].isNotNull())
            else:
                source_df = source_df[source_df[column].notna()]

        if self.engine == "spark" and other.engine == "spark":
            return source_df.join(
                other.df, source_df[column] == other.df[other_column], how="left_anti"
            ).count()
        # Fallback for Pandas or mixed engines
        ref_values = other.distinct_values(other_column, limit=None)
        if self.engine == "spark":
            return source_df.filter(~self._spark().col(column).isin(ref_values)).count()
        return len(source_df[~source_df[column].isin(ref_values)])

    def sample(self, max_rows: int = 10000) -> Any:
        """Return a sample of the data as a Pandas DataFrame."""
        if self.engine == "spark":
            total = self.count()
            if total <= max_rows:
                return self.df.toPandas()
            fraction = max_rows / total
            return self.df.sample(withReplacement=False, fraction=fraction, seed=42).toPandas()

        if len(self.df) <= max_rows:
            return self.df
        return self.df.sample(n=max_rows, random_state=42)

    def filter_where(self, sql_condition: str) -> int:
        if self.engine == "spark":
            name = f"_quality_{uuid.uuid4().hex[:8]}"
            self.df.createOrReplaceTempView(name)
            try:
                return self.df.sparkSession.sql(
                    f"SELECT COUNT(*) FROM {name} WHERE {sql_condition}"
                ).collect()[0][0]
            finally:
                self.df.sparkSession.catalog.dropTempView(name)
        try:
            return len(self.df.query(sql_condition))
        except Exception as e:
            raise QualityEngineError(f"Pandas query failed: {e}", engine_type=self.engine)

    def to_pandas(self) -> Any:
        return self.df if self.engine == "pandas" else self.df.toPandas()


class CheckSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"

    @classmethod
    def from_str(cls, value: str) -> "CheckSeverity":
        if isinstance(value, cls):
            return value
        try:
            return cls[value.upper()]
        except KeyError:
            raise ValueError(
                f"Invalid severity: {value!r}. Must be one of {[e.value for e in cls]}"
            )

    def is_error(self) -> bool:
        return self == CheckSeverity.ERROR

    def is_warning(self) -> bool:
        return self == CheckSeverity.WARNING


@dataclass
class CheckResult:
    check_name: str
    passed: bool
    severity: CheckSeverity = CheckSeverity.ERROR
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if isinstance(self.severity, str):
            self.severity = CheckSeverity.from_str(self.severity)

    @property
    def is_error(self) -> bool:
        return not self.passed and self.severity == CheckSeverity.ERROR

    @property
    def is_warning(self) -> bool:
        return not self.passed and self.severity == CheckSeverity.WARNING

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "executed_at": self.executed_at,
        }


@dataclass
class QualityReport:
    dataset_name: str
    passed: bool
    results: List[CheckResult] = field(default_factory=list)
    run_id: Optional[str] = None
    workspace_path: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    elapsed_seconds: float = 0.0
    score: float = 1.0
    # Persistence failures (report/baseline/history) used to only log a
    # warning — invisible to whatever's reading the execution response. Not a
    # check failure (the data quality result itself is still valid), but a
    # real operational problem (e.g. a full disk) that was easy to miss.
    persistence_warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized = []
        for r in self.results:
            if isinstance(r, CheckResult):
                normalized.append(r)
            elif isinstance(r, dict):
                try:
                    normalized.append(
                        CheckResult(
                            **{
                                k: v
                                for k, v in r.items()
                                if k
                                in {
                                    "check_name",
                                    "passed",
                                    "severity",
                                    "message",
                                    "details",
                                    "executed_at",
                                }
                            }
                        )
                    )
                except TypeError as e:
                    logger.warning(f"Failed to deserialize CheckResult: {e}")
                    continue
            else:
                raise TypeError(f"Invalid result type: {type(r)}")
        self.results = normalized

    @property
    def errors_count(self) -> int:
        return sum(1 for r in self.results if r.is_error)

    @property
    def warnings_count(self) -> int:
        return sum(1 for r in self.results if r.is_warning)

    @property
    def checks_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "passed": self.passed,
            "score": self.score,
            "run_id": self.run_id,
            "workspace_path": self.workspace_path,
            "created_at": self.created_at,
            "elapsed_seconds": self.elapsed_seconds,
            "results": [r.to_dict() for r in self.results],
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count,
            "checks_count": self.checks_count,
            "persistence_warnings": self.persistence_warnings,
        }


class BaseQualityCheck(ABC):
    def __init__(self, name: str, severity: CheckSeverity = CheckSeverity.ERROR) -> None:
        self.name = name
        self.severity = severity

    @abstractmethod
    def run(
        self, df: Any, config: Any, adapter: Any, context_datasets: Optional[Dict[str, Any]] = None
    ) -> CheckResult: ...

    def _create_result(
        self,
        passed: bool,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        severity: Optional[CheckSeverity] = None,
    ) -> CheckResult:
        return CheckResult(
            check_name=self.name,
            passed=passed,
            severity=severity or self.severity,
            message=message,
            details=details or {},
        )

    def _get_context_adapter(
        self, dataset_name: str, context_datasets: Optional[Dict[str, Any]]
    ) -> Optional[Any]:
        if not context_datasets or dataset_name not in context_datasets:
            return None
        return DFAdapter(context_datasets[dataset_name])
