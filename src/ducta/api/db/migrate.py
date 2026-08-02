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

import threading
from pathlib import Path

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine

_migration_lock = threading.Lock()
_migrations_run = False


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply any pending Alembic migrations against *engine* synchronously.

    Alembic's standard runner is synchronous; we execute it via
    ``run_sync`` on an AsyncConnection so the event loop is not blocked
    for real workloads (the migration itself is fast on startup).
    """
    global _migrations_run

    if _migrations_run:
        return

    with _migration_lock:
        if _migrations_run:
            return

        try:
            # Import here so Alembic is optional unless DB is active
            from alembic.config import Config  # type: ignore

            alembic_ini = Path(__file__).resolve().parents[4] / "alembic.ini"
            if not alembic_ini.exists():
                logger.warning(
                    "alembic.ini not found at {path} — skipping auto-migrate",
                    path=alembic_ini,
                )
                return

            alembic_cfg = Config(str(alembic_ini))
            # Set absolute path to migrations directory (fixes path resolution when run from different cwd)
            migrations_dir = alembic_ini.parent / "src" / "ducta" / "api" / "db" / "migrations"
            alembic_cfg.set_main_option("script_location", str(migrations_dir))

            # Override the URL so Alembic always uses the live engine URL
            async with engine.begin() as conn:
                await conn.run_sync(_apply_migrations, alembic_cfg, str(engine.url))

            logger.info("Database migrations applied successfully")
            _migrations_run = True

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to apply database migrations: {exc}", exc=exc)
            raise


def _apply_migrations(connection, alembic_cfg, url: str) -> None:
    """Synchronous helper executed inside ``run_sync``."""
    alembic_cfg.attributes["connection"] = connection
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    from alembic import command  # type: ignore

    command.upgrade(alembic_cfg, "head")
