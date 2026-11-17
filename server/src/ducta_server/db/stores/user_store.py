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
import re
import threading
import uuid
from typing import List, Optional, cast

from loguru import logger
from sqlalchemy import select

from ducta_server.auth.security import probe_or_verify, resolve_admin_password
from ducta_server.auth.service import AuthService, get_auth_service
from ducta_server.config import get_settings
from ducta_server.db.models import UserRow
from ducta_server.db.session import get_session_factory, require_session
from ducta_server.models.auth import ROLE_PERMISSIONS, User

_DUMMY_HASH_LOCK = threading.Lock()
_dummy_hash: Optional[str] = None


def _get_dummy_hash() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        with _DUMMY_HASH_LOCK:
            if _dummy_hash is None:
                _dummy_hash = get_auth_service().hash_password("__dummy__")
    return _dummy_hash


class UserAdminError(ValueError):
    """A user-management request that cannot be done (and why, in words for an operator)."""


#: Lower-case, starts with a letter: what a login name can be.
_USERNAME = re.compile(r"^[a-z][a-z0-9_.-]{1,31}$")
#: Shortest password a user created here may have (the seeded admin keeps its own rule).
MIN_PASSWORD_LENGTH = 10


def check_username(username: str) -> str:
    name = username.strip().lower()
    if not _USERNAME.fullmatch(name):
        raise UserAdminError(
            f"Invalid user name {username!r}: 2 to 32 characters, starting with a letter, "
            "lower-case letters, digits, '_', '.' or '-'."
        )
    return name


def check_roles(roles: List[str]) -> List[str]:
    clean = list(dict.fromkeys(r.strip().lower() for r in roles if r.strip()))
    unknown = [r for r in clean if r not in ROLE_PERMISSIONS]
    if not clean or unknown:
        raise UserAdminError(
            f"Unknown role {', '.join(unknown) or '(none given)'}: choose from "
            f"{', '.join(sorted(ROLE_PERMISSIONS))}."
        )
    return clean


def check_password(password: str, username: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserAdminError(f"The password must have at least {MIN_PASSWORD_LENGTH} characters.")
    if password.lower() == username.lower():
        raise UserAdminError("The password cannot be the user name.")
    return password


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
        env_password = os.environ.get("DUCTA_ADMIN_PASSWORD")

        # Only an explicitly-set env var represents intentional rotation of the
        # admin password. If it's unset, don't clobber a password that may have
        # been changed some other way (e.g. directly in the DB) on every restart.
        explicit_password = bool(env_password)
        admin_password = resolve_admin_password(
            env_password, strict=settings.requires_strong_credentials()
        )

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

    @require_session()
    async def _upsert_user(
        self,
        session,
        id: str,
        username: str,
        email: str,
        password_hash: str,
        roles: list[str],
        update_password: bool = True,
    ) -> None:
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

    # ------------------------------------------------------- administration
    # Used by ``ducta-server user …``: the accounts the sign-in page accepts. The web app has
    # no screen for them; whoever can run the command on the server's machine manages them.

    async def _row(self, session, username: str) -> UserRow:
        result = await session.execute(select(UserRow).where(UserRow.username == username.lower()))
        row = result.scalar_one_or_none()
        if row is None:
            raise UserAdminError(f"No user called {username!r}.")
        return cast(UserRow, row)

    @staticmethod
    async def _other_active_admins(session, than: UserRow) -> int:
        rows = (await session.execute(select(UserRow).where(UserRow.is_active.is_(True)))).scalars()
        return sum(1 for r in rows if r.id != than.id and "admin" in r.roles)

    async def create_user(
        self, username: str, password: str, roles: List[str], email: Optional[str] = None
    ) -> User:
        name = check_username(username)
        clean_roles = check_roles(roles)
        check_password(password, name)
        mail = (email or f"{name}@ducta.local").strip().lower()
        factory = get_session_factory()
        if factory is None:
            raise UserAdminError("No database is configured: set DATABASE_URL or pass --db.")
        async with factory() as session:
            taken = (
                await session.execute(
                    select(UserRow).where((UserRow.username == name) | (UserRow.email == mail))
                )
            ).first()
            if taken is not None:
                raise UserAdminError(f"A user with the name {name!r} or the email {mail!r} exists.")
            row = UserRow(
                id=f"usr_{uuid.uuid4().hex[:12]}",
                username=name,
                email=mail,
                password_hash=self._svc.hash_password(password),
            )
            row.roles = clean_roles
            session.add(row)
            await session.commit()
            return _row_to_user(row)

    async def list_users(self) -> List[User]:
        factory = get_session_factory()
        if factory is None:
            raise UserAdminError("No database is configured: set DATABASE_URL or pass --db.")
        async with factory() as session:
            rows = (await session.execute(select(UserRow).order_by(UserRow.username))).scalars()
            return [_row_to_user(r) for r in rows]

    async def _change(self, username: str, change) -> User:
        factory = get_session_factory()
        if factory is None:
            raise UserAdminError("No database is configured: set DATABASE_URL or pass --db.")
        async with factory() as session:
            row = await self._row(session, username)
            await change(session, row)
            await session.commit()
            return _row_to_user(row)

    async def set_roles(self, username: str, roles: List[str]) -> User:
        clean = check_roles(roles)

        async def change(session, row: UserRow) -> None:
            if "admin" in row.roles and "admin" not in clean:
                if await self._other_active_admins(session, row) == 0:
                    raise UserAdminError("That would leave the server with no administrator.")
            row.roles = clean

        return await self._change(username, change)

    async def set_password(self, username: str, password: str) -> User:
        async def change(session, row: UserRow) -> None:
            row.password_hash = self._svc.hash_password(check_password(password, row.username))

        return await self._change(username, change)

    async def set_active(self, username: str, active: bool) -> User:
        async def change(session, row: UserRow) -> None:
            if not active and "admin" in row.roles:
                if await self._other_active_admins(session, row) == 0:
                    raise UserAdminError("That would leave the server with no administrator.")
            row.is_active = active

        return await self._change(username, change)

    # ------------------------------------------------------------------ read

    @require_session()
    async def get_by_id(self, session, user_id: str) -> Optional[User]:
        row = await session.get(UserRow, user_id)
        return _row_to_user(row) if row else None

    @require_session()
    async def get_by_username(self, session, username: str) -> Optional[User]:
        result = await session.execute(select(UserRow).where(UserRow.username == username.lower()))
        row = result.scalar_one_or_none()
        return _row_to_user(row) if row else None

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """Return the User if credentials are valid, else None.

        Uses timing-resistant comparison to prevent user-enumeration attacks.
        """
        factory = get_session_factory()
        if factory is None:
            probe_or_verify(
                username_found=False,
                password=password,
                stored_hash=None,
                dummy_hash=_get_dummy_hash(),
                verify_fn=self._svc.verify_password,
            )
            return None

        async with factory() as session:
            result = await session.execute(
                select(UserRow).where(UserRow.username == username.lower())
            )
            row = result.scalar_one_or_none()

        password_valid = probe_or_verify(
            username_found=row is not None,
            password=password,
            stored_hash=row.password_hash if row else None,
            dummy_hash=_get_dummy_hash(),
            verify_fn=self._svc.verify_password,
        )
        if not password_valid or row is None or not row.is_active:
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
