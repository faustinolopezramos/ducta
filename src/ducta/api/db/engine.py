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

SQLAlchemy async engine — singleton; None when DATABASE_URL is not configured.
"""

from __future__ import annotations

import threading
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ducta.api.config import get_settings

_engine: Optional[AsyncEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> Optional[AsyncEngine]:
    """Return the application-wide async engine, or ``None`` if DB is disabled."""
    global _engine
    if _engine is not None:
        return _engine

    with _engine_lock:
        if _engine is not None:
            return _engine

        settings = get_settings()
        database_url = settings.database_url.strip()

        if not database_url:
            return None

        # --- SQLite specific options ---
        connect_args: dict = {}
        engine_kwargs: dict = {}

        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            engine_kwargs["pool_pre_ping"] = False
            # sqlite doesn't support connection pool sizing — no pool_size kwarg set
        else:
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 10
            engine_kwargs["pool_timeout"] = 30
            engine_kwargs["pool_recycle"] = 1800  # 30 min — avoids stale PG connections

        _engine = create_async_engine(
            database_url,
            echo=settings.debug,
            connect_args=connect_args,
            **engine_kwargs,
        )
        logger.info(
            "Database engine initialised — url={driver}",
            driver=_engine.url.drivername,
        )
        return _engine


def is_db_enabled() -> bool:
    """Return True when DATABASE_URL is configured (non-empty)."""
    return bool(get_settings().database_url.strip())
