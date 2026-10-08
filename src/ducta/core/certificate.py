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

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from loguru import logger  # type: ignore

from ducta.core.context_utils import get_context_value as _ctx_get
from ducta.setting.environments import sanitize_env_for_path

# 1.6: an ML node that scored with a registered model records it under ``ml.model``
# (source, name, the version the run pinned, artifact hash).
SCHEMA_VERSION = "1.6"
DEFAULT_CERTIFICATE_DIR = "${output_path}/${environment}/.ducta/runs"
LEGACY_FINGERPRINT_ALGORITHM = "legacy/v1"
_HASH_PREFIX = "sha256:"
_SIG_PREFIX = "hmac-sha256:"
_SIGNING_KEY_ENV = "DUCTA_CERTIFICATE_KEY"


def resolve_signing_key(context: Any) -> Optional[bytes]:
    """Optional HMAC signing key from ``DUCTA_CERTIFICATE_KEY`` or config; None if unset."""
    from ducta.core.settings import CoreSettings

    key = os.environ.get(_SIGNING_KEY_ENV)
    if not key:
        key = CoreSettings.from_context(context).certificate_signing_key
        if key:
            logger.warning(
                "Run Certificate signing key read from 'global_config.certificate_signing_key'. "
                "Prefer the {} environment variable: a key in a config file is usually "
                "committed to version control, and a short/low-entropy value can be recovered "
                "from the public 'key_id' field of any certificate it signs.",
                _SIGNING_KEY_ENV,
            )
    if not key:
        return None
    return str(key).encode("utf-8")


def resolve_signing_key_from_dir(project_root: Path) -> Optional[bytes]:
    """Resolve the signing key for a project directory that has no live ``Context``.

    Reads ``settings`` of the project's ``ducta.yaml`` (the project at
    ``project_root`` or in its ``config/`` folder); the environment variable
    still wins, as in :func:`resolve_signing_key`.
    """
    gs: Dict[str, Any] = {}
    try:
        from ducta.setting.project_loader import (
            compile_project,
            find_project_root,
            validate_project,
        )

        root = find_project_root(Path(project_root))
        if root is not None:
            gs = compile_project(validate_project(root, None))["global_config"]
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not read the project in {} for a signing key: {}", project_root, e)
    return resolve_signing_key(gs)


def key_id_of(key: bytes) -> str:
    """A short, non-secret identifier for a signing key (first 8 hex of its SHA-256)."""
    return hashlib.sha256(key).hexdigest()[:8]


def _canonical_json(payload: Any) -> str:
    """Deterministic JSON for hashing: sorted keys, compact, str-coerced fallbacks."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return _HASH_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_fingerprint(context: Any) -> str:
    """Hash the five config documents so a config change is visible in the certificate."""
    configs = {
        name: _ctx_get(context, name, {}) or {}
        for name in (
            "global_config",
            "pipelines_config",
            "nodes_config",
            "input_config",
            "output_config",
        )
    }
    return _sha256(_canonical_json(configs))


_config_fingerprint = config_fingerprint


def _quality_extension_fingerprints(context: Any) -> Dict[str, Any]:
    """Hash the custom-check modules named in ``quality.extensions``."""
    try:
        from ducta.core.code_fingerprint import fingerprint_module

        gs = _ctx_get(context, "global_config", {}) or {}
        quality = gs.get("quality") if isinstance(gs, dict) else None
        paths = (quality or {}).get("extensions") if isinstance(quality, dict) else None
        if not paths:
            return {}
        return {str(path): fingerprint_module(str(path)) for path in paths}
    except Exception as e:  # noqa: BLE001 — a certificate must never break a run
        logger.debug("Quality extension fingerprinting skipped: {}", e)
        return {}


def _quality_summary(context: Any) -> List[Dict[str, Any]]:
    """Per-node quality outcomes for the certificate."""
    from ducta.core.ledger import ledger_for

    results = ledger_for(context).quality_results
    if results:
        return list(results)

    entries: List[Dict[str, Any]] = []
    for path in _ctx_get(context, "quality_output_paths", []) or []:
        entries.append(
            {
                "report_type": getattr(path, "report_type", None),
                "node": getattr(path, "node_name", None),
                "run_id": getattr(path, "run_id", None),
                "output_path": getattr(path, "output_path", None),
                "format": getattr(path, "format", None),
                "rows_written": getattr(path, "rows_written", None),
            }
        )
    return entries


@dataclass
class RunCertificate:
    """A verifiable record of one pipeline run."""

    run_id: str
    pipeline: str
    environment_name: str
    status: str
    started_at: str
    ended_at: str
    ducta_version: str
    schema_version: str = SCHEMA_VERSION
    duration_seconds: Optional[float] = None
    config_fingerprint: str = ""
    environment: Dict[str, Any] = field(default_factory=dict)
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    quality: List[Dict[str, Any]] = field(default_factory=list)
    code: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    evidence_complete: bool = True
    evidence_gaps: List[str] = field(default_factory=list)
    signed: bool = False
    evidence_level: str = "record"
    certificate_hash: str = ""
    signature: Optional[str] = None
    key_id: Optional[str] = None

    def content(self) -> Dict[str, Any]:
        """The certificate as a dict, excluding the self-hash (what the hash is over)."""
        data = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "pipeline": self.pipeline,
            "environment_name": self.environment_name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "ducta_version": self.ducta_version,
            "config_fingerprint": self.config_fingerprint,
            "environment": self.environment,
            "nodes": self.nodes,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "quality": self.quality,
            "code": self.code,
            "error": self.error,
            "evidence_complete": self.evidence_complete,
            "evidence_gaps": self.evidence_gaps,
            "signed": self.signed,
            "evidence_level": self.evidence_level,
        }
        return data

    def compute_hash(self) -> str:
        """SHA-256 over the canonical content (independent of the stored hash)."""
        return _sha256(_canonical_json(self.content()))

    def sign(self, key: bytes) -> None:
        """Attach an HMAC-SHA256 signature over the certificate hash (attribution)."""
        self.signed = True
        digest = hmac.new(key, self.compute_hash().encode("utf-8"), hashlib.sha256).hexdigest()
        self.signature = _SIG_PREFIX + digest
        self.key_id = key_id_of(key)

    def sealed(self) -> Dict[str, Any]:
        """Full certificate dict with hash (and signature, when present)."""
        data = self.content()
        data["certificate_hash"] = self.compute_hash()
        if self.signature:
            data["signature"] = self.signature
            data["key_id"] = self.key_id
        return data


def _build_code_block(context: Any, ledger: Any) -> Dict[str, Any]:
    """Assemble the certificate's ``code`` block from the ledger and config."""
    try:
        block: Dict[str, Any] = {"nodes": ledger.code_fingerprints}
    except Exception as e:  # noqa: BLE001
        logger.debug("Code fingerprints unreadable from ledger: {}", e)
        block = {"nodes": {}}

    extensions = _quality_extension_fingerprints(context)
    if extensions:
        block["quality_extensions"] = extensions
    return block


def _evidence_level(context: Any) -> str:
    from ducta.core.settings import CoreSettings

    try:
        return CoreSettings.from_context(context).evidence_level
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not resolve evidence_level for certificate: {}", e)
        return "record"


def build_certificate(
    context: Any,
    *,
    run_id: str,
    pipeline: str,
    environment_name: str,
    status: str,
    started_at: datetime,
    ended_at: datetime,
    ducta_version: str,
    error: Optional[str] = None,
) -> RunCertificate:
    """Assemble a certificate from the evidence the run left on ``context``."""
    try:
        from ducta.mlrun.environment import EnvironmentSnapshot

        environment = EnvironmentSnapshot.capture().to_dict()
    except Exception as e:  # noqa: BLE001
        logger.debug("Environment capture for certificate failed: {}", e)
        environment = {}

    from ducta.core.ledger import ledger_for

    ledger = ledger_for(context)

    cert = RunCertificate(
        run_id=run_id,
        pipeline=pipeline,
        environment_name=environment_name,
        status=status,
        started_at=started_at.astimezone(timezone.utc).isoformat(),
        ended_at=ended_at.astimezone(timezone.utc).isoformat(),
        duration_seconds=round((ended_at - started_at).total_seconds(), 3),
        ducta_version=ducta_version,
        config_fingerprint=_config_fingerprint(context),
        environment=environment,
        nodes=sorted(ledger.node_details, key=lambda n: str(n.get("name", ""))),
        inputs=ledger.input_fingerprints,
        outputs=ledger.output_fingerprints,
        quality=_quality_summary(context),
        code=_build_code_block(context, ledger),
        error=error,
        evidence_complete=ledger.evidence_complete,
        evidence_gaps=ledger.record_failures,
        evidence_level=_evidence_level(context),
    )
    cert.certificate_hash = cert.compute_hash()
    return cert


def certificate_dir(context: Any, run_id: str) -> Path:
    """Resolve the run certificate directory for this run."""
    from ducta.core.settings import CoreSettings

    settings = CoreSettings.from_context(context)
    return Path(settings.run_certificate_dir) / run_id


def iter_certificate_dirs(base_dir: Path) -> Iterator[Tuple[Optional[str], str, Path]]:
    """Yield ``(env, run_id, run_dir)`` for every certificate under ``base_dir``."""
    if not base_dir.is_dir():
        return
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "certificate.json").is_file():
            yield None, entry.name, entry
            continue
        for sub in sorted(entry.iterdir()):
            if sub.is_dir() and (sub / "certificate.json").is_file():
                yield entry.name, sub.name, sub


def find_certificate_dir(base_dir: Path, run_id: str, env: Optional[str] = None) -> Optional[Path]:
    """Resolve a single run's certificate directory under ``base_dir``."""
    if env:
        candidate = base_dir / sanitize_env_for_path(env) / run_id
        if (candidate / "certificate.json").is_file():
            return candidate
    for found_env, found_run_id, run_dir in iter_certificate_dirs(base_dir):
        if found_run_id == run_id and (env is None or found_env == env):
            return run_dir
    return None


def is_enabled(context: Any) -> bool:
    """Run certificates are on by default; disable with ``evidence_level: off``."""
    from ducta.core.settings import CoreSettings

    return CoreSettings.from_context(context).enable_run_certificate


def write_certificate(cert: RunCertificate, run_dir: Path) -> Path:
    """Atomically write ``certificate.json`` into ``run_dir`` and sync to StorageBackend; return its path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "certificate.json"
    payload = json.dumps(cert.sealed(), indent=2, default=str)
    fd, tmp = tempfile.mkstemp(dir=str(run_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    try:
        from ducta.core.storage import get_storage_backend

        storage = get_storage_backend()
        storage.put_object(f"certificates/{cert.run_id}/certificate.json", payload.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "StorageBackend certificate sync failed for {id}: {exc}", id=cert.run_id, exc=exc
        )

    return target


def load_certificate(path: Path) -> Dict[str, Any]:
    """Load a certificate JSON file as a dict."""
    data: Dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


LEVEL_INTEGRITY = "integrity"
LEVEL_AUTHENTICATED = "authenticated"


@dataclass
class VerifyResult:
    """Outcome of verifying a certificate's integrity."""

    ok: bool
    run_id: Optional[str]
    reason: str
    signature: str = "unsigned"
    level: str = "none"
    policy_satisfied: bool = True


def verify_certificate(path: Path, signing_key: Optional[bytes] = None) -> VerifyResult:
    """Confirm the certificate at *path* was not altered; when signed and keyed, check the signature."""
    try:
        data = load_certificate(path)
    except Exception as e:  # noqa: BLE001
        return VerifyResult(ok=False, run_id=None, reason=f"could not read certificate: {e}")
    return verify_certificate_data(data, signing_key=signing_key)


def verify_certificate_data(
    data: Dict[str, Any], signing_key: Optional[bytes] = None
) -> VerifyResult:
    """Confirm an already-parsed certificate dict was not altered; check the signature when keyed."""
    run_id = data.get("run_id")
    stored = data.get("certificate_hash")
    if not stored:
        return VerifyResult(ok=False, run_id=run_id, reason="certificate has no certificate_hash")

    content = {
        k: v for k, v in data.items() if k not in ("certificate_hash", "signature", "key_id")
    }
    recomputed = _sha256(_canonical_json(content))
    if recomputed != stored:
        return VerifyResult(
            ok=False,
            run_id=run_id,
            reason=f"hash mismatch — certificate was modified (stored {stored}, recomputed {recomputed})",
        )

    stored_sig = data.get("signature")
    if not stored_sig:
        if data.get("signed"):
            return VerifyResult(
                ok=False,
                run_id=run_id,
                reason=(
                    "certificate declares signed=true but carries no signature — "
                    "the signature was removed"
                ),
                signature="stripped",
            )
        if "signed" not in data and signing_key is not None:
            return VerifyResult(
                ok=False,
                run_id=run_id,
                reason=(
                    "certificate predates the signed marker (schema < 1.3) and carries no "
                    "signature, so a removed signature cannot be ruled out; a signing key "
                    "was provided, so authorship cannot be attested. Verify without a key "
                    "to check integrity only, or re-issue the certificate."
                ),
                signature="unverifiable",
            )
        if data.get("evidence_level") == "signed":
            return VerifyResult(
                ok=False,
                run_id=run_id,
                reason=(
                    "certificate was issued under evidence_level=signed but carries " "no signature"
                ),
            )
        return VerifyResult(
            ok=True,
            run_id=run_id,
            reason=(
                "integrity OK — unsigned: detects corruption, not deliberate tampering "
                "(anyone who edits a field can recompute the hash)"
            ),
            level=LEVEL_INTEGRITY,
        )
    if signing_key is None:
        policy_signed = data.get("evidence_level") == "signed"
        reason = (
            "integrity OK — signed, but the signature was NOT checked (no key "
            "provided); provide the key to rule out deliberate tampering"
        )
        if policy_signed:
            reason += (
                ". This certificate's policy (evidence_level=signed) requires "
                "authentication — verification is incomplete without the key"
            )
        return VerifyResult(
            ok=True,
            run_id=run_id,
            reason=reason,
            signature="present (no key)",
            level=LEVEL_INTEGRITY,
            policy_satisfied=not policy_signed,
        )
    expected = (
        _SIG_PREFIX + hmac.new(signing_key, stored.encode("utf-8"), hashlib.sha256).hexdigest()
    )
    if hmac.compare_digest(expected, stored_sig):
        return VerifyResult(
            ok=True,
            run_id=run_id,
            reason="hash matches and signature valid — untampered",
            signature="valid",
            level=LEVEL_AUTHENTICATED,
        )
    return VerifyResult(
        ok=False,
        run_id=run_id,
        reason="signature mismatch — not signed by the provided key",
        signature="invalid",
    )


def logical_fingerprint(fp: Dict[str, Any]) -> tuple:
    """The reproducibility-relevant identity of a dataset."""
    return (
        fp.get("algorithm") or LEGACY_FINGERPRINT_ALGORITHM,
        fp.get("schema_hash"),
        fp.get("row_count"),
        fp.get("content_hash") or fp.get("sample_hash"),
    )


def fingerprints_comparable(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Whether two serialized fingerprints may be compared at all, and why not."""
    from ducta.mlrun.fingerprint import comparable

    return comparable(a, b)


def diff_certificates(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Structural diff between two certificates: identity, config, outputs, quality."""
    outputs_a = a.get("outputs", {}) or {}
    outputs_b = b.get("outputs", {}) or {}
    output_rows = []
    for key in sorted(set(outputs_a) | set(outputs_b)):
        fp_a = outputs_a.get(key)
        fp_b = outputs_b.get(key)
        reason: Optional[str] = None
        match: Optional[bool]
        if fp_a is None or fp_b is None:
            match = False
        else:
            ok, reason = fingerprints_comparable(fp_a, fp_b)
            match = (logical_fingerprint(fp_a) == logical_fingerprint(fp_b)) if ok else None
        output_rows.append(
            {
                "key": key,
                "in_a": fp_a is not None,
                "in_b": fp_b is not None,
                "match": match,
                "not_comparable_reason": reason,
            }
        )

    def _quality_key(entry: Dict[str, Any]) -> tuple:
        return (entry.get("node"), entry.get("phase"))

    quality_a = {_quality_key(q): q for q in (a.get("quality", []) or [])}
    quality_b = {_quality_key(q): q for q in (b.get("quality", []) or [])}
    quality_rows = []
    for key in sorted(set(quality_a) | set(quality_b), key=lambda k: (k[0] or "", k[1] or "")):
        qa = quality_a.get(key)
        qb = quality_b.get(key)
        quality_rows.append(
            {
                "node": key[0],
                "phase": key[1],
                "passed_a": qa.get("passed") if qa else None,
                "passed_b": qb.get("passed") if qb else None,
                "errors_a": qa.get("errors") if qa else None,
                "errors_b": qb.get("errors") if qb else None,
                "match": (
                    qa is not None and qb is not None and qa.get("passed") == qb.get("passed")
                ),
            }
        )

    model_rows = _model_rows(a, b)
    models_match = all(row["match"] for row in model_rows)

    config_fingerprint_match = bool(a.get("config_fingerprint")) and a.get(
        "config_fingerprint"
    ) == b.get("config_fingerprint")
    pipeline_match = a.get("pipeline") == b.get("pipeline")
    environment_match = a.get("environment_name") == b.get("environment_name")
    status_match = a.get("status") == b.get("status")
    outputs_match = all(row["match"] is not False for row in output_rows) if output_rows else True
    outputs_comparable = all(row["match"] is not None for row in output_rows)

    return {
        "outputs_comparable": outputs_comparable,
        "run_a": a.get("run_id"),
        "run_b": b.get("run_id"),
        "pipeline_a": a.get("pipeline"),
        "pipeline_b": b.get("pipeline"),
        "pipeline_match": pipeline_match,
        "environment_match": environment_match,
        "status_a": a.get("status"),
        "status_b": b.get("status"),
        "status_match": status_match,
        "config_fingerprint_match": config_fingerprint_match,
        "outputs": output_rows,
        "outputs_match": outputs_match,
        "quality": quality_rows,
        "models": model_rows,
        "models_match": models_match,
        "identical": pipeline_match
        and environment_match
        and status_match
        and config_fingerprint_match
        and outputs_match
        and models_match,
    }


def _served_models(cert: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """node name → the model it scored with (schema >= 1.6)."""
    return {
        str(n.get("name")): n["ml"]["model"]
        for n in cert.get("nodes", []) or []
        if isinstance(n, dict) and isinstance(n.get("ml"), dict) and n["ml"].get("model")
    }


def _model_identity(model: Optional[Dict[str, Any]]) -> Optional[tuple]:
    if not model:
        return None
    return (
        model.get("source"),
        model.get("name"),
        model.get("version"),
        model.get("artifact_sha256"),
    )


def _model_rows(a: Dict[str, Any], b: Dict[str, Any]) -> List[Dict[str, Any]]:
    models_a, models_b = _served_models(a), _served_models(b)
    rows = []
    for node in sorted(set(models_a) | set(models_b)):
        ma, mb = models_a.get(node), models_b.get(node)
        rows.append(
            {
                "node": node,
                "model_a": f"{ma.get('name')} v{ma.get('version')}" if ma else None,
                "model_b": f"{mb.get('name')} v{mb.get('version')}" if mb else None,
                "match": _model_identity(ma) == _model_identity(mb),
            }
        )
    return rows
