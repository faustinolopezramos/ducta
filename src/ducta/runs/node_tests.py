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

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

FIXTURES_DIR = Path("tests") / "fixtures"


def _safe(name: str) -> str:
    return re.sub(r"\W+", "_", name).strip("_").lower()


def _uses_spark(source: str) -> bool:
    return "pyspark" in source


def _has_spark_fixture(root: Path) -> bool:
    conftest = root / "tests" / "conftest.py"
    return (
        conftest.is_file() and re.search(r"def spark\s*\(", conftest.read_text("utf-8")) is not None
    )


def _write_parquet(df: Any, path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    # Microseconds: Spark 3 cannot read nanosecond timestamps.
    pq.write_table(table, path, coerce_timestamps="us", allow_truncated_timestamps=True)


def pii_columns_of(project_root: Path, env: str, dataset: str) -> List[str]:
    """The columns the catalog lists in *dataset*'s ``metadata.pii`` (empty when none)."""
    try:
        from ducta.setting.project.loader import validate_project

        entry = (validate_project(Path(project_root), env).catalog or {}).get(dataset)
    except Exception:  # noqa: BLE001 — an unreadable project failed earlier, louder
        return []
    metadata = getattr(entry, "metadata", None) if entry is not None else None
    items = metadata.get("pii") if isinstance(metadata, dict) else None
    return [str(c) for c in items or [] if c]


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _stand_in(value: Any, n: int, col: str) -> Any:
    """The *n*-th stand-in of column *col*, of *value*'s kind: an email stays an email, a
    number a number, a date a date — so the node's code runs on it as on the real one."""
    import datetime as dt

    if isinstance(value, bool):
        return value  # one bit: nothing to tell, and its type is all a test needs
    if isinstance(value, str):
        return f"{col}_{n}@example.invalid" if _EMAIL.match(value.strip()) else f"{col}_{n}"
    if isinstance(value, int):
        return n
    if isinstance(value, float):
        return float(n)
    if isinstance(value, dt.datetime):
        return dt.datetime(2000, 1, 1) + dt.timedelta(days=n)
    if isinstance(value, dt.date):
        return dt.date(2000, 1, 1) + dt.timedelta(days=n)
    return None


def mask_pii(df: Any, pii: List[str]) -> tuple[Any, List[str]]:
    """``(df, masked columns)``: the *pii* columns of *df* (names matched case-insensitively)
    with each value replaced by a stand-in of the same kind (``email_1@example.invalid``,
    ``name_2``, ``3``, ``2000-01-04``): the same value, the same stand-in, so duplicates and
    joins behave. Nulls stay null and the column keeps its type.

    Fixtures go into the repository and to whoever reads its files: personal data has no
    place there, and a node test (it pins the output's columns) does not need it.
    """
    import pandas as pd

    wanted = {c.lower() for c in pii}
    masked = [c for c in df.columns if str(c).lower() in wanted]
    if not masked:
        return df, []
    df = df.copy()
    for col in masked:
        seen: Dict[Any, Any] = {}

        def stand_in(value: Any, col: Any = col, seen: Dict[Any, Any] = seen) -> Any:
            if value is None or value is pd.NaT or (isinstance(value, float) and value != value):
                return value
            if hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()
            try:
                if value not in seen:
                    seen[value] = _stand_in(value, len(seen) + 1, str(col))
                return seen[value]
            except TypeError:  # a list or a map: no stand-in of its kind, so none at all
                return None

        dtype = df[col].dtype
        out = df[col].astype(object).map(stand_in)
        try:
            df[col] = out.astype(dtype)
        except (TypeError, ValueError):  # a stand-in the old type cannot hold: keep it as is
            df[col] = out
    return df, [str(c) for c in masked]


def render_test(
    *,
    node: str,
    module: str,
    function: str,
    inputs: Dict[str, str],
    columns: List[str],
    fixtures: str,
    env: str,
    spark: bool,
    spark_fixture: bool,
    positional: bool,
) -> str:
    fn = _safe(function)
    lines = [
        f'"""Snapshot test for node `{node}`, generated by Ducta from its inputs in `{env}`',
        f"on {date.today().isoformat()}. It runs `{module}:{function}` on the fixtures and pins the",
        "columns it produces: adding, dropping or renaming one fails here first.",
        'Regenerate it from the node\'s Runs tab when the change is intended."""',
        "",
        "from pathlib import Path",
        "",
    ]
    if spark and not spark_fixture:
        lines += ["import pytest", "from pyspark.sql import SparkSession", ""]
    if not spark:
        lines += ["import pandas as pd", ""]
    lines += [
        f"from {module} import {function}",
        "",
        f'FIXTURES = Path(__file__).parent / "fixtures" / "{fixtures}"',
        f"EXPECTED_COLUMNS = {columns!r}",
        "",
    ]
    if spark and not spark_fixture:
        lines += [
            "",
            '@pytest.fixture(scope="module")',
            "def spark():",
            '    session = SparkSession.builder.master("local[1]").appName("ducta-snapshot").getOrCreate()',
            "    yield session",
            "    session.stop()",
            "",
        ]
    read = (
        (lambda alias: f'spark.read.parquet(str(FIXTURES / "{_safe(alias)}.parquet"))')
        if spark
        else (lambda alias: f'pd.read_parquet(FIXTURES / "{_safe(alias)}.parquet")')
    )
    args = (
        ", ".join(read(a) for a in inputs)
        if positional
        else ", ".join(f"{a}={read(a)}" for a in inputs)
    )
    lines += [
        "",
        f"def test_{fn}_keeps_its_output_columns({'spark' if spark else ''}):",
        f"    out = {function}({args})",
        "    assert list(out.columns) == EXPECTED_COLUMNS",
        "",
    ]
    return "\n".join(lines)


def generate_snapshot_test(
    *,
    project_root: Path,
    env: str,
    node: str,
    module: str,
    function: str,
    source_file: Path,
    inputs: Dict[str, str],
    output: Optional[str],
    rows: int = 20,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Write the fixtures and the test; returns what was written. Raises
    ``FileExistsError`` for an existing test unless *overwrite*, and
    ``LookupError`` when an input or the output is not materialized in *env*."""
    from ducta.runs.dataset_preview import (
        PreviewUnavailable,
        dataset_location,
        read_frame,
    )

    test_path = project_root / "tests" / f"test_{_safe(node)}_snapshot.py"
    if test_path.exists() and not overwrite:
        raise FileExistsError(str(test_path.relative_to(project_root)))
    if not output:
        raise LookupError(f"Node '{node}' writes no dataset to snapshot")

    def frame(dataset: str, limit: int) -> Any:
        try:
            path, fmt = dataset_location(project_root, env, dataset)
            return read_frame(path, fmt, limit)
        except (KeyError, PreviewUnavailable) as e:
            raise LookupError(f"{dataset} in {env}: {e}") from e

    _df, out_columns, _ = frame(output, 1)
    fixtures = _safe(node)
    written: List[str] = []
    masked: Dict[str, List[str]] = {}
    for alias, dataset in inputs.items():
        df, _cols, _ = frame(dataset, rows)
        df, hidden = mask_pii(df, pii_columns_of(project_root, env, dataset))
        if hidden:
            masked[dataset] = hidden
        target = project_root / FIXTURES_DIR / fixtures / f"{_safe(alias)}.parquet"
        _write_parquet(df, target)
        written.append(str(target.relative_to(project_root)))
    source = source_file.read_text("utf-8") if source_file.is_file() else ""
    text = render_test(
        node=node,
        module=module,
        function=function,
        inputs=inputs,
        columns=[c["name"] for c in out_columns],
        fixtures=fixtures,
        env=env,
        spark=_uses_spark(source),
        spark_fixture=_has_spark_fixture(project_root),
        # `inputs: [a, b]` is passed positionally; the index keys it by dataset name.
        positional=all(alias == dataset for alias, dataset in inputs.items()),
    )
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(text, encoding="utf-8")
    return {
        "test_file": str(test_path.relative_to(project_root)),
        "fixtures": written,
        "columns": [c["name"] for c in out_columns],
        "rows": rows,
        # The metadata.pii columns written as stand-ins, per input dataset.
        "masked": masked,
    }


def tests_for(project_root: Path, node: str, function: str) -> List[str]:
    """Test files that name the node or call its function."""
    folder = project_root / "tests"
    if not folder.is_dir():
        return []
    hits = []
    for path in sorted(folder.rglob("test_*.py")):
        text = path.read_text("utf-8", errors="replace")
        if node in text or re.search(rf"\b{re.escape(function)}\b", text):
            hits.append(str(path.relative_to(project_root)))
    return hits


def run_tests(
    project_root: Path,
    targets: List[str],
    timeout: int = 600,
    python: str = sys.executable,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Run pytest on *targets* in the project; per-test outcomes with file:line.

    The tests are the project's own code, so they get this process's environment
    minus the server's secrets (``JWT_SECRET_KEY``, the admin password, the certificate
    signing key, …) unless *env* is given.
    """
    if env is None:
        from ducta.server_secrets import withheld_from_runs

        env = {k: v for k, v in os.environ.items() if not withheld_from_runs(k)}
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        cmd = [
            python, "-m", "pytest", *targets, "-q", "--no-header", "-p", "no:cacheprovider",
            "--tb=short", f"--junitxml={report}", "-o", "junit_family=xunit1",
        ]  # fmt: skip
        try:
            proc = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=dict(env),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "exit_code": None,
                "tests": [],
                "output": f"Timed out after {timeout}s",
            }
        tests = _parse_junit(report, project_root) if report.exists() else []
    output = (proc.stdout + proc.stderr)[-20000:]
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "tests": tests,
        "summary": _summary(tests),
        "output": output,
    }


def _summary(tests: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t in tests:
        out[t["outcome"]] = out.get(t["outcome"], 0) + 1
    return out


_FRAME = re.compile(r"^(?P<file>[\w./-]+\.py):(?P<line>\d+):", re.M)


def _inside(root: Path, file: str) -> bool:
    path = Path(file)
    if path.is_absolute():
        return False  # site-packages and the interpreter: not the project's code
    return (root / path).is_file()


def _parse_junit(report: Path, root: Path) -> List[Dict[str, Any]]:
    tests = []
    for case in ET.parse(report).getroot().iter("testcase"):
        outcome, message, detail = "passed", None, None
        for tag in ("failure", "error", "skipped"):
            el = case.find(tag)
            if el is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = el.get("message")
                detail = (el.text or "")[-4000:]
                break
        file = case.get("file")
        raw_line = case.get("line")
        line = int(raw_line) + 1 if raw_line else None
        if detail:  # the deepest frame in the project's own code: where it failed
            frames = [m for m in _FRAME.finditer(detail) if _inside(root, m["file"])]
            if frames:
                file, line = frames[-1]["file"], int(frames[-1]["line"])
        tests.append(
            {
                "name": case.get("name"),
                "file": file,
                "line": line,
                "outcome": outcome,
                "message": message,
                "detail": detail,
                "seconds": float(case.get("time") or 0),
            }
        )
    return tests
