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

import json
from pathlib import Path
from typing import Optional

from loguru import logger

from ducta.console.core import VALID_NAME_RE, ExitCode
from ducta.core.certificate import (
    DEFAULT_CERTIFICATE_DIR,
    load_certificate,
    resolve_signing_key_from_dir,
    verify_certificate,
)


def _runs_dir(parsed_args) -> Path:
    return Path(getattr(parsed_args, "dir", None) or DEFAULT_CERTIFICATE_DIR)


def _certificate_path(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / run_id / "certificate.json"


def handle_certify(parsed_args) -> int:
    cmd = getattr(parsed_args, "certify_command", None)
    if cmd == "list":
        return _handle_list(parsed_args)
    if cmd == "show":
        return _handle_show(parsed_args)
    if cmd == "verify":
        return _handle_verify(parsed_args)
    logger.error("Unknown certify command: {}", cmd)
    return ExitCode.GENERAL_ERROR.value


def _handle_list(parsed_args) -> int:
    runs_dir = _runs_dir(parsed_args)
    if not runs_dir.is_dir():
        logger.warning("No runs directory found at {}", runs_dir)
        return ExitCode.SUCCESS.value

    certs = sorted(runs_dir.glob("*/certificate.json"))
    if not certs:
        logger.warning("No run certificates found under {}", runs_dir)
        return ExitCode.SUCCESS.value

    rows = []
    for path in certs:
        try:
            data = load_certificate(path)
            rows.append(data)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read {}: {}", path, e)

    rows.sort(key=lambda d: d.get("started_at", ""), reverse=True)
    for d in rows:
        logger.info(
            "{}  {:<10}  {:<10}  {}",
            d.get("run_id", "?")[:16],
            d.get("pipeline", "?"),
            d.get("status", "?"),
            d.get("started_at", "?"),
        )
    return ExitCode.SUCCESS.value


def _resolve_run(parsed_args) -> Optional[Path]:
    """Resolve the certificate path for --run-id (accepts a unique prefix)."""
    runs_dir = _runs_dir(parsed_args)
    run_id = getattr(parsed_args, "run_id", None)
    if not run_id:
        logger.error("--run-id is required")
        return None
    if not VALID_NAME_RE.match(run_id):
        # run_id becomes a path component below (runs_dir / run_id / ...);
        # without this, a value like "../../../../etc" could resolve
        # outside runs_dir once matched against an existing certificate.json.
        logger.error("Invalid --run-id '{}': must be alphanumeric, '_' or '-'", run_id)
        return None

    exact = _certificate_path(runs_dir, run_id)
    if exact.exists():
        return exact

    matches = [p for p in runs_dir.glob("*/certificate.json") if p.parent.name.startswith(run_id)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        logger.error("No certificate found for run '{}' under {}", run_id, runs_dir)
    else:
        logger.error("Run id prefix '{}' is ambiguous ({} matches)", run_id, len(matches))
    return None


def _handle_show(parsed_args) -> int:
    path = _resolve_run(parsed_args)
    if path is None:
        return ExitCode.VALIDATION_ERROR.value
    try:
        data = load_certificate(path)
    except Exception as e:  # noqa: BLE001
        logger.error("Could not read certificate: {}", e)
        return ExitCode.EXECUTION_ERROR.value
    print(json.dumps(data, indent=2))
    return ExitCode.SUCCESS.value


def _handle_verify(parsed_args) -> int:
    path = _resolve_run(parsed_args)
    if path is None:
        return ExitCode.VALIDATION_ERROR.value

    # Integrity first: a tampered certificate can't be trusted to reproduce against.
    # A signing key (env Ducta_CERTIFICATE_KEY/DUCTA_CERTIFICATE_KEY, or
    # global_settings.certificate_signing_key in the project's config) additionally
    # verifies the signature.
    signing_key = resolve_signing_key_from_dir(Path.cwd())
    result = verify_certificate(path, signing_key=signing_key)
    if not result.ok:
        logger.error("✗ Certificate {} FAILED verification: {}", result.run_id, result.reason)
        return ExitCode.VALIDATION_ERROR.value
    logger.info(
        "✓ Certificate {} verified: {} [signature: {}]",
        result.run_id,
        result.reason,
        result.signature,
    )

    if getattr(parsed_args, "reproduce", False):
        return _reproduce(parsed_args, path)
    return ExitCode.SUCCESS.value


def _logical_fingerprint(fp: dict) -> tuple:
    """The reproducibility-relevant identity of a dataset: schema + rows + sample.

    Excludes ``file_size_bytes``/``file_mtime`` (which can jitter across otherwise
    identical writes) — so 'reproducible' means 'same data', not 'same bytes'.
    """
    return (fp.get("schema_hash"), fp.get("row_count"), fp.get("sample_hash"))


def _reproduce(parsed_args, cert_path: Path) -> int:
    """Re-run the certificate's pipeline and confirm every output reproduces.

    Turns the certificate from a tamper-evident record into a reproducibility
    proof: run again, compare each output's logical fingerprint to the recorded one.
    """
    cert = load_certificate(cert_path)
    pipeline = str(cert.get("pipeline") or "")
    env = cert.get("environment_name", "base")
    recorded = cert.get("outputs", {}) or {}
    if not pipeline:
        logger.error("Certificate has no pipeline name — cannot reproduce")
        return ExitCode.VALIDATION_ERROR.value
    if not recorded:
        logger.warning("Certificate records no outputs — nothing to reproduce")
        return ExitCode.SUCCESS.value

    logger.info("Reproducing pipeline '{}' (env={}) to compare against certificate…", pipeline, env)
    try:
        from ducta.console import execution
        from ducta.console.commands.config_cmds import _init_config_manager
        from ducta.core import PipelineExecutor

        config_manager = _init_config_manager(parsed_args)
        context = execution.ContextInitializer(config_manager).initialize(env)
        executor = PipelineExecutor(context, str(config_manager.get_config_directory()))
        run = executor.run_pipeline(
            pipeline_name=pipeline,
            start_date=getattr(parsed_args, "start_date", None),
            end_date=getattr(parsed_args, "end_date", None),
            execution_mode="sync",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Reproduction run failed: {}", e)
        return ExitCode.EXECUTION_ERROR.value

    # A blocked gate returns normally, so the fingerprint comparison below would
    # run against outputs the reproduction never wrote and report "not
    # reproducible" for the wrong reason.
    if run.gate_blocked:
        logger.error(
            "Reproduction run was blocked by a quality gate on {}; cannot compare "
            "fingerprints against the certificate.",
            ", ".join(sorted(run.gate_blocked)),
        )
        return ExitCode.EXECUTION_ERROR.value

    fresh = getattr(context, "_output_fingerprints", {}) or {}
    mismatches = []
    for key, old_fp in recorded.items():
        new_fp = fresh.get(key)
        if not new_fp:
            mismatches.append((key, "missing in reproduction run"))
        elif _logical_fingerprint(new_fp) != _logical_fingerprint(old_fp):
            mismatches.append((key, "data differs (schema/rows/sample changed)"))

    if mismatches:
        for key, why in mismatches:
            logger.error("    ✗ {}: {}", key, why)
        logger.error(
            "✗ NOT reproducible: {}/{} outputs diverged from the certificate",
            len(mismatches),
            len(recorded),
        )
        return ExitCode.VALIDATION_ERROR.value

    logger.info("✓ Reproducible: all {} output(s) match the certificate", len(recorded))
    return ExitCode.SUCCESS.value
