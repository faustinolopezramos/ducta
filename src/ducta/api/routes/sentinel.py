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

Ducta Sentinel over HTTP: its state, its incidents, and what a person does
with them. Reading takes ``sentinel.read``; pausing, resolving, ignoring or
re-running takes ``sentinel.manage`` (operators, admins). A re-run asked for
here is never in a protected environment, and is the person's run. Asking the
model for a proposal is an AI job (``ai.use`` and ``sentinel.read``):
``kind: sentinel_propose`` in ``routes/ai.py``.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ducta.api.dependencies import CurrentUserDep, require_permission
from ducta.api.routes.projects import ProjectServiceDep

router = APIRouter(tags=["Sentinel"])


class SentinelStatus(BaseModel):
    enabled: bool
    paused: bool
    environments: List[str]
    protected: List[str]
    pipelines: List[str]
    actions_today: int
    max_actions_per_day: int
    active: int
    escalated: int
    #: Why the project's sentinel block could not be read, when it could not.
    error: Optional[str] = None


class IncidentModel(BaseModel):
    id: str
    env: str
    pipeline: str
    kind: str
    status: str
    opened_at: str
    updated_at: str
    resolved_at: Optional[str] = None
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    runbook: str = ""
    level: str = "L0"
    reason: str = ""
    failures: int = 0
    attempts: int = 0
    last_run_id: Optional[str] = None
    pending: Optional[Dict[str, Any]] = None
    links: Dict[str, Any] = Field(default_factory=dict)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)


class IncidentAction(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


def _root(svc: Any, project_id: str) -> Path:
    return Path(svc.store(project_id).root)


def _who(user: Any) -> str:
    return str(getattr(user, "username", None) or getattr(user, "id", None) or "user")


def _incident(root: Path, incident_id: str) -> Any:
    from ducta.ai.agents.sentinel.incidents import Incidents

    found = Incidents(root).get(incident_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No incident {incident_id}"
        )
    return found


def _status(root: Path) -> SentinelStatus:
    from ducta.ai.agents.sentinel import policy as gate
    from ducta.ai.agents.sentinel.incidents import Incidents

    settings = gate.Settings.of(root)
    active = Incidents(root).list(status="active")
    if settings is None:
        return SentinelStatus(
            enabled=False,
            paused=gate.is_paused(root),
            environments=[],
            protected=[],
            pipelines=[],
            actions_today=0,
            max_actions_per_day=0,
            active=len(active),
            escalated=sum(1 for i in active if i.status == "escalated"),
            error="The project does not load; fix it to read its sentinel block",
        )
    p = settings.policy
    return SentinelStatus(
        enabled=p.enabled,
        paused=gate.is_paused(root),
        environments=list(p.environments),
        protected=list(settings.protected),
        pipelines=list(p.pipelines),
        actions_today=gate.actions_today(root),
        max_actions_per_day=p.max_actions_per_day,
        active=len(active),
        escalated=sum(1 for i in active if i.status == "escalated"),
    )


@router.get(
    "/projects/{project_id}/sentinel/status",
    response_model=SentinelStatus,
    summary="Whether Sentinel watches this project, where it may act, and how busy it is",
    dependencies=[Depends(require_permission("sentinel.read"))],
)
async def sentinel_status(project_id: str, svc: ProjectServiceDep) -> SentinelStatus:
    return await asyncio.to_thread(_status, _root(svc, project_id))


@router.get(
    "/projects/{project_id}/sentinel/incidents",
    response_model=List[IncidentModel],
    summary="The project's incidents, newest first",
    dependencies=[Depends(require_permission("sentinel.read"))],
)
async def list_incidents(
    project_id: str,
    svc: ProjectServiceDep,
    state: Optional[
        Literal["active", "open", "remediating", "escalated", "resolved", "ignored"]
    ] = Query(default=None, alias="status"),
    env: Optional[str] = None,
) -> List[IncidentModel]:
    from ducta.ai.agents.sentinel.incidents import Incidents

    root = _root(svc, project_id)
    found = await asyncio.to_thread(Incidents(root).list, status=state, env=env)
    return [IncidentModel(**i.to_dict()) for i in found]


@router.get(
    "/projects/{project_id}/sentinel/incidents/{incident_id}",
    response_model=IncidentModel,
    summary="One incident, with its timeline",
    dependencies=[Depends(require_permission("sentinel.read"))],
)
async def get_incident(project_id: str, incident_id: str, svc: ProjectServiceDep) -> IncidentModel:
    root = _root(svc, project_id)
    found = await asyncio.to_thread(_incident, root, incident_id)
    return IncidentModel(**found.to_dict())


def _close(root: Path, incident_id: str, to: str, who: str, note: str) -> IncidentModel:
    from ducta.ai.agents import audit
    from ducta.ai.agents.sentinel.incidents import Incidents
    from ducta.ai.agents.store import now

    with _locked(root):
        found = _incident(root, incident_id)
        if not found.active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Incident {incident_id} is {found.status}",
            )
        found.status = to
        found.pending = None
        if to == "resolved":
            found.resolved_at = now()
        found.note(who, to, note)
        Incidents(root).save(found)
    audit.record(
        root,
        "sentinel",
        to,
        target={"incident": found.id, "env": found.env, "pipeline": found.pipeline},
        result=to,
        reason=note,
        actor=who,
    )
    return IncidentModel(**found.to_dict())


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    """Sentinel's engine lock, waited for: a person's change never overwrites the engine's."""
    from ducta.ai.agents.sentinel.engine import LOCK_WAIT, engine_lock

    with engine_lock(root, wait=LOCK_WAIT) as got:
        if not got:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Sentinel is busy with this project; try again in a moment",
            )
        yield


@router.post(
    "/projects/{project_id}/sentinel/incidents/{incident_id}/{action}",
    response_model=IncidentModel,
    summary="Resolve, ignore or re-run an incident",
    description="A proposal (explanation and fix draft) is an AI job: "
    '`POST /api/projects/{id}/ai/jobs` with `{"kind": "sentinel_propose", "incident_id": …}`.',
    dependencies=[Depends(require_permission("sentinel.manage"))],
)
async def incident_action(
    project_id: str,
    incident_id: str,
    action: Literal["resolve", "ignore", "retry"],
    body: IncidentAction,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> IncidentModel:
    root = _root(svc, project_id)
    who = _who(current_user)
    note = (body.note or "").strip()
    if action in ("resolve", "ignore"):
        return await asyncio.to_thread(
            _close, root, incident_id, "resolved" if action == "resolve" else "ignored", who, note
        )
    user_id = str(getattr(current_user, "id", None) or who)
    return await asyncio.to_thread(_retry, root, incident_id, who, user_id, project_id)


def _retry(root: Path, incident_id: str, who: str, user_id: str, project_id: str) -> IncidentModel:
    from ducta.ai.agents import audit
    from ducta.ai.agents.sentinel import policy as gate
    from ducta.ai.agents.sentinel.actions import ServerExecutor
    from ducta.ai.agents.sentinel.incidents import Incidents
    from ducta.ai.agents.store import now

    settings = gate.Settings.of(root)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The project does not load"
        )
    with _locked(root):
        found = _incident(root, incident_id)
        if not found.active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Incident {incident_id} is {found.status}",
            )
        if found.env in settings.protected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{found.env} is protected: run it from the run page, where its permission applies",
            )
        found.attempts += 1
        found.status = "remediating"
        found.pending = {"action": "running", "since": now(), "nodes": []}
        found.note(who, "rerun", "re-run asked for by a person")
        Incidents(root).save(found)
    # Not Sentinel's own action: it does not spend the day's budget.
    audit.record(
        root,
        "sentinel",
        "manual_rerun",
        target={"incident": found.id, "env": found.env, "pipeline": found.pipeline},
        result="started",
        reason="asked for by a person",
        actor=who,
    )
    from ducta.api.execution.manager import get_execution_manager

    # Only now: a refused re-run never touches the execution manager. The run is
    # the person's — in run history, and to Sentinel when it finishes.
    ServerExecutor(get_execution_manager(), project_id, user_id=user_id).rerun(
        root, found.env, found.pipeline, [], False
    )
    return IncidentModel(**found.to_dict())


@router.post(
    "/projects/{project_id}/sentinel/{action}",
    response_model=SentinelStatus,
    summary="Pause Sentinel's actions on this project, or resume them",
    dependencies=[Depends(require_permission("sentinel.manage"))],
)
async def pause_or_resume(
    project_id: str,
    action: Literal["pause", "resume"],
    body: IncidentAction,
    svc: ProjectServiceDep,
    current_user: CurrentUserDep,
) -> SentinelStatus:
    from ducta.ai.agents.sentinel import policy as gate

    root = _root(svc, project_id)
    who = _who(current_user)
    if action == "pause":
        await asyncio.to_thread(gate.pause, root, who, (body.note or "").strip())
    else:
        await asyncio.to_thread(gate.resume, root, who)
    return await asyncio.to_thread(_status, root)
