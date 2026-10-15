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

Sentinel inside the API server: the hook every finished run goes through,
and the periodic pass (``sentinel_scan_minutes``). Neither ever raises: a
run's bookkeeping and the server must not depend on Sentinel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

#: Sentinel's proposals (model calls, minutes each) get a thread of their own,
#: one at a time: neither a run's bookkeeping nor the API's threads wait on them.
_PROPOSALS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ducta-sentinel")


def _enabled(root: Path) -> bool:
    from ducta.ai.agents.sentinel.policy import Settings

    settings = Settings.of(root)
    return settings is not None and settings.policy.enabled


def on_run_finished(source_path: Any, project_id: Optional[str], record: Dict[str, Any]) -> None:
    """Triage a run the server just finished (sample runs never reach here)."""
    try:
        root = Path(source_path).resolve()
        if not _enabled(root):
            return
        from ducta.ai.agents.sentinel.actions import ServerExecutor
        from ducta.ai.agents.sentinel.engine import Sentinel
        from ducta.ai.agents.sentinel.triage import event_from_execution
        from ducta.api.execution.manager import get_execution_manager
        from ducta.api.routes.execution import run_errors

        errors = run_errors(str(record.get("id"))) if record.get("status") != "success" else []
        sentinel = Sentinel(
            root,
            ServerExecutor(get_execution_manager(), project_id),
            project_id=project_id,
            run_later=_PROPOSALS.submit,
        )
        report = sentinel.on_run_finished(event_from_execution(record, errors))
        if report.opened or report.actions or report.escalated:
            logger.info("Sentinel {}: {}", project_id or root.name, report.to_dict())
    except Exception as e:  # noqa: BLE001 — never break a run's bookkeeping
        logger.warning("Sentinel did not triage run {}: {}", record.get("id"), e)


async def sentinel_watch(workspace: Any, interval_seconds: float) -> None:
    """A Sentinel pass over every project that enabled it, every *interval_seconds*."""
    import asyncio

    from ducta.ai.agents.sentinel.actions import ServerExecutor
    from ducta.ai.agents.sentinel.engine import Sentinel, project_envs
    from ducta.api.execution.manager import get_execution_manager
    from ducta.api.services.project import ProjectService

    while True:
        try:
            svc = ProjectService(Path(workspace))

            def run_all() -> None:
                for item in svc.list_projects_paginated(limit=10_000).projects:
                    if getattr(item, "config_status", "ok") == "invalid":
                        continue
                    try:
                        store = svc.store(item.id)
                        if store is None or not _enabled(store.root):
                            continue
                        executor = ServerExecutor(get_execution_manager(), item.id)
                        Sentinel(
                            store.root, executor, project_id=item.id, run_later=_PROPOSALS.submit
                        ).run_once(project_envs(store.root))
                    except Exception as e:  # noqa: BLE001 — one project must not stop the others
                        logger.warning("Sentinel pass over {} failed: {}", item.id, e)

            await asyncio.to_thread(run_all)
        except Exception as e:  # noqa: BLE001
            logger.warning("Sentinel watch pass failed: {}", e)
        await asyncio.sleep(interval_seconds)
