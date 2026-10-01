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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import bcrypt as _bcrypt  # type: ignore
import jwt  # PyJWT
from jwt import ExpiredSignatureError
from jwt import InvalidTokenError as _JWTInvalidTokenError

from ducta.api.exceptions import ExpiredTokenError, InvalidTokenError


class AuthService:
    """Handles JWT lifecycle and password operations (basic login only)."""

    _TOKEN_TYPE_ACCESS = "access"

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expires_hours: int = 24,
        redis_url: Optional[str] = None,
    ) -> None:
        self._secret = secret_key
        self._algorithm = algorithm
        self._access_ttl = timedelta(hours=access_token_expires_hours)
        # jti -> expiry. In-memory/per-process (same constraint as the
        # in-memory rate limiter): a logout on one worker won't revoke the
        # token on another. Bounded by each entry's own token expiry, not by
        # size — a revoked jti only needs remembering until it would have
        # expired anyway; _prune_expired_revocations sweeps stale entries.
        # When *redis_url* is given, revocations are also written to Redis
        # (key TTL = remaining token lifetime) so every worker/replica and a
        # restart honour them; the in-memory dict stays as a local fallback.
        self._revoked: dict[str, datetime] = {}
        self._revoked_lock = threading.Lock()
        self._redis = self._connect_redis(redis_url)

    @staticmethod
    def _connect_redis(redis_url: Optional[str]) -> Any:
        if not redis_url:
            return None
        try:
            import redis  # type: ignore[import-untyped]

            client = redis.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
            client.ping()
            return client
        except Exception as exc:  # noqa: BLE001 - missing package, connection/auth errors
            from loguru import logger

            logger.warning(
                "Token revocation: could not use Redis at the configured URL ({exc}); "
                "falling back to per-process revocation (logout will not propagate "
                "across workers or survive restarts).",
                exc=exc,
            )
            return None

    @staticmethod
    def _revocation_key(jti: str) -> str:
        return f"ducta:revoked:{jti}"

    @staticmethod
    def _bcrypt_bytes(plain: str) -> bytes:
        """Encode a password for bcrypt.

        bcrypt only considers the first 72 bytes and raises on longer inputs in
        recent versions; truncate explicitly so hashing and verification stay
        consistent and never error on long passphrases.
        """
        return plain.encode("utf-8")[:72]

    def hash_password(self, plain: str) -> str:
        """Return a bcrypt hash of *plain*."""
        return _bcrypt.hashpw(self._bcrypt_bytes(plain), _bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, plain: str, hashed: str) -> bool:
        """Return True if *plain* matches the bcrypt *hashed* password."""
        return _bcrypt.checkpw(self._bcrypt_bytes(plain), hashed.encode("utf-8"))

    def create_access_token(self, user_id: str, username: str, roles: list[str]) -> str:
        """Return a signed JWT access token."""
        now = datetime.now(tz=timezone.utc)
        payload = {
            "sub": user_id,
            "username": username,
            "roles": roles,
            "type": self._TOKEN_TYPE_ACCESS,
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + self._access_ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    @property
    def access_token_lifetime_seconds(self) -> int:
        return int(self._access_ttl.total_seconds())

    def decode_access_token(self, token: str) -> dict:
        """Decode and validate an access token."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except ExpiredSignatureError:
            raise ExpiredTokenError("Token has expired")
        except _JWTInvalidTokenError:
            raise InvalidTokenError("Token is invalid or has been tampered with")

        if payload.get("type") != self._TOKEN_TYPE_ACCESS:
            raise InvalidTokenError(
                f"Expected token type '{self._TOKEN_TYPE_ACCESS}', got '{payload.get('type')}'"
            )
        if self.is_revoked(payload.get("jti", "")):
            raise InvalidTokenError("Token has been revoked (logged out)")
        return payload

    def revoke_token(self, jti: str, expires_at: datetime) -> None:
        """Revoke a token by its ``jti`` — checked by every subsequent `decode_access_token`.

        No previously-issued JWT can otherwise be invalidated before its own
        expiry (that's the whole point of a stateless token) — logout only
        cleared the client's cookie, so a captured/leaked token kept working
        for its full lifetime regardless of logout.
        """
        if not jti:
            return
        with self._revoked_lock:
            self._prune_expired_revocations_locked()
            self._revoked[jti] = expires_at
        if self._redis is not None:
            ttl = max(1, int((expires_at - datetime.now(tz=timezone.utc)).total_seconds()))
            try:
                self._redis.setex(self._revocation_key(jti), ttl, "1")
            except Exception as exc:  # noqa: BLE001
                from loguru import logger

                logger.warning("Token revocation: Redis write failed ({exc})", exc=exc)

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        with self._revoked_lock:
            if jti in self._revoked:
                return True
        if self._redis is not None:
            try:
                return bool(self._redis.exists(self._revocation_key(jti)))
            except Exception:  # noqa: BLE001 - Redis down: local list is all we have
                return False
        return False

    def _prune_expired_revocations_locked(self) -> None:
        now = datetime.now(tz=timezone.utc)
        expired = [jti for jti, exp in self._revoked.items() if exp <= now]
        for jti in expired:
            del self._revoked[jti]


_auth_service: Optional[AuthService] = None
_auth_service_lock = threading.Lock()


def get_auth_service() -> AuthService:
    """Return the module-level AuthService singleton (thread-safe)."""
    global _auth_service
    if _auth_service is None:
        with _auth_service_lock:
            if _auth_service is None:
                from ducta.api.config import get_settings

                s = get_settings()
                _auth_service = AuthService(
                    secret_key=s.jwt_secret_key,
                    algorithm=s.jwt_algorithm,
                    access_token_expires_hours=s.jwt_expiration_hours,
                    redis_url=s.revocation_redis_url or s.rate_limit_redis_url,
                )
    return _auth_service
