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

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ducta.api.dependencies import SourcePathDep, require_permission
from ducta.api.execution.scheduler import PipelineSchedule, get_cron_scheduler

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


class SchedulesListResponse(BaseModel):
    schedules: List[PipelineSchedule]
    count: int


@router.get(
    "",
    response_model=SchedulesListResponse,
    summary="List all scheduled pipeline triggers",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def list_schedules() -> SchedulesListResponse:
    scheduler = get_cron_scheduler()
    items = await scheduler.list_schedules()
    return SchedulesListResponse(schedules=items, count=len(items))


@router.post(
    "",
    response_model=PipelineSchedule,
    status_code=201,
    summary="Create a new automated pipeline schedule",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def create_schedule(
    body: CreateScheduleRequest, source_path: SourcePathDep
) -> PipelineSchedule:
    parts = body.cron.strip().split()
    if len(parts) != 5:
        raise HTTPException(
            status_code=400,
            detail="Invalid cron expression. Expected 5 fields: 'minute hour day-of-month month day-of-week'",
        )
    sched = PipelineSchedule(
        pipeline_name=body.pipeline_name,
        cron=body.cron,
        env=body.env,
        project_id=body.project_id,
        node_name=body.node_name,
        hyperparams=body.hyperparams,
        # Captured now (same resolution as manual runs: ?source=, X-Source-Path,
        # or DUCTA_WORKSPACE) so the scheduler loop knows exactly which
        # workspace to target — see execution/scheduler.py::_scheduler_loop.
        source_path=str(source_path),
    )
    scheduler = get_cron_scheduler()
    return await scheduler.create_schedule(sched)


@router.delete(
    "/{schedule_id}",
    status_code=204,
    summary="Delete a scheduled pipeline trigger",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def delete_schedule(schedule_id: str) -> None:
    scheduler = get_cron_scheduler()
    success = await scheduler.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")


@router.post(
    "/{schedule_id}/toggle",
    response_model=PipelineSchedule,
    summary="Toggle or set enabled status for a schedule",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def toggle_schedule(schedule_id: str, enabled: Optional[bool] = None) -> PipelineSchedule:
    scheduler = get_cron_scheduler()
    updated = await scheduler.toggle_schedule(schedule_id, enabled=enabled)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    return updated
