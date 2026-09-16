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

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ducta.api.dependencies import CurrentUserDep, SourcePathDep, require_permission
from ducta.api.execution.scheduler import (
    PipelineSchedule,
    compute_next_run,
    get_cron_scheduler,
    validate_cron,
)

router = APIRouter(prefix="/schedules", tags=["Schedules"])


class CreateScheduleRequest(BaseModel):
    pipeline_name: str = Field(description="Name of the pipeline to schedule")
    cron: str = Field(description="5-part cron expression (e.g. '0 0 * * *')")
    env: str = Field(default="base", description="Execution environment")
    project_id: Optional[str] = Field(default=None, description="Optional project ID context")
    node_name: Optional[str] = Field(default=None, description="Optional node name context")
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional hyperparameters"
    )


class UpdateScheduleRequest(BaseModel):
    pipeline_name: Optional[str] = Field(default=None, description="Name of the pipeline to run")
    cron: Optional[str] = Field(default=None, description="5-part cron expression")
    env: Optional[str] = Field(default=None, description="Execution environment")
    node_name: Optional[str] = Field(default=None, description="Optional node name context")
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional hyperparameters"
    )


class ScheduleWithNextRun(PipelineSchedule):
    """A schedule annotated with its next expected run, computed on read."""

    next_run_at: Optional[str] = Field(
        default=None, description="ISO UTC timestamp of the next expected trigger"
    )


class SchedulesListResponse(BaseModel):
    schedules: List[ScheduleWithNextRun]
    count: int


def _with_next_run(sched: PipelineSchedule) -> ScheduleWithNextRun:
    next_run = (
        compute_next_run(sched.cron, datetime.now(tz=timezone.utc)) if sched.enabled else None
    )
    return ScheduleWithNextRun(
        **sched.model_dump(),
        next_run_at=next_run.isoformat() if next_run else None,
    )


def _validate_cron_or_400(cron: str) -> None:
    try:
        validate_cron(cron)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get(
    "",
    response_model=SchedulesListResponse,
    summary="List scheduled pipeline triggers for the current workspace",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def list_schedules(source_path: SourcePathDep) -> SchedulesListResponse:
    scheduler = get_cron_scheduler()
    items = await scheduler.list_schedules(str(source_path))
    return SchedulesListResponse(schedules=[_with_next_run(s) for s in items], count=len(items))


@router.post(
    "",
    response_model=ScheduleWithNextRun,
    status_code=201,
    summary="Create a new automated pipeline schedule",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def create_schedule(
    body: CreateScheduleRequest, source_path: SourcePathDep, current_user: CurrentUserDep
) -> ScheduleWithNextRun:
    _validate_cron_or_400(body.cron)
    sched = PipelineSchedule(
        pipeline_name=body.pipeline_name,
        cron=body.cron,
        env=body.env,
        project_id=body.project_id,
        node_name=body.node_name,
        hyperparams=body.hyperparams,
        user_id=current_user.id,
        # Captured now (same resolution as manual runs: ?source=, X-Source-Path,
        # or DUCTA_WORKSPACE) so the scheduler loop knows exactly which
        # workspace to target — see execution/scheduler.py::_scheduler_loop.
        source_path=str(source_path),
    )
    scheduler = get_cron_scheduler()
    created = await scheduler.create_schedule(sched)
    return _with_next_run(created)


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleWithNextRun,
    summary="Edit an existing scheduled pipeline trigger",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def update_schedule(
    schedule_id: str, body: UpdateScheduleRequest, source_path: SourcePathDep
) -> ScheduleWithNextRun:
    if body.cron is not None:
        _validate_cron_or_400(body.cron)
    scheduler = get_cron_scheduler()
    updated = await scheduler.update_schedule(
        schedule_id,
        str(source_path),
        pipeline_name=body.pipeline_name,
        cron=body.cron,
        env=body.env,
        node_name=body.node_name,
        hyperparams=body.hyperparams,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    return _with_next_run(updated)


@router.delete(
    "/{schedule_id}",
    status_code=204,
    summary="Delete a scheduled pipeline trigger",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def delete_schedule(schedule_id: str, source_path: SourcePathDep) -> None:
    scheduler = get_cron_scheduler()
    success = await scheduler.delete_schedule(schedule_id, str(source_path))
    if not success:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")


@router.post(
    "/{schedule_id}/toggle",
    response_model=ScheduleWithNextRun,
    summary="Toggle or set enabled status for a schedule",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def toggle_schedule(
    schedule_id: str, source_path: SourcePathDep, enabled: Optional[bool] = None
) -> ScheduleWithNextRun:
    scheduler = get_cron_scheduler()
    updated = await scheduler.toggle_schedule(schedule_id, str(source_path), enabled=enabled)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    return _with_next_run(updated)
