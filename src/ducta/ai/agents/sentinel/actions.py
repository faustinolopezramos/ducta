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

How Sentinel re-runs a pipeline — the only thing it ever does on its own.

* :class:`CliExecutor` (``ducta ai sentinel watch``): ``ducta start`` in a
  child process; the outcome is known when it returns, from the run's
  certificate.
* :class:`ServerExecutor` (inside the API server): queued on the server's
  execution manager as user ``sentinel``; its outcome comes back through the
  same hook every run finishes through.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Protocol

from ducta.ai.agents.sentinel.triage import RunEvent, event_from_certificate

#: The user a re-run is attributed to: in run history, audit, and the hook.
SENTINEL_USER = "sentinel"


class Executor(Protocol):
    def rerun(
        self, root: Path, env: str, pipeline: str, nodes: List[str], reuse_upstream: bool
    ) -> Optional[RunEvent]:
        """Start a re-run; its outcome when known now, else ``None`` (it arrives later)."""
        ...


def _newest_certificate(
    root: Path, env: str, pipeline: str, after: Optional[str]
) -> Optional[dict]:
    from datetime import datetime, timezone

    from ducta.api.services.run_certificates import certificates

    def at(value: object) -> datetime:
        try:
            found = datetime.fromisoformat(str(value))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        return found if found.tzinfo else found.replace(tzinfo=timezone.utc)

    since = at(after) if after else None
    newest = None
    for _env, cert in certificates(root, env):
        if cert.get("pipeline") != pipeline:
            continue
        started = at(cert.get("started_at"))
        if since is not None and started < since:
            continue
        if newest is None or started > at(newest.get("started_at")):
            newest = cert
    return newest


#: How long ``ducta ai sentinel watch`` lets one re-run take before stopping it.
DEFAULT_RERUN_TIMEOUT = 4 * 3600.0


class CliExecutor:
    """``ducta start`` in a child process, waited for (at most *timeout* seconds).

    ``ducta start`` runs one node or the whole pipeline, so several nodes are
    re-run one after another, in the order given (dependency order), stopping
    at the first that fails.
    """

    def __init__(self, timeout: Optional[float] = DEFAULT_RERUN_TIMEOUT):
        self.timeout = timeout

    def rerun(
        self, root: Path, env: str, pipeline: str, nodes: List[str], reuse_upstream: bool
    ) -> Optional[RunEvent]:
        event: Optional[RunEvent] = None
        earlier: List[str] = []
        for step in [[n] for n in nodes] or [[]]:
            if event is not None and event.run_id:
                earlier.append(event.run_id)
            event = self._run(root, env, pipeline, step, reuse_upstream)
            if event.status != "success":
                break
        if event is not None:
            # One re-run for Sentinel: the steps before the last are not runs to triage.
            event.earlier_runs = earlier
        return event

    def _run(
        self, root: Path, env: str, pipeline: str, nodes: List[str], reuse_upstream: bool
    ) -> RunEvent:
        from ducta.ai.agents.runs import run_pipeline
        from ducta.ai.agents.store import now

        started = now()
        outcome = run_pipeline(
            root,
            env,
            pipeline,
            nodes=nodes,
            reuse_upstream=reuse_upstream and bool(nodes),
            timeout=self.timeout,
        )
        cert = _newest_certificate(root, env, pipeline, started)
        if cert is not None:
            event = event_from_certificate(env, cert)
        else:
            event = RunEvent(
                env=env,
                pipeline=pipeline,
                status="success" if outcome.ok else "failed",
                error="" if outcome.ok else outcome.output,
            )
        event.exit_code = outcome.exit_code
        event.actor = SENTINEL_USER
        return event


class ServerExecutor:
    """Queued on the API server's execution manager; the outcome arrives through its hook."""

    def __init__(
        self, manager: Any, project_id: Optional[str] = None, user_id: str = SENTINEL_USER
    ):
        self.manager = manager
        self.project_id = project_id
        #: Who the run is attributed to: Sentinel, or the person who asked for it.
        self.user_id = user_id

    def rerun(
        self, root: Path, env: str, pipeline: str, nodes: List[str], reuse_upstream: bool
    ) -> Optional[RunEvent]:
        self.manager.execute(
            source_path=root,
            pipeline_name=pipeline,
            env=env,
            node_names=nodes or None,
            reuse_upstream=reuse_upstream and bool(nodes),
            project_id=self.project_id,
            user_id=self.user_id,
        )
        return None
