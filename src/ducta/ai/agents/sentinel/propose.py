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

L2: for a failure a person must fix, the model explains it and drafts a fix.

Both are kept and linked to the incident — the explanation per run
(``ducta ai explain``'s store), the fix as an ordinary draft — and **neither
is applied**: Sentinel never writes a project file. Every safeguard of
``ducta ai`` holds (masked errors, a file with a credential never sent to a
remote model).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ducta.ai.agents.sentinel.incidents import Incident
from ducta.ai.agents.sentinel.triage import RunEvent
from ducta.ai.errors import AIError

ACTOR = "sentinel"


def propose(
    root: Path,
    incident: Incident,
    event: RunEvent,
    diagnosis: Dict[str, Any],
    policy: Any,
    provider: Any = None,
    *,
    requested: bool = False,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, Optional[str]]:
    """Explain and draft for *incident*; what was linked. A model failure is noted, not raised.

    *requested*: a person asked for it — both are made, whatever
    ``sentinel.propose`` says Sentinel does on its own. Unasked, a remote model
    is used only with ``sentinel.propose.remote``: it would receive the
    pipeline's code and the run's error without anyone deciding to send them.
    """
    from ducta.ai.agents.model import optional_provider
    from ducta.ai.errors import AICancelledError

    out: Dict[str, Optional[str]] = {"explanation": None, "draft": None}
    explain = requested or policy.propose.explain
    fix_draft = requested or policy.propose.fix_draft
    if not (explain or fix_draft):
        return out
    if provider is None:
        provider, why = optional_provider()
        if provider is None:
            incident.note(ACTOR, "propose", f"no proposal: no AI model ({why})")
            return out
    if not requested and not provider.config.is_local and not policy.propose.remote:
        incident.note(
            ACTOR,
            "propose",
            f"no proposal: the model is remote ({provider.config.label}) and "
            "sentinel.propose.remote is off — ask for one, or turn it on",
        )
        return out
    run_id = event.run_id or incident.last_run_id or incident.id
    if explain:
        try:
            from ducta.ai.explain import explain_failure, save_explanation

            explanation = explain_failure(root, diagnosis, event.error, provider)
            save_explanation(root, run_id, explanation)
            out["explanation"] = run_id
            incident.links["explanation"] = run_id
            incident.note(
                ACTOR, "explain", explanation.text.splitlines()[0][:200] if explanation.text else ""
            )
        except AIError as e:
            incident.note(ACTOR, "explain", f"not explained: {e.message}")
    if fix_draft and incident.runbook == "propose_fix":
        if should_stop and should_stop():
            raise AICancelledError("Stopped")
        try:
            from ducta.ai.builder import fix, save_draft

            draft = fix(root, event.pipeline, provider, error=event.error, should_stop=should_stop)
            save_draft(root, draft)
            out["draft"] = draft.id
            incident.links["draft"] = draft.id
            state = "validates" if draft.ok else "does not validate yet"
            incident.note(
                ACTOR,
                "draft",
                f"fix draft {draft.id} ({state}); review it with `ducta ai apply {draft.id}`",
            )
        except AICancelledError:
            raise
        except AIError as e:
            incident.note(ACTOR, "draft", f"no fix drafted: {e.message}")
    return out


def propose_for(
    root: Path,
    incident_id: str,
    event: Optional[RunEvent] = None,
    *,
    provider: Any = None,
    requested_by: Optional[str] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, Optional[str]]:
    """:func:`propose` for the incident on disk, its result merged back under the lock.

    The model works on a copy, without the engine lock (it takes minutes);
    what it adds — links and timeline lines — is then written onto the
    incident as it is *now*, so a resolve or a re-run recorded meanwhile is kept.
    *requested_by*: the person who asked (both proposals are made).
    """
    from ducta.ai.agents.sentinel.engine import LOCK_WAIT, engine_lock
    from ducta.ai.agents.sentinel.incidents import Incident, Incidents
    from ducta.ai.agents.sentinel.policy import Settings
    from ducta.ai.errors import AIConfigError, AINotFoundError

    incidents = Incidents(root)
    found = incidents.get(incident_id)
    if found is None:
        raise AINotFoundError(f"No incident {incident_id}")
    settings = Settings.of(root)
    if settings is None:
        raise AIConfigError("The project does not load: fix it before asking for a proposal")
    work = Incident.from_dict(found.to_dict())
    if requested_by:
        work.note(requested_by, "propose", "proposal asked for by a person")
        if work.runbook not in ("propose_fix", "propose_quality"):
            work.runbook = "propose_fix"
    before = len(found.timeline)
    if event is None:
        event = RunEvent(
            env=work.env,
            pipeline=work.pipeline,
            status="failed",
            run_id=work.last_run_id,
            error=str(work.diagnosis.get("message") or ""),
        )
    out = propose(
        root,
        work,
        event,
        work.diagnosis,
        settings.policy,
        provider,
        requested=bool(requested_by),
        should_stop=should_stop,
    )
    with engine_lock(root, wait=LOCK_WAIT):
        fresh = incidents.get(incident_id) or work
        fresh.links.update(work.links)
        fresh.timeline += work.timeline[before:]
        fresh.updated_at = work.updated_at
        if requested_by and fresh.runbook != work.runbook and fresh.active:
            fresh.runbook = work.runbook
        incidents.save(fresh)
    return out
