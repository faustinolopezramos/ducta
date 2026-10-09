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

The first rows of a dataset as last materialized in an environment, and its
columns — read with pyarrow/pandas from the local filesystem, no Spark session.
Remote storage and table formats with a transaction log are reported as not
previewable rather than read wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ducta.api.execution.runner import normalize_execution_context_paths, select_execution_cwd
from ducta.api.workspace.manager import WorkspaceManager

#: Formats read here, by catalog `format`.
READABLE = {"parquet", "csv", "json"}


class PreviewUnavailable(Exception):
    """The dataset exists in config but cannot be previewed here (and why)."""


def _fmt(value: Any) -> str:
    return str(getattr(value, "value", value) or "").lower()


def dataset_location(
    project_dir: Path, env: str, name: str, scratch: bool = False
) -> Tuple[Optional[str], str]:
    """``(path, format)`` of *name* as the engine resolves it in *env* — or, with
    *scratch*, where the last sample run wrote it (``<output>/<env>/.ducta/scratch``)."""
    ctx = WorkspaceManager(project_dir).load_context(env)
    env_dir = project_dir / env if (project_dir / env).is_dir() else project_dir
    normalize_execution_context_paths(ctx, select_execution_cwd(project_dir, env_dir, ctx))
    entry = (getattr(ctx, "input_config", {}) or {}).get(name) or (
        getattr(ctx, "output_config", {}) or {}
    ).get(name)
    if entry is None:
        raise KeyError(name)
    path = entry.get("filepath") or entry.get("path")
    if not path:
        # An output nobody reads: the conventional <output>/<env>/<schema>/<sub>/<table>.
        parts = name.split(".")
        output = (getattr(ctx, "global_config", {}) or {}).get("output_path")
        if output and len(parts) == 3:
            path = str(Path(output) / env / Path(*parts))
    if scratch and path and "://" not in path:
        output = (getattr(ctx, "global_config", {}) or {}).get("output_path")
        if not output:
            return None, _fmt(entry.get("format"))
        try:
            rel = Path(path).relative_to(Path(output))
        except ValueError:
            rel = Path(*name.split("."))  # as redirect_to_scratch places it
        path = str(Path(output) / env / ".ducta" / "scratch" / rel)
    return path, _fmt(entry.get("format"))


def read_frame(
    path: Optional[str], fmt: str, limit: int = 100
) -> "tuple[Any, List[Dict[str, str]], Optional[int]]":
    """The first *limit* rows of a local dataset as a pandas frame, its columns
    (name and type) and, when cheap to know, its total row count."""
    if not path:
        raise PreviewUnavailable("The catalog gives this dataset no path to read")
    if "://" in path:
        raise PreviewUnavailable(f"Remote storage is not previewed here: {path}")
    if fmt not in READABLE:
        raise PreviewUnavailable(f"Format '{fmt}' is not previewed here (parquet, csv, json are)")
    p = Path(path)
    if not p.exists():
        raise PreviewUnavailable(f"Not materialized in this environment yet: {path}")

    import pandas as pd

    if fmt == "parquet":
        import pyarrow.dataset as ds

        dataset = ds.dataset(str(p), format="parquet", exclude_invalid_files=True)
        table = dataset.head(limit)
        df = table.to_pandas()
        columns = [{"name": f.name, "type": str(f.type)} for f in dataset.schema]
        total: Optional[int] = dataset.count_rows()
    else:
        files = sorted(
            f
            for f in (p.rglob("*") if p.is_dir() else [p])
            if f.is_file() and not f.name.startswith(("_", "."))
        )
        if not files:
            raise PreviewUnavailable(f"No data files under {path}")
        if fmt == "csv":
            df = pd.read_csv(files[0], nrows=limit)
        else:
            df = pd.read_json(files[0], lines=True, nrows=limit)
        columns = [{"name": str(c), "type": str(t)} for c, t in df.dtypes.items()]
        total = None
    return df, columns, total


def preview(path: Optional[str], fmt: str, limit: int = 100) -> Dict[str, Any]:
    df, columns, total = read_frame(path, fmt, limit)
    p = Path(str(path))
    rows: List[Dict[str, Any]] = json.loads(
        df.head(limit).to_json(orient="records", date_format="iso")
    )
    return {"path": str(p), "format": fmt, "columns": columns, "rows": rows, "total_rows": total}
