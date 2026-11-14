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

Runs that must not touch the real datasets: a sample run (``--sample``) and the
reproduction of a certificate (``certify verify --reproduce``) write their
outputs under a folder of their own.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from loguru import logger  # type: ignore

from ducta import state


def _original_output_root(ctx: Any) -> Path:
    return Path(str(getattr(ctx, "output_path", None) or ctx.global_config.get("output_path")))


#: What a run id looks like: the hex uuid a run gets, or any plain name.
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*\Z")


def reproduction_dir(ctx: Any, env: str, run_id: str) -> Path:
    """Where the reproduction of run *run_id* writes: ``<output>/<env>/.ducta/reproduce/<id>``.

    *run_id* comes from the certificate's JSON, which an unsigned certificate
    does not protect, and this folder is emptied before the run: an id that is
    an absolute path or climbs with ``..`` must never name another folder.
    """
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
        raise ValueError(f"{run_id!r} is not a run id; the certificate cannot be reproduced")
    if not env or ".." in env or any(sep in env for sep in ("/", "\\", ":")):
        raise ValueError(f"{env!r} is not an environment name")
    base = state.under(_original_output_root(ctx) / env, "reproduce")
    target = base / run_id
    if base.resolve() not in target.resolve().parents:
        raise ValueError(f"The reproduction folder {target} is outside {base}")
    return target


def redirect_writes(
    ctx: Any,
    target: Path,
    env: str,
    *,
    certificates: bool,
    pipeline_name: Optional[str] = None,
) -> None:
    """Make every dataset this run writes land under *target*.

    The datasets the run produces are also read from there by the nodes
    downstream of them; the other inputs are read where they are. Quality
    reports and chain state go to *target* too, and so does the run
    certificate when *certificates* is true.

    So do the model registry and the experiment tracker: a training node that
    registers and promotes its model used to do it in the real registry, and a
    reproduction put a new version in production. A serving node still reads its
    model from the real registry (``ctx.serving_mlops_path``), read-only.
    """
    from ducta.gate.output.paths import _PathManager
    from ducta.gate.validators import ConfigValidator
    from ducta.mlrun.config import StorageBackendFactory

    original = _original_output_root(ctx)
    gs = ctx.global_config
    # Before the output path moves: without `mlops_path` the store lives under it.
    real_mlops = StorageBackendFactory.resolve_mlops_path(ctx, None, pipeline_name)
    if real_mlops:
        ctx.serving_mlops_path = str(real_mlops)
    gs["mlops_path"] = str(state.under(target, "mlops"))
    ctx.output_path = str(target)
    gs["output_path"] = str(target)
    output_config = getattr(ctx, "output_config", None) or {}
    for key, cfg in output_config.items():
        declared = cfg.get("filepath") if isinstance(cfg, dict) else None
        if not declared:
            continue  # derived from output_path, which now is the target
        try:
            rel = Path(declared).relative_to(original)
        except ValueError:
            # Elsewhere — on another disk, or remote storage (s3://…): the run
            # writes none of it, only a local copy under the target.
            rel = Path(*str(key).split("."))
        cfg["filepath"] = str(target / rel)

    # A node downstream reads what the run just wrote, not the real dataset: its
    # input entry names the dataset's real path, which the run no longer writes.
    paths = _PathManager(ctx, ConfigValidator())
    for key, entry in (getattr(ctx, "input_config", None) or {}).items():
        out = output_config.get(key)
        if not isinstance(entry, dict) or not isinstance(out, dict):
            continue
        out_format = str(getattr(out.get("format"), "value", out.get("format")) or "")
        if not entry.get("filepath") or out_format.lower() == "unity_catalog":
            continue
        try:
            entry["filepath"] = paths.resolve_output_path(out, key, env)
        except Exception as error:  # noqa: BLE001
            logger.debug("Input '{}' keeps its path: {}", key, error)
    # A dataset this run does not produce (a single node, or a subset, reads its
    # upstream) is missing under the target: it is read from the real one.
    fallbacks = list(getattr(ctx, "_read_fallback_paths", None) or [])
    if str(original) not in fallbacks:
        fallbacks.append(str(original))
    ctx._read_fallback_paths = fallbacks
    gs["_read_fallback_paths"] = fallbacks

    if certificates:
        gs["run_certificate_dir"] = str(state.under(target, "runs"))
    chain = gs.get("chain") if isinstance(gs.get("chain"), dict) else {}
    gs["chain"] = {**chain, "state_dir": str(state.under(target, "chain_state"))}
    quality = gs.get("quality") if isinstance(gs.get("quality"), dict) else None
    if quality is not None:
        output = quality.get("output") if isinstance(quality.get("output"), dict) else {}
        quality["output"] = {**output, "base_path": str(target / "quality")}


def prepare_reproduction(
    ctx: Any, env: str, run_id: str, pipeline_name: Optional[str] = None
) -> Path:
    """Point the run at a fresh reproduction folder for *run_id* and return it.

    The folder is emptied first: an appending output would otherwise add to the
    previous reproduction's rows. The run's certificate stays with the real
    ones (it says which run it reproduces), so it can be listed and compared.
    """
    from ducta.core.settings import CoreSettings

    target = reproduction_dir(ctx, env, run_id)
    if target.exists():
        shutil.rmtree(target)
    # Resolved before the output path moves: the default directory is under it.
    ctx.pinned_certificate_dir = CoreSettings.from_context(ctx).run_certificate_dir
    redirect_writes(ctx, target, env, certificates=False, pipeline_name=pipeline_name)
    ctx.reproduction_of = run_id
    return target


def pin_served_models(ctx: Any, cert: Dict[str, Any]) -> Dict[str, int]:
    """Serve the reproduction the model versions the run served (``{name: version}``).

    A serving node names a stage (``stage: production``); reproduced after a
    promotion, it scored with today's production model and the outputs differed
    for a reason that has nothing to do with reproducibility. The certificate
    names the version each node used (``nodes[].ml.model``).
    """
    pins: Dict[str, int] = {}
    for node in cert.get("nodes") or []:
        model = ((node or {}).get("ml") or {}).get("model") or {}
        name, version = model.get("name"), model.get("version")
        if model.get("source", "ducta") != "ducta" or not name or version is None:
            continue
        if name in pins and pins[name] != int(version):
            logger.warning(
                "The run served '{}' at versions {} and {}; the reproduction serves v{}",
                name,
                pins[name],
                version,
                pins[name],
            )
            continue
        pins[name] = int(version)
    if pins:
        ctx.pinned_models = pins
        for name, version in sorted(pins.items()):
            logger.info("Reproducing with model '{}' pinned to v{}", name, version)
    return pins


def reproduction_window(
    cert: Dict[str, Any], start_date: Optional[str], end_date: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """The dates a reproduction runs with: the ones given, else the ones the run used.

    Re-running an incremental pipeline over another window cannot reproduce its
    outputs, so dates that differ from the recorded ones are warned about.
    """
    recorded = cert.get("run_window") or {}
    if start_date is None and end_date is None:
        return recorded.get("start_date"), recorded.get("end_date")
    if recorded and (start_date, end_date) != (
        recorded.get("start_date"),
        recorded.get("end_date"),
    ):
        logger.warning(
            "The run used --start-date {} --end-date {}; reproducing over other dates "
            "will most likely not match its outputs.",
            recorded.get("start_date"),
            recorded.get("end_date"),
        )
    return start_date, end_date
