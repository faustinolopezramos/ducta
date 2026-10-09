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
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

import msgpack  # type: ignore
from fastapi import (  # type: ignore
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool
from loguru import logger  # type: ignore

from ducta.api.config import Settings, get_settings
from ducta.api.dependencies import (
    ExecutionManagerDep,
    OptionalSourcePathDep,
    SourcePathDep,
    WebSocketAuthError,
    WorkspaceManagerDep,
    authenticate_websocket,
    extract_ws_token,
    get_current_user,
    require_permission,
    resolve_websocket_user,
)
from ducta.api.exceptions import ExecutionNotFoundError, http_error_on
from ducta.api.execution.manager import ExecutionManager
from ducta.api.models.auth import User
from ducta.api.models.execution import (
    BulkCancelRequest,
    BulkCancelResponse,
    ExecutionErrorDetail,
    ExecutionErrorsResponse,
    ExecutionListResponse,
    ExecutionResponse,
    LogEntry,
    QueueStatusResponse,
    StreamingStatusResponse,
)

_WS_HEARTBEAT_INTERVAL = 30
_WS_TOKEN_REVALIDATION_INTERVAL = 60  # Reduced from 300s for better security
_WS_INACTIVITY_TIMEOUT = 600


def _get_exec_manager_ws(websocket: WebSocket) -> ExecutionManager:
    return websocket.app.state.execution_manager


router = APIRouter(prefix="/executions", tags=["Execution"])


@router.get(
    "/queue",
    response_model=QueueStatusResponse,
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_queue_status(exec_manager: ExecutionManagerDep) -> QueueStatusResponse:
    """Return current execution queue depth and concurrency stats."""
    stats = exec_manager.queue_status()
    return QueueStatusResponse(
        running=stats["active"],
        queued=stats["queued"],
        max_concurrent=stats["capacity"],
        total_queued=stats["total_queued"],
        total_completed=stats["total_completed"],
    )


@router.get(
    "",
    response_model=ExecutionListResponse,
    dependencies=[Depends(require_permission("execution.read"))],
)
async def list_executions(
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    skip: int = 0,
    limit: int = 50,
    pipeline_name: Optional[str] = None,
    node_name: Optional[str] = None,
    status: Optional[str] = None,
    env: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    sweep_id: Optional[str] = None,
    project_id: Optional[str] = None,
    q: Optional[str] = None,
    workspace: OptionalSourcePathDep = None,
) -> ExecutionListResponse:
    user_id = current_user.id if current_user else None
    # Only this workspace's runs: the run store is shared, and project ids repeat
    # across workspaces (a copy of a project lists as the same project).
    executions, total = exec_manager.list_executions_paginated(
        skip=skip,
        limit=limit,
        user_id=user_id,
        pipeline_name=pipeline_name,
        node_name=node_name,
        status=status,
        env=env,
        since=since,
        until=until,
        sweep_id=sweep_id,
        project_id=project_id,
        q=q,
        workspace=workspace,
    )
    return ExecutionListResponse(
        executions=executions, count=len(executions), total=total, skip=skip, limit=limit
    )


@router.get(
    "/{execution_id}",
    response_model=ExecutionResponse,
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_execution(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> ExecutionResponse:
    user_id = current_user.id if current_user else None

    return await exec_manager.load_execution(execution_id, user_id=user_id)


@router.get(
    "/{execution_id}/streaming",
    response_model=StreamingStatusResponse,
    dependencies=[Depends(require_permission("execution.read"))],
    summary="The live state of an execution's streaming queries",
    description=(
        "For a streaming or hybrid execution that is still running: per pipeline, its "
        "queries' state, each node's latest batch throughput and the model it scores "
        "with. `active` is false once the execution holds no running engine."
    ),
)
async def get_execution_streaming_status(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> StreamingStatusResponse:
    from ducta.api.services.streaming_status import streaming_status

    user_id = current_user.id if current_user else None
    await exec_manager.load_execution(execution_id, user_id=user_id)  # 404 / ownership
    engine = exec_manager.get_active_engine(execution_id)
    return await run_in_threadpool(streaming_status, execution_id, engine)


@router.get(
    "/{execution_id}/logs",
    response_model=List[LogEntry],
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_execution_logs(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    since: Optional[str] = None,
) -> List[LogEntry]:
    """Get execution logs, optionally filtered since a timestamp (ISO format)."""
    user_id = current_user.id if current_user else None
    # ExecutionNotFoundError from load_logs propagates to the global DuctaAPIError handler.
    all_logs = await exec_manager.load_logs(execution_id, user_id=user_id)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
            all_logs = [log for log in all_logs if log.timestamp and log.timestamp >= since_dt]
        except (ValueError, AttributeError, TypeError):
            logger.warning(f"Invalid 'since' timestamp: {since}, returning all logs")

    return all_logs


@router.get(
    "/{execution_id}/diagnosis",
    summary="Why a run failed: what kind of failure, where, and what changed since the last good run",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_execution_diagnosis(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    manager: WorkspaceManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> dict:
    from ducta.api.services.diagnosis import diagnose
    from ducta.api.services.run_certificates import candidate_runs_dirs, latest_successful
    from ducta.core.certificate import find_certificate_dir, load_certificate

    user_id = current_user.id if current_user else None
    # Memory first, then the persisted run: a diagnosis must survive a restart.
    record = await exec_manager.load_execution(execution_id, user_id=user_id)
    from ducta.api.execution.error_recovery import load_error_log_summary

    summary = load_error_log_summary(execution_id) or {}
    errors = []
    for entry in summary.get("errors", []):
        error = entry.get("error") or {}
        errors.append(
            {
                "node_id": entry.get("node_id"),
                "error_type": error.get("type"),
                "message": error.get("message"),
                "traceback": error.get("traceback"),
                "hint": entry.get("hint"),
            }
        )

    def compute() -> dict:
        project_root = None
        certificate = None
        last_ok = None
        if record.project_id:
            project_root = manager.for_project(record.project_id).root
            if record.certificate_run_id:
                for _env, runs_dir in candidate_runs_dirs(project_root, record.env):
                    run_dir = find_certificate_dir(runs_dir, record.certificate_run_id)
                    if run_dir is not None:
                        certificate = load_certificate(run_dir / "certificate.json")
                        break
            ok = latest_successful(project_root, record.env).get(record.pipeline_name)
            # The last good run before this one, not this one (a later success is no baseline).
            if ok and (
                not certificate
                or (ok.get("started_at") or "") < (certificate.get("started_at") or "")
            ):
                last_ok = ok
        return diagnose(record.model_dump(mode="json"), errors, project_root, certificate, last_ok)

    return await run_in_threadpool(compute)


@router.get(
    "/{execution_id}/errors",
    response_model=ExecutionErrorsResponse,
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_execution_errors(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> ExecutionErrorsResponse:
    """Return categorized failures (type, category, full traceback, hint)
    for a finished execution. Empty result when the run recorded no errors."""
    user_id = current_user.id if current_user else None
    # ExecutionNotFoundError propagates to the global DuctaAPIError handler.
    summary = exec_manager.get_execution_errors(execution_id, user_id=user_id)
    if summary is None:
        return ExecutionErrorsResponse(
            execution_id=execution_id,
            error_count=0,
            warning_count=0,
            has_critical_errors=False,
        )
    errors: List[ExecutionErrorDetail] = []
    for entry in summary.get("errors", []):
        error = entry.get("error") or {}
        # Logs written before `hint` existed carry a `recovery_plan` whose
        # `notes` held the same guidance.
        hint = entry.get("hint") or (entry.get("recovery_plan") or {}).get("notes")
        errors.append(
            ExecutionErrorDetail(
                timestamp=entry.get("timestamp", ""),
                node_id=entry.get("node_id"),
                node_type=entry.get("node_type"),
                attempt=entry.get("attempt", 1),
                error_type=error.get("type", "Exception"),
                message=error.get("message", ""),
                category=error.get("category", "unknown"),
                traceback=error.get("traceback", ""),
                traceback_lines=error.get("traceback_lines", []),
                hint=hint,
            )
        )
    return ExecutionErrorsResponse(
        execution_id=execution_id,
        error_count=summary.get("error_count", len(errors)),
        warning_count=summary.get("warning_count", 0),
        has_critical_errors=summary.get("has_critical_errors", False),
        errors=errors,
        warnings=summary.get("warnings", []),
    )


@router.post(
    "/{execution_id}/cancel",
    response_model=ExecutionResponse,
    dependencies=[Depends(require_permission("execution.write"))],
)
async def cancel_execution(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> ExecutionResponse:
    user_id = current_user.id if current_user else None
    # ExecutionNotFoundError propagates to the global DuctaAPIError handler.
    exec_manager.cancel_execution(execution_id, user_id=user_id)
    return exec_manager.get_execution(execution_id, user_id=user_id)


@router.post(
    "/bulk-cancel",
    response_model=BulkCancelResponse,
    dependencies=[Depends(require_permission("execution.write"))],
)
async def bulk_cancel_executions(
    body: BulkCancelRequest,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> BulkCancelResponse:
    """Cancel many executions at once. Non-cancellable/unknown IDs are skipped."""
    user_id = current_user.id if current_user else None
    cancelled: List[str] = []
    skipped: List[str] = []
    for execution_id in body.execution_ids:
        try:
            if exec_manager.cancel_execution(execution_id, user_id=user_id):
                cancelled.append(execution_id)
            else:
                skipped.append(execution_id)
        except ExecutionNotFoundError:
            skipped.append(execution_id)
    return BulkCancelResponse(cancelled=cancelled, skipped=skipped)


@router.post(
    "/{execution_id}/resume",
    summary="Resume a run paused at a data breakpoint",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def resume_execution(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> Dict[str, Any]:
    if not exec_manager.resume(execution_id):
        raise HTTPException(status_code=409, detail="The run is not paused at a breakpoint")
    return {"resumed": execution_id}


@router.post(
    "/{execution_id}/retry",
    response_model=ExecutionResponse,
    status_code=202,
    dependencies=[Depends(require_permission("execution.write"))],
)
async def retry_execution(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    source_path: SourcePathDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> ExecutionResponse:
    """Clone a terminal execution and re-enqueue it with the same parameters."""
    user_id = current_user.id if current_user else None
    if current_user is not None:
        from ducta.api.services.governance import check_can_run
        from ducta.api.workspace.manager import WorkspaceManager

        original = exec_manager.get_execution(execution_id)
        root = None
        if original.project_id:
            try:
                root = WorkspaceManager(source_path).for_project(original.project_id).root
            except Exception:  # noqa: BLE001 — unknown project: the default protected names apply
                root = None
        check_can_run(current_user, original.env, root)
    # ExecutionNotFoundError propagates to the global DuctaAPIError handler.
    with http_error_on(400):
        return exec_manager.retry(execution_id, source_path=source_path, user_id=user_id)


_TERMINAL_STATUSES = frozenset({"success", "failed", "cancelled"})

ws_router = APIRouter(prefix="/ws", tags=["WebSocket"])


@ws_router.websocket("/logs/{execution_id}")
async def stream_logs_ws(
    websocket: WebSocket,
    execution_id: str,
    exec_manager: ExecutionManager = Depends(_get_exec_manager_ws),
    settings: Settings = Depends(get_settings),
) -> None:
    user = await authenticate_websocket(websocket, settings, permission="execution.read")
    if user is None:
        return

    token = extract_ws_token(websocket)

    await websocket.accept()
    logger.info("WebSocket connected for execution {id}", id=execution_id)

    token_validated_at = datetime.now(tz=timezone.utc)
    last_activity = datetime.now(tz=timezone.utc)

    async def heartbeat_and_validate():
        nonlocal token_validated_at, last_activity
        while True:
            try:
                await asyncio.sleep(_WS_HEARTBEAT_INTERVAL)
                now = datetime.now(tz=timezone.utc)
                if (now - last_activity).total_seconds() > _WS_INACTIVITY_TIMEOUT:
                    await websocket.close(code=1000, reason="Inactivity timeout")
                    return
                try:
                    await websocket.send_json({"type": "heartbeat", "timestamp": now.isoformat()})

                    last_activity = now
                except Exception as exc:
                    logger.debug(
                        "WebSocket heartbeat send failed (socket likely closed): {exc}", exc=exc
                    )
                    return

                if (now - token_validated_at).total_seconds() > _WS_TOKEN_REVALIDATION_INTERVAL:
                    try:
                        revalidated_user = await resolve_websocket_user(settings, token)
                        if settings.auth_enabled and not revalidated_user.has_permission(
                            "execution.read"
                        ):
                            await websocket.close(
                                code=1008, reason="Token invalid or permissions revoked"
                            )
                            return
                        token_validated_at = now
                    except WebSocketAuthError as e:
                        await websocket.close(code=e.code, reason=e.reason)
                        return
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("WebSocket heartbeat loop exiting unexpectedly: {exc}", exc=exc)
                return

    hb_task = asyncio.create_task(heartbeat_and_validate())

    use_msgpack = websocket.query_params.get("format") == "msgpack"

    try:
        async for batch in exec_manager.stream_logs(execution_id, user_id=user.id):
            try:
                last_activity = datetime.now(tz=timezone.utc)
                data = [entry.as_serialized_dict() for entry in batch]
                if use_msgpack:
                    await websocket.send_bytes(msgpack.packb(data, use_bin_type=True))
                else:
                    await websocket.send_json(data)
            except Exception:
                break

        await websocket.close(code=1000, reason="Stream completed")

    except ExecutionNotFoundError as exc:
        try:
            await websocket.close(code=1008, reason=f"Execution not found: {exc.message}")
        except Exception:
            pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("WebSocket error for execution {id}: {exc}", id=execution_id, exc=exc)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass
