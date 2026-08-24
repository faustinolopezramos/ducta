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
import re
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from loguru import logger  # type: ignore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Bucket used for reports/history/baselines that don't belong to any real
#: pipeline execution (e.g. QualityService.run_checks against a standalone
#: file). Keeps every StorageBackend path shaped the same
#: ({root}/{pipeline_name}/{dataset_name}/...) with no special-cased branch.
DEFAULT_PIPELINE_NAME = "_adhoc"


@contextmanager
def _exclusive_lock(f: Any) -> Generator[None, None, None]:
    try:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except ImportError:
        try:
            import msvcrt
        except ImportError:
            # Neither fcntl (POSIX) nor msvcrt (Windows) is available;
            # concurrent writes may corrupt files.
            yield
            return

        # msvcrt.locking() locks a byte range starting at the *current* file
        # position, so pin it to a fixed 1-byte region at offset 0 — the
        # LK_LOCK and matching LK_UNLCK calls must agree on both the start
        # offset and length, and callers seek around inside `f` while the
        # lock is held.
        original_pos = f.tell()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            f.seek(original_pos)
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def _write_json_atomic(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _read_json_safe(path: Path) -> Optional[Any]:
    if not path.exists():
        logger.debug(f"JSON file not found: {path}")
        return None
    content = path.read_text(encoding="utf-8")
    return json.loads(content) if content else None


_SAFE_RUN_ID_RE = re.compile(r"^[\w\-]+$")


def _sanitize_run_id(run_id: str) -> str:
    safe = Path(run_id).name
    if not safe or safe in (".", "..") or not _SAFE_RUN_ID_RE.match(safe):
        raise ValueError(
            f"Invalid run_id {run_id!r}: must contain only word characters and hyphens"
        )
    return safe


def _sanitize_dataset_name(dataset_name: str) -> str:
    safe = Path(dataset_name).name
    if not safe or safe in (".", ".."):
        raise ValueError(f"Invalid dataset_name: {dataset_name!r}")
    return safe


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class StorageBackend(ABC):
    """Persists sanity/data-quality reports, baselines, and history.

    Every dataset is scoped under ``pipeline_name`` (default
    :data:`DEFAULT_PIPELINE_NAME`) so that two different pipelines with a node
    of the same name never share/overwrite each other's reports, baseline, or
    history — mirrors the ``{pipeline_name}/{node_name}/...`` scoping already
    used for streaming checkpoints (``ducta.stream.checkpoints``).
    """

    @abstractmethod
    def save_report(
        self,
        report: Dict[str, Any],
        run_id: str,
        dataset_name: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None: ...

    @abstractmethod
    def load_report(
        self, run_id: str, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def save_baseline(
        self,
        baseline: Dict[str, Any],
        dataset_name: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None: ...

    @abstractmethod
    def load_baseline(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def save_history(
        self,
        history: List[Dict[str, Any]],
        dataset_name: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None: ...

    @abstractmethod
    def load_history(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> Optional[List[Dict[str, Any]]]: ...

    @abstractmethod
    def append_history(
        self,
        dataset_name: str,
        metric_entry: Dict[str, Any],
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None: ...

    @abstractmethod
    def save_gate_result(
        self,
        gate_result: Dict[str, Any],
        run_id: str,
        dataset_name: str,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None: ...

    @abstractmethod
    def load_gate_result(
        self, run_id: str, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> Optional[Dict[str, Any]]: ...

    def load_score_trend(
        self, dataset_name: str, last_n: int = 20, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> List[float]:
        history = self.load_history(dataset_name, pipeline_name) or []
        scores = [float(e["score"]) for e in history if isinstance(e.get("score"), (int, float))]
        return scores[-last_n:]

    # Concrete with a safe default (empty/False) rather than abstract: every
    # backend in this codebase now implements these directly, but a default
    # keeps a hypothetical third backend from crashing with AttributeError
    # instead of just reporting "nothing found" — matching load_score_trend's
    # own precedent above.
    def list_reports(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> List[str]:
        return []

    def list_reports_by_recency(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> List[str]:
        """Like list_reports(), but ordered most-recent-first.

        run_id is an opaque identifier (a random UUID fragment, not a
        timestamp), so callers that want "the latest report" must not sort
        list_reports()'s output lexicographically. Concrete backends that
        persist to a local filesystem override this with a real
        mtime-based sort; this default falls back to list_reports()'s own
        (unspecified) order for backends that can't determine recency.
        """
        return self.list_reports(dataset_name, pipeline_name)

    def delete_report(
        self, run_id: str, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> bool:
        return False

    def list_datasets(self, pipeline_name: Optional[str] = None) -> List[str]:
        """List datasets with at least one persisted report.

        With *pipeline_name* given, returns plain dataset names within that
        pipeline. With *pipeline_name* omitted, aggregates across every
        pipeline bucket and returns ``"{pipeline_name}/{dataset_name}"``
        qualified names, so callers can't confuse same-named datasets that
        belong to different pipelines.
        """
        return []


# ---------------------------------------------------------------------------
# File-based implementation
# ---------------------------------------------------------------------------


class FileStorageBackend(StorageBackend):
    def __init__(self, workspace_path: str) -> None:
        self.workspace_path = Path(workspace_path)
        self.base_dir = self.workspace_path / ".quality"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _dataset_path(self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME) -> Path:
        safe_pipeline = _sanitize_dataset_name(pipeline_name)
        safe_name = _sanitize_dataset_name(dataset_name)
        p = self.base_dir / safe_pipeline / safe_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _reports_dir(self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME) -> Path:
        p = self._dataset_path(dataset_name, pipeline_name) / "reports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_report(self, report, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        _write_json_atomic(
            self._reports_dir(dataset_name, pipeline_name) / f"{_sanitize_run_id(run_id)}.json",
            report,
        )

    def load_report(self, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        return _read_json_safe(
            self._reports_dir(dataset_name, pipeline_name) / f"{_sanitize_run_id(run_id)}.json"
        )

    def save_baseline(self, baseline, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        _write_json_atomic(
            self._dataset_path(dataset_name, pipeline_name) / "baseline.json", baseline
        )

    def load_baseline(self, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        return _read_json_safe(self._dataset_path(dataset_name, pipeline_name) / "baseline.json")

    def save_history(self, history, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        _write_json_atomic(
            self._dataset_path(dataset_name, pipeline_name) / "history.json", history
        )

    def load_history(self, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        return _read_json_safe(self._dataset_path(dataset_name, pipeline_name) / "history.json")

    def append_history(self, dataset_name, metric_entry, pipeline_name=DEFAULT_PIPELINE_NAME):
        p = self._dataset_path(dataset_name, pipeline_name) / "history.json"
        try:
            if not p.exists():
                p.write_text("[]", encoding="utf-8")
            with open(p, "r+") as f:
                with _exclusive_lock(f):
                    content = f.read()
                    history = json.loads(content) if content.strip() else []
                    history.append(metric_entry)
                    f.seek(0)
                    f.truncate()
                    json.dump(history, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to append to history: {e}")

    def save_gate_result(
        self, gate_result, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME
    ):
        d = self._dataset_path(dataset_name, pipeline_name) / "gate_results"
        d.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(d / f"{_sanitize_run_id(run_id)}.json", gate_result)

    def load_gate_result(self, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        p = (
            self._dataset_path(dataset_name, pipeline_name)
            / "gate_results"
            / f"{_sanitize_run_id(run_id)}.json"
        )
        return _read_json_safe(p) if p.exists() else None

    def list_reports(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> List[str]:
        try:
            return [f.stem for f in self._reports_dir(dataset_name, pipeline_name).glob("*.json")]
        except Exception:
            return []

    def list_reports_by_recency(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> List[str]:
        try:
            files = sorted(
                self._reports_dir(dataset_name, pipeline_name).glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return [f.stem for f in files]
        except Exception:
            return []

    def delete_report(
        self, run_id: str, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> bool:
        """Delete a stored report. Returns False if it didn't exist."""
        path = self._reports_dir(dataset_name, pipeline_name) / f"{_sanitize_run_id(run_id)}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    def _list_datasets_in(self, pipeline_dir: Path) -> List[str]:
        return sorted(
            p.name
            for p in pipeline_dir.iterdir()
            if p.is_dir() and (p / "reports").is_dir() and any((p / "reports").glob("*.json"))
        )

    def list_datasets(self, pipeline_name: Optional[str] = None) -> List[str]:
        try:
            if pipeline_name is not None:
                pipeline_dir = self.base_dir / _sanitize_dataset_name(pipeline_name)
                if not pipeline_dir.is_dir():
                    return []
                return self._list_datasets_in(pipeline_dir)

            qualified: List[str] = []
            for pipeline_dir in self.base_dir.iterdir():
                if not pipeline_dir.is_dir():
                    continue
                for dataset_name in self._list_datasets_in(pipeline_dir):
                    qualified.append(f"{pipeline_dir.name}/{dataset_name}")
            return sorted(qualified)
        except Exception:
            return []

    def cleanup_old_reports(
        self,
        dataset_name: str,
        keep_latest: int = 100,
        pipeline_name: str = DEFAULT_PIPELINE_NAME,
    ) -> None:
        try:
            files = sorted(
                self._reports_dir(dataset_name, pipeline_name).glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for f in files[keep_latest:]:
                f.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Context-aware implementation (Spark/Pandas)
# ---------------------------------------------------------------------------


class ContextAwareStorageBackend(StorageBackend):
    def __init__(
        self,
        context: Any,
        format: str = "json",
        base_path: Optional[str] = None,
        writer_options: Optional[Dict[str, Any]] = None,
    ) -> None:
        from ducta.gate.base import BaseIO
        from ducta.gate.output import is_cloud_path

        self.context = context
        self.format = format.lower()
        self.writer_options = writer_options or {}
        self._base_io = BaseIO(context)
        self._is_cloud_path = is_cloud_path

        if base_path:
            self._root = Path(base_path)
        else:
            output_path = self._base_io._ctx_get("output_path") or "."
            self._root = Path(str(output_path)) / ".quality"

        if not self._is_cloud_path(str(self._root)):
            self._base_io._prepare_local_directory(str(self._root))

    def _dataset_dir(self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME) -> Path:
        safe_pipeline = _sanitize_dataset_name(pipeline_name)
        safe = _sanitize_dataset_name(dataset_name)
        p = self._root / safe_pipeline / safe
        if not self._is_cloud_path(str(self._root)):
            self._base_io._prepare_local_directory(str(p))
        return p

    def _reports_dir(self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME) -> Path:
        p = self._dataset_dir(dataset_name, pipeline_name) / "reports"
        if not self._is_cloud_path(str(self._root)):
            self._base_io._prepare_local_directory(str(p))
        return p

    def _to_dataframe(self, data: Any):
        try:
            return self.context.spark.createDataFrame(data)
        except (AttributeError, Exception):
            import pandas as pd  # type: ignore

            return pd.DataFrame(data)

    def _from_dataframe(self, df: Any):
        if hasattr(df, "toPandas"):
            return df.toPandas().to_dict(orient="records")
        return df.to_dict(orient="records")

    def _write_with_io(self, data_list: list, path: Path):
        from ducta.gate.factories import WriterFactory

        df = self._to_dataframe(data_list)
        writer = WriterFactory(self.context).get_handler(self.format)
        write_config = {"mode": "overwrite", "format": self.format}
        write_config.update(self.writer_options)
        writer.write(df, str(path), write_config)

    def _read_with_io(self, path: Path) -> Optional[list]:
        from ducta.gate.factories import ReaderFactory

        try:
            reader = ReaderFactory(self.context).get_handler(self.format)
            df = reader.read(str(path), {"format": self.format})
            return self._from_dataframe(df)
        except Exception as e:
            logger.debug(f"Failed to read {self.format} from {path}: {e}")
            return None

    def save_report(self, report, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            _write_json_atomic(
                self._reports_dir(dataset_name, pipeline_name) / f"{_sanitize_run_id(run_id)}.json",
                report,
            )
        else:
            records = [report]
            for r in records:
                r["results"] = json.dumps(r.get("results", []), default=str)
            self._write_with_io(
                records,
                self._reports_dir(dataset_name, pipeline_name)
                / f"{_sanitize_run_id(run_id)}.{self.format}",
            )

    def load_report(self, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            return _read_json_safe(
                self._reports_dir(dataset_name, pipeline_name) / f"{_sanitize_run_id(run_id)}.json"
            )
        else:
            records = self._read_with_io(
                self._reports_dir(dataset_name, pipeline_name)
                / f"{_sanitize_run_id(run_id)}.{self.format}"
            )
            if records and len(records) > 0:
                report = records[0]
                if isinstance(report.get("results"), str):
                    report["results"] = json.loads(report["results"])
                return report
            return None

    def save_baseline(self, baseline, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            _write_json_atomic(
                self._dataset_dir(dataset_name, pipeline_name) / "baseline.json", baseline
            )
        else:
            records = [
                {"column": k, "metrics": json.dumps(v, default=str)} for k, v in baseline.items()
            ]
            self._write_with_io(
                records, self._dataset_dir(dataset_name, pipeline_name) / f"baseline.{self.format}"
            )

    def load_baseline(self, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            return _read_json_safe(self._dataset_dir(dataset_name, pipeline_name) / "baseline.json")
        else:
            records = self._read_with_io(
                self._dataset_dir(dataset_name, pipeline_name) / f"baseline.{self.format}"
            )
            if records is not None:
                return {r["column"]: json.loads(r["metrics"]) for r in records}
            return None

    def save_history(self, history, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            _write_json_atomic(
                self._dataset_dir(dataset_name, pipeline_name) / "history.json", history
            )
        else:
            self._write_with_io(
                history, self._dataset_dir(dataset_name, pipeline_name) / f"history.{self.format}"
            )

    def load_history(self, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            return _read_json_safe(self._dataset_dir(dataset_name, pipeline_name) / "history.json")
        else:
            return self._read_with_io(
                self._dataset_dir(dataset_name, pipeline_name) / f"history.{self.format}"
            )

    def append_history(self, dataset_name, metric_entry, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            p = self._dataset_dir(dataset_name, pipeline_name) / "history.json"
            try:
                if not p.exists():
                    p.write_text("[]", encoding="utf-8")
                with open(p, "r+") as f:
                    with _exclusive_lock(f):
                        content = f.read()
                        history = json.loads(content) if content.strip() else []
                        history.append(metric_entry)
                        f.seek(0)
                        f.truncate()
                        json.dump(history, f, indent=2, default=str)
            except Exception as e:
                logger.error(f"Failed to append to history: {e}")
        else:
            # Non-JSON formats have no cheap incremental append, so this does a
            # full load-modify-save; without a lock around that, two concurrent
            # appends can each read the same old history and the later save wins,
            # silently dropping the other's entry. Locks on a sentinel file since
            # the writer/reader abstractions don't expose a raw file handle to
            # flock directly (unlike the json branch above).
            lock_path = self._dataset_dir(dataset_name, pipeline_name) / "history.lock"
            try:
                with open(lock_path, "a+") as lockf:
                    with _exclusive_lock(lockf):
                        history = self.load_history(dataset_name, pipeline_name) or []
                        history.append(metric_entry)
                        self.save_history(history, dataset_name, pipeline_name)
            except Exception as e:
                logger.error(f"Failed to append to history: {e}")

    def save_gate_result(
        self, gate_result, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME
    ):
        d = self._dataset_dir(dataset_name, pipeline_name) / "gate_results"
        if not self._is_cloud_path(str(self._root)):
            self._base_io._prepare_local_directory(str(d))
        if self.format == "json":
            _write_json_atomic(d / f"{_sanitize_run_id(run_id)}.json", gate_result)
        else:
            gate_result["triggered_rules"] = json.dumps(
                gate_result.get("triggered_rules", []), default=str
            )
            self._write_with_io([gate_result], d / f"{_sanitize_run_id(run_id)}.{self.format}")

    def load_gate_result(self, run_id, dataset_name, pipeline_name=DEFAULT_PIPELINE_NAME):
        if self.format == "json":
            return _read_json_safe(
                self._dataset_dir(dataset_name, pipeline_name)
                / "gate_results"
                / f"{_sanitize_run_id(run_id)}.json"
            )
        else:
            d = self._dataset_dir(dataset_name, pipeline_name) / "gate_results"
            records = self._read_with_io(d / f"{_sanitize_run_id(run_id)}.{self.format}")
            if records and len(records) > 0:
                result = records[0]
                if isinstance(result.get("triggered_rules"), str):
                    result["triggered_rules"] = json.loads(result["triggered_rules"])
                return result
            return None

    def list_reports(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> List[str]:
        """Return the run_ids with a persisted report for *dataset_name*."""
        if self._is_cloud_path(str(self._root)):
            logger.warning(
                "list_reports() is not supported for cloud storage paths ({}); "
                "returning empty list",
                self._root,
            )
            return []
        try:
            reports_dir = self._reports_dir(dataset_name, pipeline_name)
            return sorted(f.stem for f in reports_dir.glob(f"*.{self.format}"))
        except Exception as e:
            logger.debug(f"Failed to list reports for '{dataset_name}': {e}")
            return []

    def list_reports_by_recency(
        self, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> List[str]:
        """Like list_reports(), but ordered most-recent-first by file mtime.

        Not supported for cloud storage paths — mtime isn't reliably
        meaningful there, same limitation as list_reports() itself — so
        this falls back to list_reports()'s own order in that case.
        """
        if self._is_cloud_path(str(self._root)):
            return self.list_reports(dataset_name, pipeline_name)
        try:
            reports_dir = self._reports_dir(dataset_name, pipeline_name)
            files = sorted(
                reports_dir.glob(f"*.{self.format}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return [f.stem for f in files]
        except Exception as e:
            logger.debug(f"Failed to list reports by recency for '{dataset_name}': {e}")
            return []

    def delete_report(
        self, run_id: str, dataset_name: str, pipeline_name: str = DEFAULT_PIPELINE_NAME
    ) -> bool:
        """Delete a stored report. Returns False if it didn't exist."""
        if self._is_cloud_path(str(self._root)):
            logger.warning(
                "delete_report() is not supported for cloud storage paths ({})", self._root
            )
            return False
        path = (
            self._reports_dir(dataset_name, pipeline_name)
            / f"{_sanitize_run_id(run_id)}.{self.format}"
        )
        if not path.exists():
            return False
        path.unlink()
        return True

    def _list_datasets_in(self, pipeline_dir: Path) -> List[str]:
        return sorted(
            p.name
            for p in pipeline_dir.iterdir()
            if p.is_dir()
            and (p / "reports").is_dir()
            and any((p / "reports").glob(f"*.{self.format}"))
        )

    def list_datasets(self, pipeline_name: Optional[str] = None) -> List[str]:
        """Return dataset names with at least one persisted report."""
        if self._is_cloud_path(str(self._root)):
            logger.warning(
                "list_datasets() is not supported for cloud storage paths ({}); "
                "returning empty list",
                self._root,
            )
            return []
        try:
            if pipeline_name is not None:
                pipeline_dir = self._root / _sanitize_dataset_name(pipeline_name)
                if not pipeline_dir.is_dir():
                    return []
                return self._list_datasets_in(pipeline_dir)

            qualified: List[str] = []
            for pipeline_dir in self._root.iterdir():
                if not pipeline_dir.is_dir():
                    continue
                for dataset_name in self._list_datasets_in(pipeline_dir):
                    qualified.append(f"{pipeline_dir.name}/{dataset_name}")
            return sorted(qualified)
        except Exception as e:
            logger.debug(f"Failed to list datasets: {e}")
            return []
