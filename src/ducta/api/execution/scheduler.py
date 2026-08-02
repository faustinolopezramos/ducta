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

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ducta.api.execution.manager import ExecutionManager


def _match_field(field_pattern: str, val: int) -> bool:
    """Check if an integer value matches a cron field pattern (e.g. '*', '*/5', '1,15', '1-5')."""
    pattern = field_pattern.strip()
    if pattern == "*":
        return True
    if pattern.startswith("*/"):
        try:
            step = int(pattern[2:])
            return step > 0 and (val % step == 0)
        except ValueError:
            return False
    if "," in pattern:
        for sub in pattern.split(","):
            if _match_field(sub, val):
                return True
        return False
    if "-" in pattern:
        try:
            start_str, end_str = pattern.split("-", 1)
            return int(start_str) <= val <= int(end_str)
        except ValueError:
            return False
    try:
        return int(pattern) == val
    except ValueError:
        return False


def is_cron_due(cron_expr: str, dt: datetime) -> bool:
    """Return True if datetime dt matches the 5-field cron expression (min hour dom month dow)."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    min_pat, hour_pat, dom_pat, month_pat, dow_pat = parts
    cron_dow = (dt.weekday() + 1) % 7

    return (
        _match_field(min_pat, dt.minute)
        and _match_field(hour_pat, dt.hour)
        and _match_field(dom_pat, dt.day)
        and _match_field(month_pat, dt.month)
        and _match_field(dow_pat, cron_dow)
    )


class PipelineSchedule(BaseModel):
    """Model for a scheduled pipeline execution."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    pipeline_name: str = Field(description="Name of the target pipeline")
    project_id: Optional[str] = Field(default=None, description="Optional project ID context")
    source_path: Optional[str] = Field(
        default=None,
        description=(
            "Resolved workspace source path (local directory or Git clone) this "
            "schedule targets, captured at creation time. Schedules without one "
            "(e.g. loaded from an older schedules.json) are skipped at trigger "
            "time rather than falling back to the server process's cwd."
        ),
    )
    env: str = Field(default="base", description="Execution environment")
    cron: str = Field(description="Standard 5-part cron expression (e.g. '0 0 * * *')")
    enabled: bool = Field(default=True, description="Whether schedule is active")
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional hyperparameters"
    )
    node_name: Optional[str] = Field(default=None, description="Optional specific node to execute")
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    last_run_at: Optional[str] = Field(
        default=None, description="ISO timestamp of last triggered execution"
    )
    next_run_hint: Optional[str] = Field(default=None, description="Human description of schedule")


class AsyncCronScheduler:
    """Background service managing automated scheduled pipeline executions."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._storage_dir = storage_dir or (Path.home() / ".ducta")
        self._file_path = self._storage_dir / "schedules.json"
        self._schedules: Dict[str, PipelineSchedule] = {}
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._last_checked_minute: Optional[str] = None
        self._load_schedules()

    def _load_schedules(self) -> None:
        if self._file_path.is_file():
            try:
                data = json.loads(self._file_path.read_text(encoding="utf-8"))
                for item in data:
                    sched = PipelineSchedule(**item)
                    self._schedules[sched.id] = sched
            except Exception as exc:
                logger.warning(f"Failed to load schedules from {self._file_path}: {exc}")

    def _save_schedules(self) -> None:
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            raw = [s.model_dump() for s in self._schedules.values()]
            tmp_path = self._file_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            os.replace(tmp_path, self._file_path)
        except Exception as exc:
            logger.error(f"Failed to save schedules to {self._file_path}: {exc}")

    async def start(self, manager: ExecutionManager) -> None:
        """Start background scheduler loop."""
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._scheduler_loop(manager))
            logger.info("AsyncCronScheduler background loop started")

    async def stop(self) -> None:
        """Stop background scheduler loop."""
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
            logger.info("AsyncCronScheduler background loop stopped")

    async def _scheduler_loop(self, manager: ExecutionManager) -> None:
        while True:
            try:
                await asyncio.sleep(15)  # Check every 15 seconds
                now = datetime.now(tz=timezone.utc)
                current_minute = now.strftime("%Y-%m-%d %H:%M")

                if current_minute == self._last_checked_minute:
                    continue

                self._last_checked_minute = current_minute

                async with self._lock:
                    for sched in list(self._schedules.values()):
                        if not sched.enabled:
                            continue
                        if is_cron_due(sched.cron, now):
                            logger.info(
                                f"Triggering scheduled pipeline '{sched.pipeline_name}' (Schedule ID: {sched.id})"
                            )
                            if not sched.source_path:
                                logger.error(
                                    f"Schedule '{sched.id}' ({sched.pipeline_name}) has no "
                                    "source_path recorded; skipping trigger. Recreate the "
                                    "schedule to fix this."
                                )
                                continue

                            sched.last_run_at = now.isoformat()
                            self._save_schedules()

                            source_path = Path(sched.source_path)

                            try:
                                manager.execute(
                                    source_path=source_path,
                                    pipeline_name=sched.pipeline_name,
                                    env=sched.env,
                                    node_name=sched.node_name,
                                    project_id=sched.project_id,
                                    hyperparams=sched.hyperparams,
                                )
                            except Exception as exc:
                                logger.error(
                                    f"Failed to trigger scheduled execution for '{sched.pipeline_name}': {exc}"
                                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in AsyncCronScheduler loop: {exc}")

    async def list_schedules(self) -> List[PipelineSchedule]:
        async with self._lock:
            return list(self._schedules.values())

    async def create_schedule(self, schedule: PipelineSchedule) -> PipelineSchedule:
        async with self._lock:
            self._schedules[schedule.id] = schedule
            self._save_schedules()
            return schedule

    async def delete_schedule(self, schedule_id: str) -> bool:
        async with self._lock:
            if schedule_id in self._schedules:
                del self._schedules[schedule_id]
                self._save_schedules()
                return True
            return False

    async def toggle_schedule(
        self, schedule_id: str, enabled: Optional[bool] = None
    ) -> Optional[PipelineSchedule]:
        async with self._lock:
            sched = self._schedules.get(schedule_id)
            if not sched:
                return None
            sched.enabled = not sched.enabled if enabled is None else enabled
            self._save_schedules()
            return sched


_scheduler: Optional[AsyncCronScheduler] = None


def get_cron_scheduler() -> AsyncCronScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncCronScheduler()
    return _scheduler
