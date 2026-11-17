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
from pydantic import BaseModel, Field, field_validator

from ducta_server.dependencies import CurrentUserDep, SourcePathDep, require_permission
from ducta_server.exceptions import http_error_on
from ducta_server.execution.scheduler import (
    PipelineSchedule,
    compute_next_run,
    get_cron_scheduler,
    validate_cron,
)
from ducta_server.utils.validators import validate_environment_name

router = APIRouter(prefix="/schedules", tags=["Schedules"])


def _check_env(v: Optional[str]) -> Optional[str]:
    return v if v is None else validate_environment_name(v)


class CreateScheduleRequest(BaseModel):
    pipeline_name: str = Field(description="Name of the pipeline to schedule")
    cron: str = Field(description="5-part cron expression (e.g. '0 0 * * *')")
    env: str = Field(default="base", description="Execution environment")
    project_id: Optional[str] = Field(default=None, description="Optional project ID context")
    node_name: Optional[str] = Field(default=None, description="Optional node name context")
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional hyperparameters"
    )

    _env = field_validator("env")(_check_env)


class UpdateScheduleRequest(BaseModel):
    pipeline_name: Optional[str] = Field(default=None, description="Name of the pipeline to run")
    cron: Optional[str] = Field(default=None, description="5-part cron expression")
    env: Optional[str] = Field(default=None, description="Execution environment")
    node_name: Optional[str] = Field(default=None, description="Optional node name context")
    hyperparams: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional hyperparameters"
    )

    _env = field_validator("env")(_check_env)


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
    with http_error_on(422):
        validate_cron(cron)


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


def _check_may_run(user: Any, env: str, source_path: Any, project_id: Optional[str]) -> None:
    """403 when *user* may not run in *env* (protected environments take a role): a schedule
    is a run that happens later, with the same rule as running it now."""
    from ducta_server.services.governance import check_can_run
    from ducta_server.services.project import ProjectService

    root = None
    if project_id:
        try:
            root = ProjectService(source_path).store(project_id).root
        except Exception:  # noqa: BLE001 — unknown project: the defaults guard it
            root = None
    check_can_run(user, env, root)


async def _owned_schedule(schedule_id: str, source_path: Any, user: Any) -> Any:
    """The schedule, if *user* made it or may run protected environments (operator, admin);
    404 when it does not exist here, 403 when it is someone else's."""
    from ducta.project_store.governance import PROTECTED_PERMISSION

    sched = await get_cron_scheduler().get_schedule(schedule_id, str(source_path))
    if sched is None:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    if sched.user_id not in (None, user.id) and not user.has_permission(PROTECTED_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail="This schedule belongs to another user; only they, an operator or an admin "
            "can change it",
        )
    return sched


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
    _check_may_run(current_user, body.env, source_path, body.project_id)
    if body.project_id:
        # A schedule for a pipeline that does not exist was accepted, then failed at every
        # trigger: say so now (404), as running it by hand does.
        from ducta_server.services.project import ProjectService

        ProjectService(source_path).get_pipeline(body.project_id, body.pipeline_name)
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
    schedule_id: str,
    body: UpdateScheduleRequest,
    source_path: SourcePathDep,
    current_user: CurrentUserDep,
) -> ScheduleWithNextRun:
    if body.cron is not None:
        _validate_cron_or_400(body.cron)
    existing = await _owned_schedule(schedule_id, source_path, current_user)
    _check_may_run(current_user, body.env or existing.env, source_path, existing.project_id)
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
async def delete_schedule(
    schedule_id: str, source_path: SourcePathDep, current_user: CurrentUserDep
) -> None:
    await _owned_schedule(schedule_id, source_path, current_user)
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
    schedule_id: str,
    source_path: SourcePathDep,
    current_user: CurrentUserDep,
    enabled: Optional[bool] = None,
) -> ScheduleWithNextRun:
    await _owned_schedule(schedule_id, source_path, current_user)
    scheduler = get_cron_scheduler()
    updated = await scheduler.toggle_schedule(schedule_id, str(source_path), enabled=enabled)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    return _with_next_run(updated)
