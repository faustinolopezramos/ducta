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
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

SCHEMA_VERSION = "1.0"
DEFAULT_CERTIFICATE_DIR = ".ducta/runs"
_HASH_PREFIX = "sha256:"
_SIG_PREFIX = "hmac-sha256:"
_SIGNING_KEY_ENV = "Ducta_CERTIFICATE_KEY"


def resolve_signing_key(context: Any) -> Optional[bytes]:
    """Optional HMAC signing key from ``Ducta_CERTIFICATE_KEY``/``DUCTA_CERTIFICATE_KEY`` or
    config; None if unset.

    Signing is off unless a key is provided. A signed certificate proves it was
    produced by a holder of the key (attribution), on top of tamper-evidence.
    """
    # Accept both the historical mixed-case name and the conventional all-caps
    # form — a very plausible typo/convention mismatch would otherwise silently
    # disable signing with zero warning.
    from ducta.core.settings import CoreSettings

    key = os.environ.get(_SIGNING_KEY_ENV) or os.environ.get(_SIGNING_KEY_ENV.upper())
    if not key:
        # from_context accepts a Context or a bare settings dict, which is what
        # resolve_signing_key_from_dir hands in when there is no live Context.
        key = CoreSettings.from_context(context).certificate_signing_key
        if key:
            # A signing key in a config file is a secret in a file that is
            # normally committed. It also weakens `key_id`: that identifier is a
            # truncated SHA-256 of the key, harmless for a high-entropy secret
            # but brute-forceable for the short human-chosen string a config
            # file invites. Warn rather than refuse — the key still works, and
            # failing the run over it would be worse than the exposure.
            logger.warning(
                "Run Certificate signing key read from 'global_settings.certificate_signing_key'. "
                "Prefer the {} environment variable: a key in a config file is usually "
                "committed to version control, and a short/low-entropy value can be recovered "
                "from the public 'key_id' field of any certificate it signs.",
                _SIGNING_KEY_ENV.upper(),
            )
    if not key:
        return None
    return str(key).encode("utf-8")


def resolve_signing_key_from_dir(project_root: Path) -> Optional[bytes]:
    """Resolve the signing key for a project directory that has no live ``Context``.

    Looks for ``certificate_signing_key`` in a ``global_settings.{toml,yaml,yml}``
    file directly under ``project_root`` or under ``project_root/config``
    (same ``_dir_convention_paths`` convention as ``setting/config_forms.py``
    — a project may keep its config root-level or under ``config/``), then
    falls back to the environment variable via :func:`resolve_signing_key`.
    Used by the CLI ``certify verify`` command and the certificates API,
    neither of which builds a full pipeline ``Context``.
    """
    gs: Dict[str, Any] = {}
    search_dirs = [Path(project_root), Path(project_root) / "config"]
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        found = False
        for candidate in ("global_settings.toml", "global_settings.yaml", "global_settings.yml"):
            cfg_file = directory / candidate
            if cfg_file.is_file():
                try:
                    from ducta.setting.loaders import ConfigLoaderFactory

                    data = ConfigLoaderFactory().load_config(str(cfg_file))
                    if isinstance(data, dict):
                        gs = data
                except Exception as e:  # noqa: BLE001
                    logger.debug("Could not read {} for signing key: {}", cfg_file, e)
                found = True
                break
        if found:
            break
    return resolve_signing_key(gs)


def key_id_of(key: bytes) -> str:
    """A short, non-secret identifier for a signing key (first 8 hex of its SHA-256)."""
    return hashlib.sha256(key).hexdigest()[:8]


def _ctx_get(context: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a context that may be a dict or an attribute-bearing object."""
    if isinstance(context, dict):
        return context.get(key, default)
    return getattr(context, key, default)


def _canonical_json(payload: Any) -> str:
    """Deterministic JSON for hashing: sorted keys, compact, str-coerced fallbacks."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return _HASH_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _config_fingerprint(context: Any) -> str:
    """Hash the five config documents so a config change is visible in the certificate."""
    configs = {
        name: _ctx_get(context, name, {}) or {}
        for name in (
            "global_settings",
            "pipelines_config",
            "nodes_config",
            "input_config",
            "output_config",
        )
    }
    return _sha256(_canonical_json(configs))


def _quality_summary(context: Any) -> List[Dict[str, Any]]:
    """Per-node quality outcomes for the certificate.

    Prefers the compact summaries the executor deposits on ``_quality_results``
    (passed/score/errors/warnings per node+phase — populated for every run without
    opt-in). Falls back to persisted ``quality_output_paths`` for backward compat.
    """
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
    """A tamper-evident record of one pipeline run.

    ``certificate_hash`` is a SHA-256 over every other field (via :meth:`content`),
    so any later edit to the file is detectable by :func:`verify_certificate`.
    """

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
    error: Optional[str] = None
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
            "error": self.error,
        }
        return data

    def compute_hash(self) -> str:
        """SHA-256 over the canonical content (independent of the stored hash)."""
        return _sha256(_canonical_json(self.content()))

    def sign(self, key: bytes) -> None:
        """Attach an HMAC-SHA256 signature over the certificate hash (attribution)."""
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
    """Assemble a certificate from the evidence the run left on ``context``.

    Reads input/output fingerprints and quality outputs already stored on the
    context, captures the current environment, and fingerprints the config. Never
    raises — a certificate is best-effort and must not break a run.
    """
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
        error=error,
    )
    cert.certificate_hash = cert.compute_hash()
    return cert


def certificate_dir(context: Any, run_id: str) -> Path:
    """Resolve ``<run_certificate_dir>/<run_id>`` for this run (relative to cwd)."""
    from ducta.core.settings import CoreSettings

    return Path(CoreSettings.from_context(context).run_certificate_dir) / run_id


def is_enabled(context: Any) -> bool:
    """Run certificates are on by default; disable with ``enable_run_certificate: false``."""
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


@dataclass
class VerifyResult:
    """Outcome of verifying a certificate's integrity."""

    ok: bool
    run_id: Optional[str]
    reason: str
    signature: str = "unsigned"  # unsigned | valid | invalid | present (no key)


def verify_certificate(path: Path, signing_key: Optional[bytes] = None) -> VerifyResult:
    """Confirm the certificate was not altered; when signed and keyed, check the signature.

    Integrity (self-hash) is always checked. If the certificate carries a signature
    and ``signing_key`` is provided, the HMAC is verified too and a mismatch fails.
    """
    try:
        data = load_certificate(path)
    except Exception as e:  # noqa: BLE001
        return VerifyResult(ok=False, run_id=None, reason=f"could not read certificate: {e}")

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
        return VerifyResult(ok=True, run_id=run_id, reason="hash matches — untampered")
    if signing_key is None:
        return VerifyResult(
            ok=True,
            run_id=run_id,
            reason="hash matches — untampered (signed; no key provided to verify signature)",
            signature="present (no key)",
        )
    expected = (
        _SIG_PREFIX + hmac.new(signing_key, stored.encode("utf-8"), hashlib.sha256).hexdigest()
    )
    if hmac.compare_digest(expected, stored_sig):
        return VerifyResult(
            ok=True, run_id=run_id, reason="hash matches and signature valid", signature="valid"
        )
    return VerifyResult(
        ok=False,
        run_id=run_id,
        reason="signature mismatch — not signed by the provided key",
        signature="invalid",
    )
