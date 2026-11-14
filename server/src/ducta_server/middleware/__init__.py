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
from typing import cast

from fastapi import FastAPI, Request, Response  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from loguru import logger  # type: ignore

from ducta_server.config import get_settings
from ducta_server.middleware.audit import maybe_write_audit
from ducta_server.middleware.errors import register_exception_handlers
from ducta_server.middleware.origin import RequestGuardMiddleware
from ducta_server.middleware.rate_limit import RateLimitMiddleware

__all__ = ["register_middleware", "RateLimitMiddleware"]


def content_security_policy(is_production: bool) -> str:
    """The CSP sent with every response.

    Everything the UI loads is same-origin (the SPA, its typefaces under /fonts,
    Monaco through ``loader.config``, never its CDN). Two grants are not
    "self": ``'wasm-unsafe-eval'`` lets the ruff formatter compile its
    WebAssembly — and nothing else, unlike ``'unsafe-eval'`` — and ``blob:``
    workers are how Monaco and monaco-yaml start theirs. Styles keep
    ``'unsafe-inline'`` for React's style attributes; scripts never get it.
    """
    framing = "'none'" if is_production else "'self'"
    return (
        "default-src 'self'; "
        "script-src 'self' 'wasm-unsafe-eval'; "
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' ws: wss:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        f"frame-ancestors {framing}"
    )


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

    # Host + Origin guard. Added after CORS, so it runs first: a request for a
    # foreign Host (DNS rebinding) or a state change from a foreign Origin never
    # reaches a route. Preflights (OPTIONS) are not state changes and pass.
    app.add_middleware(RequestGuardMiddleware)

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

    # Security Headers. The packaged SPA is served by this app, so one policy fits
    # every environment; only framing differs. The local policy used to be
    # `default-src * 'unsafe-inline' 'unsafe-eval'` — exactly what `ducta ui` users
    # got, on the one server that can run code.
    _csp = content_security_policy(is_production)
    _frame_options = "DENY" if is_production else "SAMEORIGIN"

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = _frame_options
        if is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return cast(Response, response)

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

    register_exception_handlers(app)
