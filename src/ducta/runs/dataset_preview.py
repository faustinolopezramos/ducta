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

import io
import json
from itertools import islice
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from ducta import state
from ducta.runs.context import (
    load_project_context,
    normalize_execution_context_paths,
    select_execution_cwd,
)

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
    ctx = load_project_context(project_dir, env)
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
        path = str(state.scratch_dir(output, env) / rel)
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
    return {
        "path": str(p),
        "format": fmt,
        "columns": columns,
        "rows": rows,
        "total_rows": total,
        "modified_at": _modified_at(p),
    }


#: Files looked at to date a dataset directory that is not a Delta table.
_MAX_FILES_DATED = 2000


def _modified_at(p: Path) -> Optional[str]:
    """When the data at *p* was last written: the newest file under a dataset directory.

    A Delta table's last write is its newest commit in ``_delta_log`` — read
    there rather than over every data file, which a large table has thousands of.
    """
    from datetime import datetime, timezone
    from itertools import islice

    try:
        if p.is_dir():
            log = p / "_delta_log"
            files = log.glob("*.json") if log.is_dir() else p.rglob("*")
            times = [f.stat().st_mtime for f in islice(files, _MAX_FILES_DATED) if f.is_file()]
            if not times:
                return None
            at = max(times)
        else:
            at = p.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(at, tz=timezone.utc).isoformat()


# ── The newest rows of a dataset that is being written (a stream's sink) ─────

#: Formats whose newest rows can be read here; a Delta table is read as the parquet files in it.
TAIL_FORMATS = {"parquet", "delta", "csv", "json"}

#: Files listed under a sink to find the newest ones, and files actually read for rows.
_MAX_FILES_LISTED = 20000
_MAX_FILES_READ = 20
#: Bytes read from the end of a json/csv file to find its last rows.
_TAIL_BYTES = 8 * 1024 * 1024
#: A cell longer than this is cut: the page shows rows, it does not move documents.
MAX_CELL_CHARS = 500

_SUFFIXES = {
    "parquet": (".parquet",),
    "delta": (".parquet",),
    "csv": (".csv",),
    "json": (".json", ".jsonl", ".ndjson"),
}


def _newest_files(root: Path, fmt: str) -> List[Path]:
    """Data files of *root*, the most recently written first.

    Spark's bookkeeping (``_delta_log``, ``_spark_metadata``, ``_temporary``, ``_SUCCESS``) and
    hidden files (``.crc``) are not data: nothing under a ``_`` or ``.`` name is read.
    """
    suffixes = _SUFFIXES[fmt]
    if root.is_file():
        return [root]
    found: List[Tuple[float, str, Path]] = []
    for f in islice(root.rglob("*"), _MAX_FILES_LISTED):
        rel = f.relative_to(root).parts
        if any(part.startswith(("_", ".")) for part in rel) or not f.is_file():
            continue
        if not f.name.endswith(suffixes):
            continue
        try:
            found.append((f.stat().st_mtime, f.name, f))
        except OSError:
            continue  # written, then compacted away while listing
    found.sort(reverse=True)
    return [f for _, _, f in found]


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value


def _records(df: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = json.loads(df.to_json(orient="records", date_format="iso"))
    return [{k: _clip(v) for k, v in row.items()} for row in rows]


def _tail_text(path: Path) -> Tuple[str, bool]:
    """The last ``_TAIL_BYTES`` of a text file, and whether it is the whole file."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > _TAIL_BYTES:
            handle.seek(size - _TAIL_BYTES)
        data = handle.read()
    text = data.decode("utf-8", errors="replace")
    if size > _TAIL_BYTES:
        text = text.split("\n", 1)[1] if "\n" in text else ""  # the first line is cut in half
    return text, size <= _TAIL_BYTES


def _tail_parquet(
    files: List[Path], limit: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    import pandas as pd
    import pyarrow.parquet as pq

    rows: List[Dict[str, Any]] = []
    columns: List[Dict[str, str]] = []
    for f in files[:_MAX_FILES_READ]:
        try:
            pf = pq.ParquetFile(str(f))
        except Exception:  # noqa: BLE001 — a file still being written has no footer yet
            continue
        if not columns:
            columns = [{"name": fld.name, "type": str(fld.type)} for fld in pf.schema_arrow]
        frames = []
        have = 0
        for group in range(
            pf.num_row_groups - 1, -1, -1
        ):  # the last row groups hold the newest rows
            table = pf.read_row_group(group)
            frames.append(table.to_pandas())
            have += table.num_rows
            if have >= limit - len(rows):
                break
        if not frames:
            continue
        df = pd.concat(list(reversed(frames)), ignore_index=True)
        rows.extend(reversed(_records(df.tail(limit - len(rows)))))
        if len(rows) >= limit:
            break
    return rows, columns


def _tail_lines(
    files: List[Path], fmt: str, limit: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    import pandas as pd

    rows: List[Dict[str, Any]] = []
    columns: List[Dict[str, str]] = []
    for f in files[:_MAX_FILES_READ]:
        text, whole = _tail_text(f)
        if fmt == "json":
            parsed = []
            for line in text.splitlines():
                try:
                    parsed.append(json.loads(line))
                except ValueError:
                    continue  # a line cut in half by a write in progress
            df = pd.DataFrame([r for r in parsed if isinstance(r, dict)])
        else:
            header = f.open("r", encoding="utf-8", errors="replace").readline()
            body = text if whole else header + text
            try:
                df = pd.read_csv(io.StringIO(body))
            except Exception:  # noqa: BLE001 — empty or half-written file
                continue
        if df.empty:
            continue
        if not columns:
            columns = [{"name": str(c), "type": str(t)} for c, t in df.dtypes.items()]
        rows.extend(reversed(_records(df.tail(limit - len(rows)))))
        if len(rows) >= limit:
            break
    return rows, columns


#: Footers opened per call at most: a sink seen for the first time with tens of thousands of
#: files is counted over a few reads instead of stalling one.
_FOOTER_BUDGET = 2000
#: Footers remembered (a file's rows never change while its mtime and size do not).
_FOOTER_CACHE_MAX = 200_000
#: Sinks whose last answer is remembered, to answer again while nothing new has landed.
_TAIL_CACHE_MAX = 64

_cache_lock = Lock()
#: path -> (mtime, size, rows) of a parquet file whose footer was read.
_footer_rows: Dict[str, Tuple[float, int, int]] = {}
#: (path, fmt, limit) -> (what the sink looked like, the answer given then).
_tail_answers: Dict[Tuple[str, str, int], Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}


def _count_parquet_rows(files: List[Path]) -> Optional[int]:
    """Rows in every parquet file under a sink, from the footers alone.

    A footer is read once per file and remembered: a stream's sink grows by new files, so
    each call opens only the files that landed since the last one (it used to open them all,
    every few seconds, and gave up past 2000 files). At most ``_FOOTER_BUDGET`` footers are
    opened per call; with more still unread the total is not known yet (None) and the next
    call carries on.
    """
    import pyarrow.parquet as pq

    total = 0
    opened = 0
    complete = True
    for f in files:
        key = str(f)
        try:
            st = f.stat()
        except OSError:
            continue  # compacted away while counting
        with _cache_lock:
            known = _footer_rows.get(key)
        if known is not None and known[0] == st.st_mtime and known[1] == st.st_size:
            total += known[2]
            continue
        if opened >= _FOOTER_BUDGET:
            complete = False
            continue
        opened += 1
        try:
            rows = pq.ParquetFile(key).metadata.num_rows
        except Exception:  # noqa: BLE001 — still being written: counted once it has a footer
            continue
        with _cache_lock:
            if len(_footer_rows) >= _FOOTER_CACHE_MAX:
                _footer_rows.clear()
            _footer_rows[key] = (st.st_mtime, st.st_size, rows)
        total += rows
    return total if complete else None


def _sink_signature(files: List[Path]) -> Optional[Tuple[Any, ...]]:
    """What a sink looks like, cheaply: how many files, and which is the newest (its mtime and
    size). A batch that lands changes it; a sink nothing wrote to since keeps it."""
    try:
        st = files[0].stat()
    except OSError:
        return None
    return (len(files), str(files[0]), st.st_mtime, st.st_size)


def tail_rows(path: Optional[str], fmt: str, limit: int = 50) -> Dict[str, Any]:
    """The newest *limit* rows of a local dataset that something is writing to, newest first.

    "Newest" is by the time each file was written, then the row's place in its file: a
    stream's sink grows by files. A Delta table is read as the parquet files in its
    directory (so rows of files a later overwrite or merge replaced can still show until
    they are cleaned up). ``total_rows`` is the sum of the parquet footers; ``newest_at``
    is when the latest file landed.
    """
    from datetime import datetime, timezone

    if not path:
        raise PreviewUnavailable("This node has no path to read")
    if "://" in path:
        raise PreviewUnavailable(f"Remote storage is not read here: {path}")
    if fmt not in TAIL_FORMATS:
        raise PreviewUnavailable(
            f"A '{fmt}' sink has no rows to show here (parquet, delta, csv and json do)"
        )
    root = Path(path)
    if not root.exists():
        raise PreviewUnavailable(f"Nothing written yet: {path}")
    files = _newest_files(root, fmt)
    if not files:
        raise PreviewUnavailable(f"No data files under {path} yet")

    # Nothing landed since the last read of this sink: the same answer, without reading a row.
    cache_key = (str(root), fmt, int(limit))
    signature = _sink_signature(files)
    with _cache_lock:
        cached = _tail_answers.get(cache_key)
    if cached is not None and signature is not None and cached[0] == signature:
        if cached[1].get("total_rows") is not None or fmt not in ("parquet", "delta"):
            return dict(cached[1])

    rows, columns = (
        _tail_parquet(files, limit)
        if fmt in ("parquet", "delta")
        else _tail_lines(files, fmt, limit)
    )
    newest = files[0].stat().st_mtime
    answer = {
        "path": str(root),
        "format": fmt,
        "columns": columns,
        "rows": rows[:limit],
        "total_rows": _count_parquet_rows(files) if fmt in ("parquet", "delta") else None,
        "newest_at": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat(),
        "files": len(files),
    }
    if signature is not None:
        with _cache_lock:
            if len(_tail_answers) >= _TAIL_CACHE_MAX:
                _tail_answers.pop(next(iter(_tail_answers)))
            _tail_answers[cache_key] = (signature, answer)
    return dict(answer)


def sink_location(project_dir: Path, env: str, sink: str) -> Tuple[str, Path]:
    """``(format, path)`` of a stream node's sink as the status says it (``"parquet data/dev/x"``,
    ``"delta merge on [id] data/dev/x"``), the path made absolute the way the run saw it.

    A relative path is relative to the run's working directory (see ``select_execution_cwd``).
    The result must lie in the project or in its configured input/output folders: this
    reads what configuration points at, and configuration must not be able to point it at
    the rest of the disk.
    """
    words = (sink or "").split()
    if not words:
        raise PreviewUnavailable("This node's sink is not known")
    fmt = _fmt(words[0])
    if len(words) < 2:
        raise PreviewUnavailable(f"A '{fmt}' sink has no path to read")
    raw = words[-1]
    if "://" in raw:
        raise PreviewUnavailable(f"Remote storage is not read here: {raw}")

    ctx = load_project_context(project_dir, env)
    env_dir = project_dir / env if (project_dir / env).is_dir() else project_dir
    cwd = select_execution_cwd(project_dir, env_dir, ctx)
    path = Path(raw)
    resolved = (path if path.is_absolute() else cwd / path).resolve()

    global_config = getattr(ctx, "global_config", {}) or {}
    roots = [project_dir.resolve()]
    for key in ("input_path", "output_path"):
        value = global_config.get(key)
        if isinstance(value, str) and value.strip() and "://" not in value:
            folder = Path(value)
            roots.append((folder if folder.is_absolute() else cwd / folder).resolve())
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise PreviewUnavailable(
            "This sink lies outside the project, so its rows are not shown here"
        )
    return fmt, resolved
