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

import os
import threading
from typing import Optional

from loguru import logger
from sqlalchemy import select

from ducta.api.auth.service import AuthService, get_auth_service
from ducta.api.config import get_settings
from ducta.api.db.models import UserRow
from ducta.api.db.session import get_session_factory
from ducta.api.models.auth import User

_DUMMY_HASH_LOCK = threading.Lock()
_dummy_hash: Optional[str] = None


def _get_dummy_hash() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        with _DUMMY_HASH_LOCK:
            if _dummy_hash is None:
                _dummy_hash = get_auth_service().hash_password("__dummy__")
    return _dummy_hash


def _row_to_user(row: UserRow) -> User:
    return User(
        id=row.id,
        username=row.username,
        email=row.email,
        roles=row.roles,
        is_active=row.is_active,
    )


class DatabaseUserStore:
    """Async user store backed by SQLAlchemy (SQLite or PostgreSQL)."""

    def __init__(self, auth_service: AuthService) -> None:
        self._svc = auth_service

    # ------------------------------------------------------------------ seed

    async def seed_from_env(self) -> None:
        """Create or update the admin user from environment variables.

        Idempotent: safe to call on every startup.
        """
        settings = get_settings()
        admin_password = os.environ.get("DUCTA_ADMIN_PASSWORD")

        if settings.is_production():
            if not admin_password:
                raise RuntimeError(
                    "DUCTA_ADMIN_PASSWORD must be set in production when auth is enabled."
                )
            if admin_password == "admin":
                raise RuntimeError(
                    "DUCTA_ADMIN_PASSWORD cannot use insecure default value in production."
                )

        # Only an explicitly-set env var represents intentional rotation of the
        # admin password. If it's unset, don't clobber a password that may have
        # been changed some other way (e.g. directly in the DB) on every restart.
        explicit_password = bool(admin_password)
        if not admin_password:
            admin_password = "admin"

        hashed = self._svc.hash_password(admin_password)
        await self._upsert_user(
            id="admin",
            username="admin",
            email="admin@ducta.local",
            password_hash=hashed,
            roles=["admin"],
            update_password=explicit_password,
        )
        logger.debug("Admin user seeded in database")

    async def _upsert_user(
        self,
        id: str,
        username: str,
        email: str,
        password_hash: str,
        roles: list[str],
        update_password: bool = True,
    ) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            row = await session.get(UserRow, id)
            if row is None:
                row = UserRow(
                    id=id,
                    username=username,
                    email=email,
                    password_hash=password_hash,
                )
                row.roles = roles
                session.add(row)
            else:
                # Only rotate the password when the caller explicitly asked to
                # (e.g. DUCTA_ADMIN_PASSWORD was set) — otherwise leave it as-is.
                if update_password:
                    row.password_hash = password_hash
                row.roles = roles
            await session.commit()

    # ------------------------------------------------------------------ read

    async def get_by_id(self, user_id: str) -> Optional[User]:
        factory = get_session_factory()
        if factory is None:
            return None
        async with factory() as session:
            row = await session.get(UserRow, user_id)
        return _row_to_user(row) if row else None

    async def get_by_username(self, username: str) -> Optional[User]:
        factory = get_session_factory()
        if factory is None:
            return None
        async with factory() as session:
            result = await session.execute(
                select(UserRow).where(UserRow.username == username.lower())
            )
            row = result.scalar_one_or_none()
        return _row_to_user(row) if row else None

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """Return the User if credentials are valid, else None.

        Uses timing-resistant comparison to prevent user-enumeration attacks.
        """
        factory = get_session_factory()
        if factory is None:
            self._svc.verify_password("__dummy_probe__", _get_dummy_hash())
            return None

        async with factory() as session:
            result = await session.execute(
                select(UserRow).where(UserRow.username == username.lower())
            )
            row = result.scalar_one_or_none()

        if row is None:
            # Constant-time dummy check to prevent timing attacks
            self._svc.verify_password("__dummy_probe__", _get_dummy_hash())
            return None

        if not self._svc.verify_password(password, row.password_hash) or not row.is_active:
            return None

        return _row_to_user(row)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_db_user_store: Optional[DatabaseUserStore] = None
_db_user_store_lock = threading.Lock()


def get_db_user_store() -> DatabaseUserStore:
    """Return the singleton DatabaseUserStore, creating it if needed."""
    global _db_user_store
    if _db_user_store is None:
        with _db_user_store_lock:
            if _db_user_store is None:
                _db_user_store = DatabaseUserStore(auth_service=get_auth_service())
    return _db_user_store
