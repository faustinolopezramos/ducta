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

import threading
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Optional

from loguru import logger  # type: ignore

_STREAMING_PREVIEW_SORT_COLS = ["event_time", "_ingested_at", "timestamp", "time", "created_at"]


class StreamingPreviewCache:
    """Thread-safe TTL cache for expensive streaming-data preview reads.

    Keyed by an arbitrary string (typically ``f"{user_id}:{execution_id}"``),
    with stale entries (older than 60s) pruned on access.
    """

    def __init__(self, ttl_seconds: float = 10.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.RLock()

    def get_or_compute(self, cache_key: str, compute: Callable[[], dict]) -> dict:
        now = time.time()
        with self._lock:
            for stale_key in [k for k, (ts, _) in self._cache.items() if now - ts > 60]:
                self._cache.pop(stale_key, None)

            cached = self._cache.get(cache_key)
            if cached and (now - cached[0]) < self._ttl_seconds:
                return cached[1]

        results = compute()

        with self._lock:
            self._cache[cache_key] = (now, results)

        return results


def json_safe(value: Any) -> Any:
    """Recursively coerce Spark/Delta row values into JSON-serializable types."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    # numpy scalars (and similar) expose .item(); fall back to str otherwise.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return json_safe(item())
        except Exception:
            pass
    return str(value)


def read_delta_parquet_preview(path: str, max_rows: int = 20) -> list:
    """Read recent rows from a Delta directory using pandas/pyarrow (no Spark needed)."""
    import os

    if not os.path.isdir(path):
        return []

    parquet_files: list[tuple[float, str]] = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ("_delta_log", ".sparkStaging")]
        for f in files:
            if f.endswith(".parquet") and not f.startswith("."):
                full = os.path.join(root, f)
                parquet_files.append((os.path.getmtime(full), full))

    if not parquet_files:
        return []

    parquet_files.sort(reverse=True)  # most-recent first

    try:
        import pandas as pd

        dfs = []
        total = 0
        for _mtime, pf in parquet_files[:10]:
            try:
                df = pd.read_parquet(pf)
                if len(df):
                    dfs.append(df)
                    total += len(df)
                    if total >= max_rows * 2:
                        break
            except Exception:
                continue

        if not dfs:
            return []

        combined = pd.concat(dfs, ignore_index=True)
        for col in _STREAMING_PREVIEW_SORT_COLS:
            if col in combined.columns:
                try:
                    combined = combined.sort_values(col, ascending=False)
                except Exception:
                    pass
                break

        return [json_safe(row) for row in combined.head(max_rows).to_dict(orient="records")]
    except Exception as exc:
        logger.debug("Could not read delta preview at {}: {}", path, exc)
        return []


def read_streaming_data_external(source_path: str, execution: Any) -> dict:
    """Read streaming output for CLI-started executions without an active engine.

    Loads nodes config via TOML/YAML (no Spark) and reads Parquet files from the
    Delta output directories using pandas.
    """
    import os
    from pathlib import Path

    pipeline_name = getattr(execution, "pipeline_name", None)
    env = getattr(execution, "env", "base") or "base"

    if not pipeline_name or not source_path:
        return {}

    try:
        from ducta.api.execution.runner import resolve_project_source
        from ducta.console.config import AppConfigManager
        from ducta.setting.loaders import ConfigLoaderFactory

        project_dir = resolve_project_source(Path(source_path), pipeline_name)
        env_file: Optional[Path] = None
        for name in ("environment.toml", "environment.yml", "environment.yaml"):
            candidate = project_dir / name
            if candidate.is_file():
                env_file = candidate
                break

        if env_file is None:
            return {}

        app_config = AppConfigManager(str(env_file))
        env_cfg = app_config.get_env_config(env)
        loader = ConfigLoaderFactory()

        nodes_path = env_cfg.get("nodes_config_path")
        pipelines_path = env_cfg.get("pipelines_config_path")
        if not nodes_path:
            return {}

        nodes_cfg = loader.load_config(nodes_path)

        # Determine node order from pipeline definition
        pipeline_nodes: list[str] = []
        if pipelines_path:
            try:
                pipelines_cfg = loader.load_config(pipelines_path)
                p = pipelines_cfg.get(pipeline_name, {})
                pipeline_nodes = p.get("nodes", []) if isinstance(p, dict) else []
            except Exception:
                pass
        if not pipeline_nodes:
            pipeline_nodes = list(nodes_cfg.keys())

        workspace_root = str(project_dir)
        results: dict = {}
        for node_name in pipeline_nodes:
            node_cfg = nodes_cfg.get(node_name)
            if not node_cfg:
                continue
            output = node_cfg.get("output", {}) or {}
            if output.get("format") != "delta":
                continue
            path = output.get("path")
            if not path:
                continue
            if not os.path.isabs(path):
                resolved = os.path.abspath(os.path.join(workspace_root, path))
            else:
                resolved = os.path.abspath(path)
            results[node_name] = read_delta_parquet_preview(resolved)

        return results
    except Exception as exc:
        logger.debug("External streaming data read failed: {}", exc)
        return {}


def read_streaming_data(engine) -> dict:
    """Blocking Delta reads for a streaming pipeline's output nodes.

    Runs in a worker thread (Spark calls are blocking) so the API event loop is
    never stalled. Returns a mapping of node_name -> recent rows.
    """
    import os

    spark = getattr(engine.context, "spark", None)
    if not spark:
        return {}

    pipeline_name = engine.context.global_config.get("pipeline_name", "")
    pipeline = {}
    try:
        pipeline = engine.batch_executor._get_pipeline_config(pipeline_name)
    except Exception:
        pass

    from ducta.core.utils import extract_pipeline_nodes

    try:
        pipeline_nodes = extract_pipeline_nodes(pipeline)
    except Exception:
        pipeline_nodes = list(engine.context.nodes_config.keys())

    workspace_root = getattr(engine.context, "workspace_root", "")
    results: dict = {}
    for node_name in pipeline_nodes:
        node_cfg = engine.context.nodes_config.get(node_name)
        if not node_cfg:
            continue
        output = node_cfg.get("output", {}) or {}
        if output.get("format") != "delta":
            continue
        path = output.get("path")
        if not path:
            continue

        if workspace_root and not os.path.isabs(path):
            resolved_path = os.path.abspath(os.path.join(workspace_root, path))
        else:
            resolved_path = os.path.abspath(path)

        try:
            df = spark.read.format("delta").load(resolved_path)
            cols = df.columns
            sort_col = next((c for c in _STREAMING_PREVIEW_SORT_COLS if c in cols), None)
            if sort_col:
                df = df.orderBy(df[sort_col].desc())

            rows = df.limit(20).collect()
            results[node_name] = [json_safe(row.asDict(recursive=True)) for row in rows]
        except Exception as exc:
            logger.debug("Could not read streaming preview for node '{}': {}", node_name, exc)
            results[node_name] = []

    return results
