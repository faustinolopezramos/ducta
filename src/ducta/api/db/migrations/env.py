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

Alembic environment configuration for Ducta API.

This file is executed by Alembic on every ``alembic`` CLI invocation AND
by the programmatic runner in ``ducta.api.db.migrate``.

Supports both:
  - Online (connected) mode: used in production startup auto-migration.
  - Offline mode: ``alembic upgrade head --sql`` for SQL preview.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

# Make sure all ORM models are imported so their tables are registered on
# Base.metadata before Alembic inspects them.
import ducta.api.db.models  # noqa: F401

# Import the project's declarative base so Alembic can auto-detect schema changes
from ducta.api.db.base import Base

config = context.config

# Attach alembic.ini logging config (only when a config file is present)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

logger = logging.getLogger("alembic.env")


def _get_url() -> str:
    """Return the database URL from Settings or the alembic.ini value.

    When called from the programmatic runner (``migrate.py``), the URL is
    injected via ``alembic_cfg.set_main_option("sqlalchemy.url", ...)``.
    """
    url = config.get_main_option("sqlalchemy.url", "")
    if not url:
        # Fallback: read from application settings (useful for CLI usage)
        try:
            from ducta.api.config import get_settings

            url = get_settings().database_url
        except Exception:
            pass
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Useful for generating SQL scripts without a live DB connection::

        alembic upgrade head --sql
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection.

    When invoked programmatically from ``migrate.py``, the connection is
    injected via ``config.attributes["connection"]``.
    """
    # Programmatic path: connection already provided
    connectable = config.attributes.get("connection", None)

    if connectable is not None:
        # Called from the async runner via conn.run_sync(_apply_migrations, ...)
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    # CLI path: create a synchronous connection from the URL
    from sqlalchemy import create_engine

    url = _get_url()
    # For async URLs (aiosqlite, asyncpg) swap to sync driver for CLI usage
    sync_url = url.replace("sqlite+aiosqlite", "sqlite").replace(
        "postgresql+asyncpg", "postgresql+psycopg2"
    )

    engine = create_engine(sync_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
