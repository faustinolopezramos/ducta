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

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ducta.core.certificate import verify_certificate_data

router = APIRouter(prefix="/certificates", tags=["certificates"])

# A pasted/uploaded certificate is a JSON document, not a huge file — this
# caps request cost without needing auth to do it (see the module docstring
# on why this endpoint has no `Depends(require_permission(...))`).
_MAX_CERTIFICATE_JSON_BYTES = 5 * 1024 * 1024


class StandaloneVerifyRequest(BaseModel):
    """A certificate handed to us directly, not one we already have on disk."""

    certificate_json: str = Field(
        ...,
        max_length=_MAX_CERTIFICATE_JSON_BYTES,
        description="The Run Certificate, as raw JSON text (paste or file upload contents).",
    )
    signing_key: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Shared HMAC signing key, if the caller holds it — checks the signature, not just the hash.",
    )


class StandaloneVerifyResponse(BaseModel):
    """Same shape `CertificateVerifyResponse` returns for a locally-known run."""

    ok: bool
    run_id: Optional[str] = None
    reason: str
    signature: str = Field(
        default="unsigned",
        description="unsigned | valid | invalid | present (no key) | stripped | unverifiable",
    )
    level: str = Field(
        default="none",
        description=(
            "What a passing result proves: integrity (self-hash only — detects corruption, "
            "not deliberate tampering) | authenticated (signature checked) | none (failed)"
        ),
    )
    policy_satisfied: bool = Field(
        default=True,
        description=(
            "False when the certificate's own policy (evidence_level=signed) requires "
            "authentication and no key was supplied"
        ),
    )


@router.post(
    "/verify",
    response_model=StandaloneVerifyResponse,
    summary="Verify a Run Certificate's integrity/authenticity without it existing locally",
    description=(
        "The other certificate routes (under /projects/{id}/certificates/...) only work "
        "for a run this instance already knows about. This one takes a certificate someone "
        "hands you directly — an auditor's copy, one pasted from another Ducta deployment — "
        "and checks it on its own terms: the self-hash always, the signature if you supply "
        "the shared key. Deliberately unauthenticated (see routes/__init__.py registration "
        "comment): the whole point is working without an account on this instance."
    ),
)
async def verify_standalone(body: StandaloneVerifyRequest) -> StandaloneVerifyResponse:
    try:
        data = json.loads(body.certificate_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Certificate JSON must be an object")

    key = body.signing_key.encode("utf-8") if body.signing_key else None
    result = verify_certificate_data(data, signing_key=key)
    return StandaloneVerifyResponse(
        ok=result.ok,
        run_id=result.run_id,
        reason=result.reason,
        signature=result.signature,
        level=result.level,
        policy_satisfied=result.policy_satisfied,
    )
