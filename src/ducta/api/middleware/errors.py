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

# Every global exception handler, in one place. Routes raise; this module
# decides the status code and the body. Every error body has the same shape —
# {"error", "message", "request_id", ...} — so a client (and a log search)
# never has to special-case which handler answered.
from typing import Any, Dict, Tuple, Type

from fastapi import FastAPI, HTTPException, Request  # type: ignore
from fastapi.encoders import jsonable_encoder  # type: ignore
from fastapi.exceptions import RequestValidationError  # type: ignore
from fastapi.responses import JSONResponse  # type: ignore
from loguru import logger  # type: ignore

from ducta.api.core.git_sync import GitSyncError
from ducta.api.exceptions import DuctaAPIError
from ducta.api.models.responses import ErrorCode
from ducta.core.errors import DuctaError as EngineError
from ducta.mlrun import exceptions as mlops_exc

# MLOps errors → HTTP status. Anything not listed is a server fault (500) and
# its message is not echoed back to the client.
_MLOPS_STATUS: Tuple[Tuple[Tuple[Type[Exception], ...], int], ...] = (
    (
        (
            mlops_exc.ModelNotFoundError,
            mlops_exc.ExperimentNotFoundError,
            mlops_exc.RunNotFoundError,
            mlops_exc.ArtifactNotFoundError,
        ),
        404,
    ),
    (
        (
            mlops_exc.ModelVersionConflictError,
            mlops_exc.ConcurrencyError,
            mlops_exc.RunNotActiveError,
        ),
        409,
    ),
    (
        (
            mlops_exc.PromotionGateError,
            mlops_exc.ProtectedVersionError,
            mlops_exc.InvalidMetricError,
            mlops_exc.InvalidParameterError,
            mlops_exc.ArtifactValidationError,
            mlops_exc.SchemaValidationError,
            mlops_exc.RunLimitExceededError,
            mlops_exc.ConfigurationError,
        ),
        400,
    ),
)


def _mlops_status(exc: mlops_exc.MLOpsException) -> int:
    for types, status in _MLOPS_STATUS:
        if isinstance(exc, types):
            return status
    return 500


def _respond(request: Request, status_code: int, body: Dict[str, Any]) -> JSONResponse:
    body["request_id"] = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=status_code, content=body)


def _internal_error(request: Request, exc: Exception) -> JSONResponse:
    logger.bind(request_id=getattr(request.state, "request_id", None), path=request.url.path).opt(
        exception=exc
    ).error("Unhandled exception: {exc}", exc=exc)
    return _respond(
        request, 500, {"error": "INTERNAL_ERROR", "message": "An unexpected error occurred."}
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every global exception handler to *app*."""

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        return _respond(
            request, exc.status_code, {"error": "HTTP_ERROR", "message": str(exc.detail)}
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _respond(
            request,
            422,
            {
                "error": "VALIDATION_ERROR",
                "message": "Request validation failed",
                # Pydantic puts the validator's own exception object in
                # `ctx`; left as-is it is not JSON-serializable and turned
                # every custom-validator 422 into a 500.
                "detail": jsonable_encoder(exc.errors(), custom_encoder={Exception: str}),
            },
        )

    @app.exception_handler(DuctaAPIError)
    async def _ducta(request: Request, exc: DuctaAPIError) -> JSONResponse:
        logger.bind(
            request_id=getattr(request.state, "request_id", None),
            error_code=exc.error_code,
            path=request.url.path,
        ).warning("DuctaAPIError: {message}", message=exc.message)
        return _respond(request, exc.status_code, exc.to_dict())

    # Engine errors (`ducta.core`) are not DuctaAPIError subclasses, but each
    # already declares the HTTP status its kind of failure deserves (404 for an
    # unknown pipeline, 400 for bad config, 422 for data that failed its checks).
    @app.exception_handler(EngineError)
    async def _engine(request: Request, exc: EngineError) -> JSONResponse:
        logger.bind(
            request_id=getattr(request.state, "request_id", None),
            error=type(exc).__name__,
            path=request.url.path,
        ).warning("Engine error: {message}", message=exc.message)
        return _respond(request, exc.http_status, exc.to_dict())

    @app.exception_handler(mlops_exc.MLOpsException)
    async def _mlops(request: Request, exc: mlops_exc.MLOpsException) -> JSONResponse:
        status = _mlops_status(exc)
        if status == 500:
            return _internal_error(request, exc)
        return _respond(request, status, {"error": exc.error_code.value, "message": exc.message})

    @app.exception_handler(GitSyncError)
    async def _git_sync(request: Request, exc: GitSyncError) -> JSONResponse:
        return _respond(
            request,
            400,
            {"error": ErrorCode.GIT_ERROR.value, "message": f"Git operation failed: {exc}"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return _internal_error(request, exc)
