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

Async SQLAlchemy session factory and FastAPI dependency.
"""

from __future__ import annotations

import functools
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ducta.api.db.engine import get_engine

# Module-level session factory — built on first request after engine is ready.
_session_factory: Optional[async_sessionmaker] = None


def get_session_factory() -> Optional[async_sessionmaker]:
    """Return (or create) the async session factory, None when DB is not configured."""
    global _session_factory
    engine = get_engine()
    if engine is None:
        return None
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


def require_session(default: Any = None) -> Callable:
    """Decorator for an async store method: skip persistence when no session
    factory is configured, otherwise open a session and pass it as the
    method's first argument (after ``self``).

    ``default`` is returned as-is when it's not callable, or called (with no
    arguments) to produce the fallback value otherwise — so mutable-looking
    defaults such as ``[]`` stay fresh instances via ``default=list``.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            factory = get_session_factory()
            if factory is None:
                return default() if callable(default) else default
            async with factory() as session:
                return await fn(self, session, *args, **kwargs)

        return wrapper

    return decorator


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields an ``AsyncSession``."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Database is not configured. Set DATABASE_URL to enable persistence.")
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
