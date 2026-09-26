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

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, Optional

if TYPE_CHECKING:
    from ducta.api.config import Settings

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ducta.api import __version__
from ducta.api.config import get_settings
from ducta.api.execution.manager import get_execution_manager
from ducta.api.middleware import register_middleware
from ducta.api.routes import register_routes
from ducta.api.utils.logging import configure_logging

_UI_DIR = Path(__file__).resolve().parent.parent / "ui" / "dist"


_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})


def warn_if_insecure_exposure(settings: "Settings") -> bool:
    """Warn loudly when the API is exposed to the network without auth.

    Authentication is off by default for a smooth local-first experience, but
    running unauthenticated on a non-local bind address exposes every endpoint
    (including pipeline execution) to the network. Returns ``True`` when a
    warning was emitted so callers/tests can assert on it.

    This only catches exposure via ``settings.host`` itself. It cannot detect
    (and does not warn about) exposure introduced one layer up — e.g. a
    reverse proxy or port-forward that makes a loopback-bound server
    (``host=127.0.0.1``) reachable from the network anyway. That's outside
    this process's visibility; auth should still be enabled whenever a proxy
    sits in front of it, regardless of what this check reports.
    """
    if not settings.auth_enabled and settings.host not in _LOCAL_HOSTS:
        logger.warning(
            "SECURITY: authentication is DISABLED while binding to a non-local "
            "address (host={host}). Every endpoint — including pipeline execution "
            "— is reachable without credentials. Set AUTH_ENABLED=true and a strong "
            "JWT_SECRET_KEY, or bind to 127.0.0.1. See SECURITY.md for the "
            "production checklist.",
            host=settings.host,
        )
        return True
    return False


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    configure_logging(level=settings.log_level, fmt=settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(
            "Ducta API v{version} starting — environment={env}",
            version=__version__,
            env=settings.environment,
        )

        # ── Security posture warning ────────────────────────────────────────
        warn_if_insecure_exposure(settings)

        # ── Database persistence (optional) ─────────────────────────────────
        from ducta.api.db.engine import get_engine, is_db_enabled

        _db_engine = None
        if is_db_enabled():
            _db_engine = get_engine()
            from ducta.api.db.migrate import run_migrations

            await run_migrations(_db_engine)

            # Seed the admin user in the DB store on first startup
            from ducta.api.auth.users import get_user_store

            user_store = get_user_store()
            if hasattr(user_store, "seed_from_env"):
                # The DB store's seed is async; the in-memory fallback's is sync.
                import inspect

                result = user_store.seed_from_env()
                if inspect.isawaitable(result):
                    await result

            logger.info(
                "Persistence enabled — driver={driver}",
                driver=_db_engine.url.drivername,
            )
        else:
            logger.info("Persistence disabled — running in in-memory mode")
        # ────────────────────────────────────────────────────────────────────

        # ExecutionManager is in-memory; DB persistence is layered transparently.
        exec_manager = get_execution_manager()
        app.state.execution_manager = exec_manager
        exec_manager.startup()

        # ── Pipeline scheduler ───────────────────────────────────────────────
        from ducta.api.execution.scheduler import get_cron_scheduler

        cron_scheduler = get_cron_scheduler()
        await cron_scheduler.start(exec_manager)
        # ─────────────────────────────────────────────────────────────────────

        yield

        await cron_scheduler.stop()
        exec_manager.shutdown()

        if _db_engine is not None:
            await _db_engine.dispose()
            logger.info("Database engine disposed")

        logger.info("Ducta API shutting down…")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Ducta API — REST interface for managing Ducta pipeline configs, "
            "execution, and git history. Source paths are provided per-request."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        debug=settings.debug,
        lifespan=lifespan,
    )

    register_middleware(app)

    register_routes(app)

    if _UI_DIR.is_dir():
        logger.info("Serving UI from {path}", path=_UI_DIR)
        app.mount("/assets", StaticFiles(directory=_UI_DIR / "assets"), name="ui-assets")

        _ui_root = _UI_DIR.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa_fallback(full_path: str):
            # An unknown API path is an API error, not a page: answering it with
            # index.html (200, text/html) hid typos and removed endpoints.
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail=f"Not Found: /{full_path}")
            # Resolve and confirm the target stays within the UI dist directory
            # before serving it; otherwise fall back to the SPA entrypoint.
            candidate = (_ui_root / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(_ui_root):
                return FileResponse(candidate)
            return FileResponse(_ui_root / "index.html")

    return app


_app: Optional[FastAPI] = None


def __getattr__(name: str) -> Any:
    """Build the ASGI app on first attribute access, not at import time.

    ``uvicorn ducta.api.main:app`` resolves the app with ``getattr``, so this keeps
    that entry point working while making a bare ``import ducta.api.main`` free of
    side effects. It has to be lazy: ``create_app`` calls ``configure_logging``,
    which does ``logger.remove()`` and installs a JSON stdout sink — so an eager
    ``app = create_app()`` silently tore down the logging config of *any* process
    that imported anything under ``ducta.api``, which is how the CLI ended up
    printing serialized JSON over its own Rich output.
    """
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "ducta.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload or settings.debug,
        workers=1 if (settings.reload or settings.debug) else settings.workers,
        log_level=settings.log_level.lower(),
    )
