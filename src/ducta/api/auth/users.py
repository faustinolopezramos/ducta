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
from typing import Any, Dict, Optional

from loguru import logger

from ducta.api.auth.security import probe_or_verify, resolve_admin_password
from ducta.api.auth.service import AuthService, get_auth_service
from ducta.api.config import get_settings
from ducta.api.models.auth import User


class _StoredUser:
    """Internal representation that also holds the hashed password."""

    def __init__(self, user: User, hashed_password: str) -> None:
        self.user = user
        self.hashed_password = hashed_password


class UserStore:
    """Thread-safe in-memory user store (basic login only)."""

    def __init__(self, auth_service: AuthService) -> None:
        self._svc = auth_service
        self._by_id: Dict[str, _StoredUser] = {}
        self._by_username: Dict[str, _StoredUser] = {}
        self._store_lock = threading.RLock()
        self._dummy_hash: str = self._svc.hash_password("__dummy__")

    def seed_from_env(self) -> None:
        """Create the admin user from DUCTA_ADMIN_PASSWORD (or use 'admin' as default)."""
        settings = get_settings()
        admin_password = resolve_admin_password(
            os.environ.get("DUCTA_ADMIN_PASSWORD"),
            is_production=settings.is_production(),
        )

        self._add_user(
            id="admin",
            username="admin",
            email="admin@ducta.local",
            plain_password=admin_password,
            roles=["admin"],
        )

    def _add_user(
        self,
        id: str,
        username: str,
        email: str,
        plain_password: str,
        roles: list[str],
    ) -> None:
        user = User(id=id, username=username, email=email, roles=roles)
        stored = _StoredUser(user=user, hashed_password=self._svc.hash_password(plain_password))
        with self._store_lock:
            self._by_id[id] = stored
            self._by_username[username.lower()] = stored

    async def get_by_id(self, user_id: str) -> Optional[User]:
        with self._store_lock:
            stored = self._by_id.get(user_id)
        return stored.user if stored else None

    async def get_by_username(self, username: str) -> Optional[User]:
        with self._store_lock:
            stored = self._by_username.get(username.lower())
        return stored.user if stored else None

    async def authenticate(self, username: str, password: str) -> Optional[User]:
        """Return the User if credentials are valid, otherwise None."""
        with self._store_lock:
            stored = self._by_username.get(username.lower())
        password_valid = probe_or_verify(
            username_found=stored is not None,
            password=password,
            stored_hash=stored.hashed_password if stored else None,
            dummy_hash=self._dummy_hash,
            verify_fn=self._svc.verify_password,
        )
        if not password_valid or stored is None or not stored.user.is_active:
            return None
        return stored.user


_user_store: Optional[UserStore] = None
_user_store_lock = threading.Lock()


def get_user_store() -> "UserStore | Any":
    """Return the singleton user store."""
    global _user_store
    if _user_store is None:
        with _user_store_lock:
            if _user_store is None:
                try:
                    from ducta.api.db.engine import is_db_enabled

                    if is_db_enabled():
                        from ducta.api.db.stores.user_store import get_db_user_store

                        _user_store = get_db_user_store()  # type: ignore[assignment]
                        return _user_store
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to initialise the database-backed user store; "
                        "falling back to in-memory users (they will NOT persist "
                        "across restarts). Cause: {exc}",
                        exc=exc,
                    )
                # Fallback: in-memory store
                store = UserStore(auth_service=get_auth_service())
                store.seed_from_env()
                _user_store = store
    return _user_store
