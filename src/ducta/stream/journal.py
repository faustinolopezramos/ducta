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

# What a streaming run leaves on disk, so it outlives the process that ran it:
#
#   <output_path>/<environment>/.ducta/streams/<pipeline>/<run_id>/
#       run.json        who ran it, its nodes, its status (rewritten atomically)
#       batches.jsonl   one line per batch with data: "progress" lines for every
#                       node (from Spark's progress reports) and "batch" lines for
#                       nodes written per micro-batch (quarantine, gate verdict)
#
# A run.json still saying "running" whose process is gone is read as
# "interrupted": the server or the CLI that ran it stopped without saying so.

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from loguru import logger  # type: ignore

from ducta.stream.checkpoints import CheckpointManager
from ducta.stream.context_utils import get_active_env, get_context_value

JOURNAL_DIR_TEMPLATE = "${output_path}/${environment}/.ducta/streams"

#: batches.jsonl is rotated to batches.1.jsonl past this size (one older file kept).
MAX_BATCHES_BYTES = 20 * 1024 * 1024

#: Statuses after which a run writes nothing more.
FINAL_STATUSES = frozenset({"completed", "stopped", "failed", "error", "partial_failure"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def journal_base(context: Any) -> Optional[str]:
    """Where this context's stream journals live; None without a local output path."""
    gs = get_context_value(context, "global_config", {}) or {}
    gs = gs if isinstance(gs, dict) else {}
    output_path = get_context_value(context, "output_path", None) or gs.get("output_path")
    if not output_path:
        return None
    base = CheckpointManager._scope_by_environment(
        str(gs.get("stream_journal_dir") or JOURNAL_DIR_TEMPLATE),
        gs,
        str(output_path),
        get_active_env(context),
    )
    if CheckpointManager.is_cloud_path(base):
        # Appends to object storage are not what a journal can afford per batch.
        logger.debug("Stream journal disabled: {} is not a local path", base)
        return None
    return base


class StreamRunJournal:
    """The on-disk record of one streaming run (see the module note). Thread-safe."""

    def __init__(
        self,
        base: str,
        pipeline: str,
        run_id: str,
        execution_id: str,
        nodes: List[str],
        api_execution_id: Optional[str] = None,
    ) -> None:
        self.dir = (
            Path(base)
            / CheckpointManager.sanitize_path_component(pipeline)
            / CheckpointManager.sanitize_path_component(run_id)
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.run: Dict[str, Any] = {
            "pipeline": pipeline,
            "run_id": run_id,
            "execution_id": execution_id,
            "api_execution_id": api_execution_id,
            "nodes": list(nodes),
            "status": "starting",
            "error": None,
            "started_at": _now(),
            "ended_at": None,
            "pid": os.getpid(),
            "host": socket.gethostname(),
        }
        self._write_run()

    @property
    def batches_path(self) -> Path:
        return self.dir / "batches.jsonl"

    def set_status(
        self,
        status: str,
        error: Optional[str] = None,
        nodes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record the run's status; *nodes* is each node's final outcome, at the end."""
        with self._lock:
            if self.run["status"] == status and self.run["error"] == error and nodes is None:
                return
            self.run["status"] = status
            self.run["error"] = error
            if nodes is not None:
                self.run["outcome"] = nodes
            if status in FINAL_STATUSES:
                self.run["ended_at"] = self.run["ended_at"] or _now()
            self._write_run()

    def record(self, kind: str, line: Dict[str, Any]) -> None:
        """Append one batch line (``kind`` is "progress" or "batch")."""
        entry = {"kind": kind, "ts": _now(), **line}
        text = json.dumps(entry, default=str) + "\n"
        with self._lock:
            try:
                path = self.batches_path
                if path.exists() and path.stat().st_size > MAX_BATCHES_BYTES:
                    os.replace(path, self.dir / "batches.1.jsonl")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:  # the journal must never break the stream
                logger.warning("Could not write to the stream journal {}: {}", self.dir, e)

    def _write_run(self) -> None:
        try:
            fd, tmp = tempfile.mkstemp(dir=str(self.dir), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.run, f, indent=2, default=str)
            os.replace(tmp, self.dir / "run.json")
        except OSError as e:
            logger.warning("Could not write the stream journal {}: {}", self.dir, e)


# ── reading ──────────────────────────────────────────────────────────────────


def _process_alive(pid: Any, host: Any) -> bool:
    if host != socket.gethostname():
        return True  # another machine's process: nothing to tell from here
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def load_run(run_dir: Path) -> Optional[Dict[str, Any]]:
    """``run.json`` of *run_dir*, with ``interrupted`` for a run whose process is gone."""
    try:
        run: Dict[str, Any] = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if run.get("status") not in FINAL_STATUSES and not _process_alive(
        run.get("pid"), run.get("host")
    ):
        run["status"] = "interrupted"
    run["journal_dir"] = str(run_dir)
    return run


def iter_runs(base: str, pipeline: str) -> Iterator[Dict[str, Any]]:
    """Runs of *pipeline* under *base*, newest first."""
    root = Path(base) / CheckpointManager.sanitize_path_component(pipeline)
    if not root.is_dir():
        return iter(())
    runs = [run for run in (load_run(d) for d in root.iterdir() if d.is_dir()) if run]
    return iter(sorted(runs, key=lambda r: str(r.get("started_at") or ""), reverse=True))


def find_run(
    base: str,
    pipeline: str,
    *,
    run_id: Optional[str] = None,
    api_execution_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    for run in iter_runs(base, pipeline):
        if run_id and run.get("run_id") == run_id:
            return run
        if api_execution_id and run.get("api_execution_id") == api_execution_id:
            return run
    return None


def iter_lines(run_dir: Path) -> Iterator[Dict[str, Any]]:
    """Every batch line of a run, oldest first (rotated file included)."""
    for name in ("batches.1.jsonl", "batches.jsonl"):
        path = Path(run_dir) / name
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue  # a line cut by a crash


def summarize(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Per node: batches with data, rows read/written/quarantined, gate verdicts."""
    nodes: Dict[str, Dict[str, Any]] = {}
    for line in iter_lines(run_dir):
        node = nodes.setdefault(
            str(line.get("node")),
            {
                "batches": 0,
                "first_batch": None,
                "last_batch": None,
                "rows_in": 0,
                "rows_written": None,
                "rows_quarantined": 0,
                "gate": {},
            },
        )
        batch_id = line.get("batch_id")
        if line.get("kind") == "progress":
            node["batches"] += 1
            node["rows_in"] += int(line.get("rows") or 0)
        elif line.get("kind") == "batch":
            node["rows_written"] = (node["rows_written"] or 0) + int(line.get("rows_written") or 0)
            node["rows_quarantined"] += int(line.get("rows_quarantined") or 0)
            if line.get("gate"):
                node["gate"][line["gate"]] = node["gate"].get(line["gate"], 0) + 1
        if isinstance(batch_id, int):
            if node["first_batch"] is None or batch_id < node["first_batch"]:
                node["first_batch"] = batch_id
            if node["last_batch"] is None or batch_id > node["last_batch"]:
                node["last_batch"] = batch_id
    return nodes


def recent_trigger_ms(
    base: str, pipeline: str, node: str, *, exclude_run: Optional[str] = None, limit: int = 50
) -> List[float]:
    """The last *limit* batch durations of *node* in the newest earlier run that has any."""
    for run in iter_runs(base, pipeline):
        if exclude_run and run.get("run_id") == exclude_run:
            continue
        values = [
            float(line["trigger_ms"])
            for line in iter_lines(Path(run["journal_dir"]))
            if line.get("kind") == "progress"
            and line.get("node") == node
            and isinstance(line.get("trigger_ms"), (int, float))
        ]
        if values:
            return values[-limit:]
    return []
