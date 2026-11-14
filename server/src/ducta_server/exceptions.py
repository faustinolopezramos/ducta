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

from contextlib import contextmanager
from typing import Iterator, Tuple, Type

from ducta.project_store.errors import ErrorCode, NotFoundError, StoreError


@contextmanager
def http_error_on(status_code: int, *exc_types: Type[Exception]) -> Iterator[None]:
    """Translate *exc_types* (default ``ValueError``) raised inside the block
    into an ``HTTPException`` carrying the exception's message.

    Replaces the ``try: ... except ValueError as exc: raise HTTPException(...)``
    stanza that routes used to spell out by hand.
    """
    # Imported here: services that share these exceptions are used outside the
    # server too (`ducta ai`), where FastAPI need not be installed.
    from fastapi import HTTPException  # type: ignore

    catch: Tuple[Type[Exception], ...] = exc_types or (ValueError,)
    try:
        yield
    except catch as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


class ExecutionNotFoundError(NotFoundError):
    """Pipeline execution record not found."""

    error_code = ErrorCode.EXECUTION_NOT_FOUND


class ExecutionError(StoreError):
    """Pipeline execution failed unexpectedly."""

    status_code = 500
    error_code = ErrorCode.EXECUTION_ERROR


class AuthenticationError(StoreError):
    """Invalid or missing authentication credentials."""

    status_code = 401
    error_code = ErrorCode.AUTHENTICATION_ERROR


class InvalidTokenError(AuthenticationError):
    """JWT token is malformed, expired, or has an invalid signature."""

    error_code = ErrorCode.INVALID_TOKEN


class ExpiredTokenError(AuthenticationError):
    """JWT token has expired."""

    error_code = ErrorCode.TOKEN_EXPIRED
