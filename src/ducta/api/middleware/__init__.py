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

import time
import uuid

from fastapi import FastAPI, Request, Response  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.responses import JSONResponse  # type: ignore
from loguru import logger  # type: ignore

from ducta.api.config import get_settings
from ducta.api.exceptions import DuctaAPIError
from ducta.api.middleware.audit import maybe_write_audit
from ducta.api.middleware.rate_limit import RateLimitMiddleware

__all__ = ["register_middleware", "RateLimitMiddleware"]


def register_middleware(app: FastAPI) -> None:
    """Attach all middleware and exception handlers to the FastAPI app."""
    settings = get_settings()
    is_production = settings.is_production()

    allow_origins = settings.cors_origins
    allow_credentials = settings.cors_allow_credentials
    # Wildcard origin + credentials lets Starlette reflect ANY Origin back with
    # Access-Control-Allow-Credentials: true. Development is NOT an exemption: that
    # combination is precisely what turns a loopback-bound, unauthenticated dev
    # server into a drive-by target, because any page the developer visits can then
    # read the response to a cross-origin request against 127.0.0.1 — enumerate the
    # workspace, write files into it, and launch a pipeline that runs them.
    # Downgrade unconditionally, in every environment.
    if allow_credentials and "*" in allow_origins:
        logger.warning(
            "CORS: refusing wildcard origin with credentials — disabling credentials. "
            "Set CORS_ORIGINS to an explicit allow-list to keep them enabled."
        )
        allow_credentials = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # Rate Limiting
    if settings.rate_limit_enabled and settings.workers > 1 and not settings.rate_limit_redis_url:
        logger.warning(
            "Rate limiting is enabled with {workers} workers but RATE_LIMIT_REDIS_URL is "
            "not set: each worker enforces its own in-memory limit, so the effective "
            "limit is ~{workers}x the configured value. Set RATE_LIMIT_REDIS_URL to share "
            "the limit across workers.",
            workers=settings.workers,
        )

    app.add_middleware(
        RateLimitMiddleware,
        max_requests_per_minute=settings.rate_limit_requests or 100,
        window_seconds=settings.rate_limit_window_seconds,
        max_keys=settings.rate_limit_max_keys,
        cleanup_interval_seconds=settings.rate_limit_cleanup_interval_seconds,
        enabled=settings.rate_limit_enabled,
        redis_url=settings.rate_limit_redis_url,
    )

    # Security Headers — strict in production, relaxed for local development.
    if is_production:
        # Restrict scripts/styles to same-origin (the SPA is served from the API
        # itself). 'unsafe-inline' for styles keeps inline style attributes working;
        # scripts stay locked down to mitigate XSS-driven token theft.
        _csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'"
        )
        _frame_options = "DENY"
    else:
        _csp = "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;"
        _frame_options = "SAMEORIGIN"

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = _frame_options
        if is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # Request ID + structured logging
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        logger.bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        ).info("-> {method} {path}", method=request.method, path=request.url.path)

        response: Response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.bind(
            request_id=request_id,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        ).info(
            "<- {status_code} {method} {path} ({duration_ms:.1f}ms)",
            status_code=response.status_code,
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id

        # Audit trail — delegated to audit.py (SRP)
        await maybe_write_audit(request, response, settings, request_id)

        return response

    # DuctaAPIError handler
    @app.exception_handler(DuctaAPIError)
    async def ducta_exception_handler(request: Request, exc: DuctaAPIError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.bind(
            request_id=request_id,
            error_code=exc.error_code,
            path=request.url.path,
        ).warning("DuctaAPIError: {message}", message=exc.message)

        body = exc.to_dict()
        if request_id:
            body["request_id"] = request_id

        return JSONResponse(status_code=exc.status_code, content=body)

    # Generic unhandled exception handler
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.bind(request_id=request_id, path=request.url.path).exception(
            "Unhandled exception: {exc}", exc=exc
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            },
        )
