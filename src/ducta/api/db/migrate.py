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
    from alembic.runtime.migration import MigrationContext  # type: ignore
    from alembic.script import ScriptDirectory  # type: ignore

    current = MigrationContext.configure(connection).get_current_revision()
    script = ScriptDirectory.from_config(alembic_cfg)
    head = script.get_current_head()
    if current is not None and current not in {rev.revision for rev in script.walk_revisions()}:
        # A newer Ducta migrated it: Alembic alone says "Can't locate revision".
        raise RuntimeError(
            f"The database {url} was migrated by a newer Ducta (migration {current}); "
            f"this Ducta knows migrations up to {head}. Upgrade Ducta "
            "(pip install -U ducta) or point it at another database."
        )
    if current is not None and current != head:
        _back_up_before_migrating(url, current)
    command.upgrade(alembic_cfg, "head")


def _back_up_before_migrating(url: str, current: str) -> None:
    """Copy a SQLite file before a migration changes it: there is no way back."""
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    database = parsed.database or ""
    if not parsed.get_backend_name().startswith("sqlite") or database in ("", ":memory:"):
        logger.warning(
            "Migrating the database {} from {}: back it up first, a migration cannot be undone",
            url,
            current,
        )
        return
    import sqlite3

    backup = Path(f"{database}.bak-{current}")
    # sqlite3's backup API copies a consistent snapshot, WAL included.
    with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    logger.info("Database backed up to {} before migrating it from {}", backup, current)
