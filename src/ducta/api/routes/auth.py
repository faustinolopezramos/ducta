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

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ducta.api.auth.service import AuthService, get_auth_service
from ducta.api.auth.users import UserStore, get_user_store
from ducta.api.config import Settings, get_settings
from ducta.api.dependencies import CurrentUserDep
from ducta.api.exceptions import ExpiredTokenError, InvalidTokenError
from ducta.api.models.auth import LoginRequest, TokenResponse, User

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserStoreDep = Annotated[UserStore, Depends(get_user_store)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]

router = APIRouter(prefix="/auth", tags=["Auth"])


def _build_token_response(user: User, auth_svc: AuthService) -> TokenResponse:
    return TokenResponse(
        access_token=auth_svc.create_access_token(user.id, user.username, user.roles),
        expires_in=auth_svc.access_token_lifetime_seconds,
        user=user,
    )


def _is_tls_request(request: Request) -> bool:
    """True if *this* request actually arrived over TLS.

    `settings.environment == "production"` doesn't reflect whether this
    particular connection is HTTPS — a production server sitting behind a
    plain-HTTP internal load balancer (mid-migration, misconfigured, or an
    intentionally internal-only deployment) would still mark the cookie
    Secure, and a real browser silently drops a Secure cookie set over plain
    HTTP — logins would appear to "not persist" with no visible error.
    """
    if request.url.scheme == "https":
        return True
    # Trust X-Forwarded-Proto only from a loopback/private immediate peer —
    # same trust model as RateLimitMiddleware._get_client_key's handling of
    # X-Forwarded-For, so the header can't be spoofed by a direct client.
    import ipaddress

    client_host = request.client.host if request.client else None
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if client_host and forwarded_proto:
        try:
            addr = ipaddress.ip_address(client_host)
            if (addr.is_private or addr.is_loopback) and (
                forwarded_proto.split(",")[0].strip().lower() == "https"
            ):
                return True
        except ValueError:
            pass
    return False


def _set_token_cookie(
    request: Request, response: Response, token_response: TokenResponse, settings: Settings
) -> None:
    response.set_cookie(
        key="access_token",
        value=token_response.access_token,
        max_age=token_response.expires_in,
        httponly=True,
        secure=_is_tls_request(request),
        samesite="Lax",
        path="/api",
    )


def _clear_token_cookie(response: Response) -> None:
    response.delete_cookie(key="access_token", path="/api")


def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.cookies.get("access_token")


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth_svc: AuthServiceDep,
    store: UserStoreDep,
    settings: SettingsDependency,
) -> TokenResponse:
    user = await store.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token_response = _build_token_response(user, auth_svc)
    _set_token_cookie(request, response, token_response, settings)
    return token_response


@router.get("/me")
async def get_me(current_user: CurrentUserDep) -> User:
    return current_user


@router.post("/logout", status_code=204, response_model=None)
async def logout(request: Request, response: Response, auth_svc: AuthServiceDep) -> None:
    # Clearing the cookie only stops *this browser* from sending the token —
    # a captured/leaked token (or one still held by another client/tab) kept
    # working for its full lifetime regardless of logout. Revoke it by jti.
    token = _extract_token(request)
    if token:
        try:
            payload = auth_svc.decode_access_token(token)
            jti = payload.get("jti", "")
            exp = payload.get("exp")
            if jti and exp:
                from datetime import datetime, timezone

                auth_svc.revoke_token(jti, datetime.fromtimestamp(exp, tz=timezone.utc))
        except (ExpiredTokenError, InvalidTokenError):
            pass  # already invalid/expired — nothing to revoke
    _clear_token_cookie(response)


class RefreshRequest(BaseModel):
    refreshToken: Optional[str] = Field(default=None, description="Ignored (forward-compat)")


@router.post("/refresh")
async def refresh_token(
    body: RefreshRequest,
    request: Request,
    response: Response,
    auth_svc: AuthServiceDep,
    store: UserStoreDep,
    settings: SettingsDependency,
) -> TokenResponse:
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="No active session found. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = auth_svc.decode_access_token(token)
    except ExpiredTokenError:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid session token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await store.get_by_id(payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="User not found or inactive.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_response = _build_token_response(user, auth_svc)
    _set_token_cookie(request, response, token_response, settings)
    return token_response
