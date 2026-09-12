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
from typing import Annotated, List, Optional

import msgpack  # type: ignore
from fastapi import (  # type: ignore
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool  # type: ignore
from loguru import logger  # type: ignore

from ducta.api.config import Settings, get_settings
from ducta.api.dependencies import (
    ExecutionManagerDep,
    SourcePathDep,
    WebSocketAuthError,
    authenticate_websocket,
    extract_ws_token,
    get_current_user,
    require_permission,
    resolve_websocket_user,
)
from ducta.api.exceptions import ExecutionNotFoundError, NotFoundError
from ducta.api.execution.manager import ExecutionManager
from ducta.api.execution.streaming_preview import (
    StreamingPreviewCache,
    read_streaming_data,
    read_streaming_data_external,
)
from ducta.api.models.auth import User
from ducta.api.models.execution import (
    BulkCancelRequest,
    BulkCancelResponse,
    ErrorRecoveryPlan,
    ExecutionErrorDetail,
    ExecutionErrorsResponse,
    ExecutionListResponse,
    ExecutionResponse,
    LogEntry,
    QueueStatusResponse,
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
) -> ExecutionListResponse:
    user_id = current_user.id if current_user else None
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
    # Durable read: falls back to the database and the on-disk run store, so
    # an execution older than the in-memory retention window still resolves.
    # ExecutionNotFoundError propagates to the global DuctaAPIError handler.
    return await exec_manager.load_execution(execution_id, user_id=user_id)


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
            all_logs = [
                log
                for log in all_logs
                if log.timestamp
                and datetime.fromisoformat(log.timestamp.replace("Z", "+00:00")) >= since_dt
            ]
        except (ValueError, AttributeError):
            logger.warning(f"Invalid 'since' timestamp: {since}, returning all logs")

    return all_logs


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
    """Return categorized failures (type, category, full traceback, recovery plan)
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
        plan = entry.get("recovery_plan")
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
                recovery_plan=ErrorRecoveryPlan(**plan) if plan else None,
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
    # ExecutionNotFoundError propagates to the global DuctaAPIError handler.
    try:
        return exec_manager.retry(execution_id, source_path=source_path, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


_TERMINAL_STATUSES = frozenset({"success", "failed", "cancelled"})

_STOPPED_STREAMING_STATUS = {
    "status": "stopped",
    "queries": [],
    "pipeline": None,
}


def _resolve_active_streaming(
    exec_manager: ExecutionManager, execution_id: str, user_id: Optional[str] = None
):
    """Resolve the active engine and the streaming manager's *internal* execution_id.

    Returns (engine, internal_id) when the pipeline is running.
    Returns (None, None) when the execution is in a terminal state and the engine
    has already been unregistered — callers should return a "stopped" response.
    Raises NotFoundError when the execution is active but the engine is not yet
    registered (pipeline still warming up — UI shows "waiting").
    """
    execution = exec_manager.get_execution(execution_id, user_id=user_id)
    engine = exec_manager.get_active_engine(execution_id)
    if not engine:
        exec_status = getattr(getattr(execution, "status", None), "value", None)
        if exec_status in _TERMINAL_STATUSES:
            return None, None
        logger.debug("Streaming resolution: engine not yet active for execution {}", execution_id)
        raise NotFoundError(f"Streaming engine not yet active for execution {execution_id}")

    internal_id = engine.get_active_streaming_execution_id()
    if not internal_id:
        logger.debug(
            "Streaming resolution: no active streaming pipeline for engine in execution {}",
            execution_id,
        )
        raise NotFoundError("No active streaming pipeline for this execution")
    return engine, internal_id


_EXTERNAL_STREAMING_STATUS = {
    "status": "running",
    "queries": [],
    "query_statuses": {},
    "total_queries": 0,
    "failed_queries": 0,
}


@router.get(
    "/{execution_id}/streaming/status",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_streaming_status(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    user_id = current_user.id if current_user else None
    try:
        engine, internal_id = _resolve_active_streaming(exec_manager, execution_id, user_id)
    except NotFoundError:
        # Pipeline started externally (CLI) — engine not in this process.
        # Return a partial "running" status so the UI shows "running" instead of 404.
        return {**_EXTERNAL_STREAMING_STATUS, "execution_id": execution_id}
    if engine is None:
        return {**_STOPPED_STREAMING_STATUS, "execution_id": execution_id}
    return await run_in_threadpool(engine.get_streaming_pipeline_status, internal_id)


@router.get(
    "/{execution_id}/streaming/metrics",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_streaming_metrics(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    user_id = current_user.id if current_user else None
    try:
        engine, internal_id = _resolve_active_streaming(exec_manager, execution_id, user_id)
    except NotFoundError:
        return {}
    if engine is None:
        return {}
    return await run_in_threadpool(engine.get_streaming_pipeline_metrics, internal_id)


@router.post(
    "/{execution_id}/streaming/nodes/{node_name}/restart",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def restart_streaming_node(
    execution_id: str,
    node_name: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    user_id = current_user.id if current_user else None
    try:
        engine, internal_id = _resolve_active_streaming(exec_manager, execution_id, user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if engine is None:
        raise HTTPException(status_code=409, detail="Execution is already stopped")
    success = await run_in_threadpool(engine.restart_streaming_node, internal_id, node_name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to restart node '{node_name}'")
    return {"status": "success", "message": f"Node '{node_name}' restart initiated"}


@router.delete(
    "/{execution_id}/streaming/checkpoints",
    dependencies=[Depends(require_permission("execution.write"))],
)
async def clear_streaming_checkpoints(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    user_id = current_user.id if current_user else None
    try:
        engine, internal_id = _resolve_active_streaming(exec_manager, execution_id, user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if engine is None:
        raise HTTPException(status_code=409, detail="Execution is already stopped")
    pipeline_name = engine.context.global_config.get("pipeline_name")
    if not pipeline_name:
        raise HTTPException(status_code=400, detail="Pipeline name not found in engine context")

    # The manager's clear_pipeline_checkpoints handles the actual deletion (and
    # refuses to run while queries for the pipeline are still active).
    result = await run_in_threadpool(
        engine.streaming_executor.streaming_manager.clear_pipeline_checkpoints, pipeline_name
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


_streaming_preview_cache = StreamingPreviewCache(ttl_seconds=10.0)


@router.get(
    "/{execution_id}/streaming/data",
    dependencies=[Depends(require_permission("execution.read"))],
)
async def get_streaming_data(
    execution_id: str,
    exec_manager: ExecutionManagerDep,
    source_path: SourcePathDep,
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    # Enforces ownership and validates the engine exists with a running pipeline.
    user_id = current_user.id if current_user else None
    try:
        engine, _ = _resolve_active_streaming(exec_manager, execution_id, user_id)
    except NotFoundError:
        # Pipeline started externally (CLI) — read Delta Parquet files directly.
        execution = exec_manager.get_execution(execution_id, user_id=user_id)
        cache_key = f"ext:{user_id or 'unknown'}:{execution_id}"
        return await run_in_threadpool(
            _streaming_preview_cache.get_or_compute,
            cache_key,
            lambda: read_streaming_data_external(source_path, execution),
        )
    if engine is None:
        return {}

    cache_key = f"{user_id or 'unknown'}:{execution_id}"
    return await run_in_threadpool(
        _streaming_preview_cache.get_or_compute,
        cache_key,
        lambda: read_streaming_data(engine),
    )


ws_router = APIRouter(prefix="/ws", tags=["WebSocket"])


@ws_router.websocket("/logs/{execution_id}")
async def stream_logs_ws(
    websocket: WebSocket,
    execution_id: str,
    exec_manager: ExecutionManager = Depends(_get_exec_manager_ws),
    settings: Settings = Depends(get_settings),
) -> None:
    # CORS does not apply to WebSocket handshakes, so this is the only thing
    # standing between a page on another site and this execution's log stream.
    user = await authenticate_websocket(websocket, settings, permission="execution.read")
    if user is None:
        return
    # Re-extracted (not returned by authenticate_websocket) for the periodic
    # revalidation below — same token that just passed the handshake auth.
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
