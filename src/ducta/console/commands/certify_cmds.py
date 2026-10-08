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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ducta.console.core import VALID_NAME_RE, ExitCode
from ducta.console.ux.formatters import create_table, get_console, require_table
from ducta.core.certificate import (
    diff_certificates,
    find_certificate_dir,
    fingerprints_comparable,
    iter_certificate_dirs,
    load_certificate,
    logical_fingerprint,
    resolve_signing_key_from_dir,
    verify_certificate,
)
from ducta.setting.environments import DEFAULT_ENVIRONMENTS

try:
    from rich import box

    _USE_RICH = True
except ImportError:  # pragma: no cover - rich is a hard dependency in practice
    _USE_RICH = False


def _env_arg(parsed_args) -> Optional[str]:
    return getattr(parsed_args, "env", None)


def _resolve_run_certificate_dir(parsed_args, env: str) -> Optional[Path]:
    """The configured run-certificates directory for one environment.

    Resolved the same way a pipeline run does — through the project's config,
    so ``run_certificate_dir``'s ``${output_path}/${environment}`` interpolation
    (the Ducta storage convention; see ``CoreSettings._resolve_scoped_dir``)
    is honored rather than assumed. Returns None if this environment can't be
    resolved at all (e.g. the project defines no config for it).
    """
    from ducta.console.config import ConfigManager
    from ducta.console.execution import ContextInitializer
    from ducta.core.settings import CoreSettings

    try:
        config_manager = ConfigManager(
            base_path=getattr(parsed_args, "base_path", None), require_config=False
        )
        config_manager.change_to_config_directory()
        context = ContextInitializer(config_manager).initialize(env)
        return Path(CoreSettings.from_context(context).run_certificate_dir)
    except Exception as e:  # noqa: BLE001 — best-effort, one environment at a time
        logger.debug("Could not resolve run-certificates dir for env '{}': {}", env, e)
        return None


#: Pre-convention default (relative to cwd, not ${output_path}/${environment}).
#: Kept discoverable — read-only — so certificates a project accumulated
#: before the Ducta storage convention moved run_certificate_dir don't
#: silently disappear from `certify list`/`show`/`verify`/`diff`; see
#: CoreSettings.DEFAULT_CERTIFICATE_DIR.
_LEGACY_RUNS_DIR = Path(".ducta/runs")


def _legacy_runs_dir() -> Optional[Path]:
    return _LEGACY_RUNS_DIR if _LEGACY_RUNS_DIR.is_dir() else None


def _candidate_runs_dirs(parsed_args) -> List[Tuple[Optional[str], Path]]:
    """``[(env, runs_dir), ...]`` to search.

    ``--dir`` is a hard override: search that one directory as-is (a manual or
    pre-convention layout; ``iter_certificate_dirs`` already understands both
    the flat and the per-environment-subfolder shape). Otherwise: every
    canonical environment (``ducta.setting.environments.DEFAULT_ENVIRONMENTS``,
    or just the one given via ``--env``) whose configured directory actually
    exists — since the Ducta storage convention gives each environment its
    own directory, there is no longer a single tree that holds every
    environment's certificates — plus the pre-convention ``.ducta/runs``
    directory, if present, so certificates written before that change stay
    discoverable.
    """
    explicit = getattr(parsed_args, "dir", None)
    if explicit:
        return [(None, Path(explicit))]

    env = _env_arg(parsed_args)
    dirs: List[Tuple[Optional[str], Path]] = []
    for candidate_env in [env] if env else DEFAULT_ENVIRONMENTS:
        d = _resolve_run_certificate_dir(parsed_args, candidate_env)
        if d is not None and d.is_dir():
            dirs.append((candidate_env, d))
    legacy = _legacy_runs_dir()
    if legacy is not None:
        dirs.append((None, legacy))
    return dirs


def handle_certify(parsed_args) -> int:
    cmd = getattr(parsed_args, "certify_command", None)
    if cmd == "list":
        return _handle_list(parsed_args)
    if cmd == "show":
        return _handle_show(parsed_args)
    if cmd == "verify":
        return _handle_verify(parsed_args)
    if cmd == "diff":
        return _handle_diff(parsed_args)
    logger.error("Unknown certify command: {}", cmd)
    return ExitCode.GENERAL_ERROR.value


# ── Formatting helpers ───────────────────────────────────────────────────────


def _relative_time(iso_ts: Optional[str]) -> str:
    """'2h ago' / '3d ago' style label; falls back to the raw timestamp."""
    if not iso_ts:
        return "?"
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return iso_ts
    delta = datetime.now(timezone.utc) - ts
    seconds = delta.total_seconds()
    if seconds < 0:
        return iso_ts
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _status_label(status: str) -> str:
    status = (status or "?").lower()
    if not _USE_RICH:
        return status
    color = {"success": "bold bright_green", "failed": "bold bright_red"}.get(status, "yellow")
    icon = {"success": "✓", "failed": "✗"}.get(status, "•")
    return f"[{color}]{icon} {status}[/]"


def _fingerprint_label(fp: Dict[str, Any]) -> str:
    """'exact' / 'sample (100 rows)' / 'schema-only' — visible without --json.

    Sample and schema fingerprints only cover part of the data (or none of it),
    so a corrupted row outside what was hashed goes undetected. That distinction
    used to be invisible in the pretty view — only ``--json`` showed ``mode`` —
    which is exactly how a project can end up presenting a degraded fingerprint
    as if it were the full-table guarantee the certificate implies.
    """
    mode = fp.get("mode")
    if not mode:
        return "[dim]?[/]" if _USE_RICH else "?"
    if mode == "exact":
        return "[bold bright_green]exact[/]" if _USE_RICH else "exact"
    if mode == "sample":
        rows = (fp.get("details") or {}).get("sample_rows_covered")
        label = f"sample ({rows} rows)" if rows is not None else "sample"
        return f"[yellow]{label}[/]" if _USE_RICH else label
    if mode == "schema":
        return "[yellow]schema-only[/]" if _USE_RICH else "schema-only"
    return f"[yellow]{mode}[/]" if _USE_RICH else str(mode)


def _quality_summary_label(quality: list) -> str:
    """'3/3 passed' or '2/3 passed (1 failed)' summarizing a certificate's checks."""
    if not quality:
        return "—"
    total = len(quality)
    passed = sum(1 for q in quality if q.get("passed"))
    if passed == total:
        return (
            f"[bold bright_green]{passed}/{total} passed[/]"
            if _USE_RICH
            else f"{passed}/{total} passed"
        )
    label = f"{passed}/{total} passed"
    return f"[bold bright_red]{label}[/]" if _USE_RICH else label


# ── list ─────────────────────────────────────────────────────────────────────


def _handle_list(parsed_args) -> int:
    candidates = _candidate_runs_dirs(parsed_args)
    env_filter = _env_arg(parsed_args)

    rows = []
    for dir_env, runs_dir in candidates:
        if not runs_dir.is_dir():
            continue
        for found_env, _run_id, run_dir in iter_certificate_dirs(runs_dir):
            effective_env = found_env or dir_env
            if env_filter is not None and effective_env != env_filter:
                continue
            try:
                data = load_certificate(run_dir / "certificate.json")
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not read {}: {}", run_dir / "certificate.json", e)
                continue
            data["_env_dir"] = effective_env
            rows.append(data)

    if not rows:
        searched = ", ".join(str(d) for _, d in candidates) or "no configured environment"
        logger.warning(
            "No run certificates found under {}{}",
            searched,
            f" for environment '{env_filter}'" if env_filter else "",
        )
        return ExitCode.SUCCESS.value

    rows.sort(key=lambda d: d.get("started_at", ""), reverse=True)

    title = (
        f"Run Certificates — {candidates[0][1]}"
        if len(candidates) == 1
        else "Run Certificates — all environments"
    )
    console = get_console()
    table = create_table(title=title, box=box.SIMPLE_HEAD) if _USE_RICH else None
    if console is not None and table is not None:
        table.add_column("Run ID", no_wrap=True)
        table.add_column("Pipeline")
        table.add_column("Status")
        table.add_column("Env")
        table.add_column("Started")
        table.add_column("Duration", justify="right")
        table.add_column("Quality")
        table.add_column("Signed", justify="center")
        for d in rows:
            duration = d.get("duration_seconds")
            env_label = d.get("_env_dir") or d.get("environment_name") or "legacy"
            table.add_row(
                str(d.get("run_id", "?"))[:12],
                str(d.get("pipeline", "?")),
                _status_label(str(d.get("status", "?"))),
                str(env_label),
                _relative_time(d.get("started_at")),
                f"{duration:.1f}s" if isinstance(duration, (int, float)) else "?",
                _quality_summary_label(d.get("quality", [])),
                "🔏" if d.get("signature") else "–",
            )
        console.print(table)
    else:
        for d in rows:
            logger.info(
                "{}  {:<10}  {:<10}  {}",
                str(d.get("run_id", "?"))[:16],
                d.get("pipeline", "?"),
                d.get("status", "?"),
                d.get("started_at", "?"),
            )
    return ExitCode.SUCCESS.value


# ── show ─────────────────────────────────────────────────────────────────────


def _resolve_run_id(
    candidates: List[Tuple[Optional[str], Path]], run_id: Optional[str], env: Optional[str] = None
) -> Optional[Path]:
    """Resolve a run id (or unique prefix) to its certificate.json across ``candidates``.

    Each candidate is searched with ``find_certificate_dir``/``iter_certificate_dirs``,
    which understand both the current per-environment-directory layout and the
    legacy flat/per-env-subfolder shapes a single directory may still hold (e.g.
    under an explicit ``--dir``). An exact run id match wins when it's unique
    across every candidate; otherwise a unique run id prefix wins.
    """
    if not run_id:
        logger.error("--run-id is required")
        return None
    if not VALID_NAME_RE.match(run_id):
        # run_id becomes a path component below (runs_dir / run_id / ...);
        # without this, a value like "../../../../etc" could resolve
        # outside runs_dir once matched against an existing certificate.json.
        logger.error("Invalid run id '{}': must be alphanumeric, '_' or '-'", run_id)
        return None

    exact_matches: List[Path] = []
    prefix_matches: List[Path] = []
    for dir_env, runs_dir in candidates:
        exact = find_certificate_dir(runs_dir, run_id, env=env if dir_env is None else None)
        if exact is not None:
            exact_matches.append(exact)
        for found_env, found_run_id, run_dir in iter_certificate_dirs(runs_dir):
            effective_env = found_env or dir_env
            if found_run_id.startswith(run_id) and (env is None or effective_env == env):
                prefix_matches.append(run_dir)

    if len(exact_matches) == 1:
        return exact_matches[0] / "certificate.json"

    matches = exact_matches or prefix_matches
    seen: set = set()
    deduped: List[Path] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            deduped.append(m)

    scope = f" in environment '{env}'" if env else ""
    if len(deduped) == 1:
        return deduped[0] / "certificate.json"
    searched = ", ".join(str(d) for _, d in candidates) or "no configured environment"
    if not deduped:
        logger.error("No certificate found for run '{}'{} under {}", run_id, scope, searched)
    else:
        logger.error("Run id prefix '{}' is ambiguous{} ({} matches)", run_id, scope, len(deduped))
    return None


def _resolve_run(parsed_args) -> Optional[Path]:
    """Resolve the certificate path for --run-id (accepts a unique prefix)."""
    return _resolve_run_id(
        _candidate_runs_dirs(parsed_args),
        getattr(parsed_args, "run_id", None),
        env=_env_arg(parsed_args),
    )


def _print_certificate_human(data: Dict[str, Any]) -> None:
    console = get_console()
    if console is None or not _USE_RICH:
        # No Rich available — fall back to the raw JSON rather than a half
        # -formatted plain-text render.
        print(json.dumps(data, indent=2))
        return

    from rich.panel import Panel
    from rich.table import Table

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("Run ID", str(data.get("run_id", "?")))
    summary.add_row("Pipeline", str(data.get("pipeline", "?")))
    summary.add_row("Status", _status_label(str(data.get("status", "?"))))
    summary.add_row("Environment", str(data.get("environment_name", "?")))
    summary.add_row("Started", str(data.get("started_at", "?")))
    summary.add_row("Ended", str(data.get("ended_at", "?")))
    duration = data.get("duration_seconds")
    summary.add_row("Duration", f"{duration:.2f}s" if isinstance(duration, (int, float)) else "?")
    summary.add_row("Config fingerprint", str(data.get("config_fingerprint", "?"))[:23] + "…")
    summary.add_row("Certificate hash", str(data.get("certificate_hash", "?"))[:23] + "…")
    signature = data.get("signature")
    summary.add_row(
        "Signed",
        f"🔏 yes (key {data.get('key_id')})"
        if signature
        else "[yellow]no — hash only, not tamper-evident[/]",
    )
    evidence_complete = data.get("evidence_complete", True)
    evidence_gaps = data.get("evidence_gaps") or []
    if not evidence_complete or evidence_gaps:
        gap_text = "; ".join(str(g) for g in evidence_gaps) or "reason not recorded"
        summary.add_row("Evidence", f"[bold yellow]⚠ incomplete[/] — {gap_text}")
    if data.get("error"):
        summary.add_row("Error", f"[bold bright_red]{data['error']}[/]")
    console.print(Panel(summary, title="Run Certificate", border_style="cyan"))

    nodes = data.get("nodes", []) or []
    if nodes:
        nodes_table = require_table(title="Nodes", box=box.SIMPLE_HEAD)
        nodes_table.add_column("Name")
        nodes_table.add_column("Type")
        nodes_table.add_column("Status")
        nodes_table.add_column("Duration", justify="right")
        nodes_table.add_column("Outputs")
        for n in nodes:
            nodes_table.add_row(
                str(n.get("name", "?")),
                str(n.get("type", "?")),
                _status_label(str(n.get("status", "?"))),
                f"{n.get('duration_seconds', 0):.2f}s",
                ", ".join(n.get("outputs") or []) or "—",
            )
        console.print(nodes_table)

    datasets: Dict[str, Dict[str, Any]] = {}
    for key, fp in (data.get("inputs", {}) or {}).items():
        datasets[key] = {"direction": "input", **fp}
    for key, fp in (data.get("outputs", {}) or {}).items():
        datasets[key] = {"direction": "output", **fp}
    if datasets:
        ds_table = require_table(title="Datasets", box=box.SIMPLE_HEAD)
        ds_table.add_column("Key")
        ds_table.add_column("I/O")
        ds_table.add_column("Rows", justify="right")
        ds_table.add_column("Schema hash")
        ds_table.add_column("Fingerprint")
        for key, fp in sorted(datasets.items()):
            row_count = fp.get("row_count")
            schema_hash = fp.get("schema_hash")
            ds_table.add_row(
                key,
                fp["direction"],
                str(row_count) if row_count is not None else "?",
                str(schema_hash)[:16] + "…" if schema_hash else "?",
                _fingerprint_label(fp),
            )
        console.print(ds_table)

    quality = data.get("quality", []) or []
    if quality:
        q_table = require_table(title="Quality checks", box=box.SIMPLE_HEAD)
        q_table.add_column("Node")
        q_table.add_column("Phase")
        q_table.add_column("Result")
        q_table.add_column("Score", justify="right")
        q_table.add_column("Errors", justify="right")
        q_table.add_column("Warnings", justify="right")
        for q in quality:
            passed = q.get("passed")
            result = "[bold bright_green]✓ passed[/]" if passed else "[bold bright_red]✗ failed[/]"
            q_table.add_row(
                str(q.get("node", "?")),
                str(q.get("phase", "?")),
                result,
                f"{q.get('score', 0):.2f}",
                str(q.get("errors", 0)),
                str(q.get("warnings", 0)),
            )
        console.print(q_table)

    console.print("[dim]Use --json for the full machine-readable certificate.[/]")


def _handle_show(parsed_args) -> int:
    path = _resolve_run(parsed_args)
    if path is None:
        return ExitCode.VALIDATION_ERROR.value
    try:
        data = load_certificate(path)
    except Exception as e:  # noqa: BLE001
        logger.error("Could not read certificate: {}", e)
        return ExitCode.EXECUTION_ERROR.value

    if getattr(parsed_args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        _print_certificate_human(data)
    return ExitCode.SUCCESS.value


# ── verify ───────────────────────────────────────────────────────────────────


def _handle_verify(parsed_args) -> int:
    path = _resolve_run(parsed_args)
    if path is None:
        return ExitCode.VALIDATION_ERROR.value

    # Integrity first: a tampered certificate can't be trusted to reproduce against.
    # A signing key (env DUCTA_CERTIFICATE_KEY, or
    # global_config.certificate_signing_key in the project's config) additionally
    # verifies the signature.
    signing_key = resolve_signing_key_from_dir(Path.cwd())
    result = verify_certificate(path, signing_key=signing_key)
    if not result.ok:
        logger.error("✗ Certificate {} FAILED verification: {}", result.run_id, result.reason)
        return ExitCode.VALIDATION_ERROR.value
    logger.info(
        "✓ Certificate {} verified ({}): {} [signature: {}]",
        result.run_id,
        result.level,
        result.reason,
        result.signature,
    )
    if not result.policy_satisfied:
        logger.error(
            "✗ Certificate {} was issued under evidence_level=signed and could not be "
            "authenticated: set DUCTA_CERTIFICATE_KEY to the signing key and verify again.",
            result.run_id,
        )
        return ExitCode.VALIDATION_ERROR.value
    _warn_degraded_fingerprints(path)

    if getattr(parsed_args, "reproduce", False):
        return _reproduce(parsed_args, path)
    return ExitCode.SUCCESS.value


def _warn_degraded_fingerprints(path: Path) -> None:
    """Flag any dataset whose fingerprint is not ``exact`` after a successful verify.

    ``verify`` only checks that the certificate wasn't altered — it says nothing
    about how thoroughly the data itself was fingerprinted. A ``sample`` or
    ``schema`` mode certificate can pass verification cleanly while covering
    only part of the data (or none of it), which is easy to miss because the
    integrity check above is the headline result. Surfacing it here, not just
    in ``--json``, is the point: this is the command someone runs specifically
    to decide whether to trust the certificate.
    """
    try:
        data = load_certificate(path)
    except Exception:  # noqa: BLE001
        return
    degraded = []
    for direction in ("inputs", "outputs"):
        for key, fp in (data.get(direction, {}) or {}).items():
            mode = fp.get("mode")
            if mode and mode != "exact":
                degraded.append(f"{key} ({mode})")
    if degraded:
        logger.warning(
            "  fingerprint mode is not 'exact' for: {} — a change outside what was "
            "hashed would not be detected",
            ", ".join(sorted(degraded)),
        )


def _pin_delta_inputs(context: Any, recorded_inputs: Dict[str, Any]) -> None:
    """Read each Delta input at the version the certificate recorded.

    Without this a reproduction reads the *current* table, so any commit since
    the original run makes the outputs differ and the verdict says nothing
    about the pipeline. Delta keeps old versions (until VACUUM removes their
    files), so the original input can be read back exactly.
    """
    input_config = getattr(context, "input_config", None) or {}
    for key, fingerprint in recorded_inputs.items():
        if (fingerprint or {}).get("algorithm") != "delta-version/v1":
            continue
        version = (fingerprint.get("details") or {}).get("delta_version")
        entry = input_config.get(key)
        if version is None or not isinstance(entry, dict):
            continue
        entry["versionAsOf"] = version
        logger.info("Reproducing with Delta input '{}' pinned to version {}", key, version)


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
        _pin_delta_inputs(context, cert.get("inputs") or {})
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
    incomparable = []
    for key, old_fp in recorded.items():
        new_fp = fresh.get(key)
        if not new_fp:
            mismatches.append((key, "missing in reproduction run"))
            continue
        ok, reason = fingerprints_comparable(new_fp, old_fp)
        if not ok:
            # Not a reproduction failure. The certificate was written by a
            # different fingerprint algorithm (usually: it predates an upgrade),
            # so nothing can be concluded about the data either way. Calling
            # that "not reproducible" would be a false alarm on every
            # certificate written before the upgrade.
            incomparable.append((key, reason))
        elif logical_fingerprint(new_fp) != logical_fingerprint(old_fp):
            mismatches.append((key, "data differs"))

    if incomparable:
        for key, why in incomparable:
            logger.warning("    ? {}: not comparable — {}", key, why)
        logger.warning(
            "{}/{} output(s) could not be compared. Re-run the pipeline to write "
            "a certificate with the current algorithm, then reproduce against that.",
            len(incomparable),
            len(recorded),
        )

    if mismatches:
        for key, why in mismatches:
            logger.error("    ✗ {}: {}", key, why)
        logger.error(
            "✗ NOT reproducible: {}/{} outputs diverged from the certificate",
            len(mismatches),
            len(recorded),
        )
        return ExitCode.VALIDATION_ERROR.value

    comparable_count = len(recorded) - len(incomparable)
    if incomparable and comparable_count == 0:
        logger.error(
            "✗ Nothing could be verified: none of the {} output(s) were comparable.",
            len(recorded),
        )
        return ExitCode.VALIDATION_ERROR.value

    logger.info("✓ Reproducible: all {} output(s) match the certificate", comparable_count)
    return ExitCode.SUCCESS.value


# ── diff ─────────────────────────────────────────────────────────────────────


def _handle_diff(parsed_args) -> int:
    candidates = _candidate_runs_dirs(parsed_args)
    env = _env_arg(parsed_args)
    path_a = _resolve_run_id(candidates, getattr(parsed_args, "run_a", None), env=env)
    path_b = _resolve_run_id(candidates, getattr(parsed_args, "run_b", None), env=env)
    if path_a is None or path_b is None:
        return ExitCode.VALIDATION_ERROR.value

    try:
        cert_a = load_certificate(path_a)
        cert_b = load_certificate(path_b)
    except Exception as e:  # noqa: BLE001
        logger.error("Could not read certificate: {}", e)
        return ExitCode.EXECUTION_ERROR.value

    result = diff_certificates(cert_a, cert_b)
    console = get_console()

    def _mark(ok: Optional[bool]) -> str:
        # None is the third answer: the two fingerprints were measured by
        # different algorithms, so neither "same" nor "DIFFERENT" is a claim we
        # can honestly make.
        if ok is None:
            return "?" if not _USE_RICH else "[bold yellow]not comparable[/]"
        if not _USE_RICH:
            return "same" if ok else "DIFFERENT"
        return "[bold bright_green]same[/]" if ok else "[bold bright_red]DIFFERENT[/]"

    if console is not None and _USE_RICH:
        head = require_table(box=box.SIMPLE_HEAD)
        head.add_column(str(result["run_a"])[:12])
        head.add_column(str(result["run_b"])[:12])
        head.add_column("")
        head.add_row("Pipeline", result["pipeline_a"], result["pipeline_b"])
        head.add_row("Status", result["status_a"], result["status_b"])
        console.print(head)
        console.print(f"Pipeline match:  {_mark(result['pipeline_match'])}")
        console.print(f"Environment match: {_mark(result['environment_match'])}")
        console.print(f"Status match: {_mark(result['status_match'])}")
        console.print(
            f"Config fingerprint match: {_mark(result['config_fingerprint_match'])} "
            "[dim](same fingerprint = identical global_config/pipelines/nodes/input/output config)[/]"
        )

        if result["outputs"]:
            out_table = require_table(title="Outputs", box=box.SIMPLE_HEAD)
            out_table.add_column("Key")
            out_table.add_column(f"In {str(result['run_a'])[:8]}", justify="center")
            out_table.add_column(f"In {str(result['run_b'])[:8]}", justify="center")
            out_table.add_column("Match")
            for row in result["outputs"]:
                mark = _mark(row["match"])
                if row.get("not_comparable_reason"):
                    mark = f"{mark} [dim]({row['not_comparable_reason']})[/]"
                out_table.add_row(
                    row["key"],
                    "✓" if row["in_a"] else "—",
                    "✓" if row["in_b"] else "—",
                    mark,
                )
            console.print(out_table)

        if result["quality"]:
            q_table = require_table(title="Quality", box=box.SIMPLE_HEAD)
            q_table.add_column("Node")
            q_table.add_column("Phase")
            q_table.add_column(f"Passed ({str(result['run_a'])[:8]})", justify="center")
            q_table.add_column(f"Passed ({str(result['run_b'])[:8]})", justify="center")
            for row in result["quality"]:
                q_table.add_row(
                    str(row["node"]),
                    str(row["phase"]),
                    "✓" if row["passed_a"] else ("✗" if row["passed_a"] is not None else "—"),
                    "✓" if row["passed_b"] else ("✗" if row["passed_b"] is not None else "—"),
                )
            console.print(q_table)

        if result.get("models"):
            m_table = require_table(title="Models", box=box.SIMPLE_HEAD)
            m_table.add_column("Node")
            m_table.add_column(str(result["run_a"])[:8])
            m_table.add_column(str(result["run_b"])[:8])
            m_table.add_column("Match")
            for row in result["models"]:
                m_table.add_row(
                    str(row["node"]),
                    row["model_a"] or "—",
                    row["model_b"] or "—",
                    _mark(row["match"]),
                )
            console.print(m_table)

        console.print()
        if result["identical"]:
            console.print(
                "[bold bright_green]✓ Certificates are equivalent[/] (same config, same outputs)"
            )
        else:
            console.print("[bold bright_yellow]⚠ Certificates differ[/] — see mismatches above")
    else:
        logger.info(json.dumps(result, indent=2, default=str))

    return ExitCode.SUCCESS.value
