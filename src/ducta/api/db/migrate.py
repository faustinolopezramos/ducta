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

            # Configured in code, not from an alembic.ini: none ships with the
            # package (or exists in the repo), so a missing file used to skip
            # migrating — and a fresh database then failed on its first query
            # ("no such table: users"). The migrations sit next to this module
            # in a source checkout and in an installed wheel alike.
            alembic_cfg = Config()
            alembic_cfg.set_main_option(
                "script_location", str(Path(__file__).resolve().parent / "migrations")
            )

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

    if _unversioned_but_current(connection):
        # Created while migrations were being skipped: the tables are already
        # at head, only the version row is missing. Upgrading would re-create them.
        logger.info("Database has the current schema but no version — stamping it at head")
        command.stamp(alembic_cfg, "head")
        return
    command.upgrade(alembic_cfg, "head")


def _unversioned_but_current(connection) -> bool:
    """Whether the database has every ORM table and column but no ``alembic_version``.

    A database that has some tables but not all of their columns is neither
    fresh nor current; it is left to ``upgrade`` to fail loudly rather than
    stamped as something it is not.
    """
    from sqlalchemy import inspect

    import ducta.api.db.models  # noqa: F401 — registers the tables on Base.metadata
    from ducta.api.db.base import Base

    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    if "alembic_version" in existing or not existing & set(Base.metadata.tables):
        return False
    for name, table in Base.metadata.tables.items():
        if name not in existing:
            return False
        have = {col["name"] for col in inspector.get_columns(name)}
        if not {col.name for col in table.columns} <= have:
            return False
    return True
