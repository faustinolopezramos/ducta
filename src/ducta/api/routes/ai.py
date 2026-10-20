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

AI pipeline builder over HTTP — what ``ducta ai`` does, for the UI.

* ``/ai/settings``, ``/ai/key``, ``/ai/models`` — the server's model, chosen
  and keyed from the UI. Changing them needs ``ai.configure`` (admins): it is
  the server's choice, and a remote provider receives project configuration.
* ``/projects/{id}/ai/jobs`` — a draft takes minutes with a local model, so it
  runs as a job the client polls; each validation attempt shows up as it ends.
* ``/projects/{id}/ai/drafts`` — the saved drafts; applying one needs
  ``pipeline.write`` and writes files without committing them.

An API key goes in and never comes out: responses carry its source and a mask.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ducta.api.dependencies import CurrentUserDep, get_execution_manager, require_permission
from ducta.api.routes.projects import ProjectServiceDep

router = APIRouter(tags=["AI"])

#: Jobs kept per project (finished ones are dropped oldest first).
_MAX_JOBS = 100
#: Drafts generated at once — a local model serves one request at a time anyway.
_MAX_RUNNING = 2


# ── models ──────────────────────────────────────────────────────────────────


class ProviderInfo(BaseModel):
    name: str
    label: str
    local: bool
    needs_key: bool
    default_base_url: Optional[str] = None
    default_model: Optional[str] = None
    api_key_env: Optional[str] = None


class KeyInfo(BaseModel):
    present: bool
    #: ``env:NAME``, ``keychain`` or ``none``.
    source: str
    masked: str


class AISettingsResponse(BaseModel):
    configured: bool
    provider: Optional[str] = None
    label: Optional[str] = None
    model: Optional[str] = None
    endpoint: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    effort: Optional[str] = None
    max_attempts: Optional[int] = None
    timeout_seconds: Optional[float] = None
    is_local: bool = False
    key: KeyInfo = Field(default_factory=lambda: KeyInfo(present=False, source="none", masked="—"))
    keychain_available: bool = False
    #: Why the settings could not be read, when they could not.
    error: Optional[str] = None
    providers: List[ProviderInfo] = Field(default_factory=list)


class AISettingsUpdate(BaseModel):
    provider: str
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = Field(
        default=None, description="Name of the variable holding the key — never the key"
    )
    effort: Optional[str] = None
    max_attempts: Optional[int] = Field(default=None, ge=1, le=10)
    timeout_seconds: Optional[float] = Field(default=None, ge=10, le=3600)
    context_tokens: Optional[int] = Field(default=None, ge=2048, le=1_000_000)


class AIKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)
    provider: Optional[str] = Field(default=None, description="Default: the configured one")


class ModelsResponse(BaseModel):
    models: List[str]


class JobRequest(BaseModel):
    kind: Literal[
        "new",
        "fix",
        "revise",
        "quality",
        "docs",
        "explain",
        "review",
        "architect_plan",
        "architect_build",
        "sentinel_propose",
        "extend",
        "review_pipeline",
    ] = "new"
    request: Optional[str] = Field(
        default=None,
        max_length=8000,
        description="new, architect_plan: what to build; extend: what the new nodes do",
    )
    pipeline: Optional[str] = Field(
        default=None,
        description="fix: the pipeline to fix; extend: the pipeline to add nodes to; "
        "review_pipeline: the pipeline to review; quality: the node's pipeline",
    )
    node: Optional[str] = Field(
        default=None, description="quality: the node whose output to check; review: the node"
    )
    env: Optional[str] = Field(
        default=None, description="quality, docs: the environment whose data is measured (dev)"
    )
    note: Optional[str] = Field(
        default=None, max_length=8000, description="What is wrong, or what matters to you"
    )
    error: Optional[str] = Field(default=None, max_length=50000, description="fix: a run's error")
    execution_id: Optional[str] = Field(
        default=None, description="fix, explain: the failed execution to take the error from"
    )
    draft_id: Optional[str] = Field(
        default=None,
        description="revise: the draft to change (with `note` saying how); "
        "architect_build: the blueprint draft to build",
    )
    incident_id: Optional[str] = Field(
        default=None,
        description="sentinel_propose: the incident to explain and draft a fix for "
        "(also takes sentinel.read)",
    )
    max_attempts: Optional[int] = Field(default=None, ge=1, le=10)


class AttemptModel(BaseModel):
    number: int
    files: List[str]
    errors: int
    warnings: int
    rejected: List[str]
    usage: Dict[str, int] = Field(default_factory=dict)
    #: The first few problems sent back to the model.
    messages: List[str] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: str
    project_id: str
    kind: str
    status: Literal["running", "done", "failed", "cancelled"]
    started_at: str
    finished_at: Optional[str] = None
    model: Optional[str] = None
    is_local: bool = False
    attempts: List[AttemptModel] = Field(default_factory=list)
    max_attempts: int = 0
    draft_id: Optional[str] = None
    ok: Optional[bool] = None
    error: Optional[str] = None
    #: explain: the explanation, once done (also kept: GET …/ai/explanations/{execution_id}).
    explanation: Optional[str] = None
    #: review, review_pipeline: the findings, once done (also kept:
    #: GET …/ai/reviews/{pipeline}/{node} and GET …/ai/reviews/{pipeline}).
    review: Optional[Dict[str, Any]] = None
    execution_id: Optional[str] = None
    #: architect_plan: what the model needs answered before it can design (ask, then retry
    #: with the answers in `note`).
    questions: Optional[List[str]] = None
    #: sentinel_propose: the incident the proposal is linked to.
    incident_id: Optional[str] = None


class DocsGaps(BaseModel):
    """What has no description: what a `{"kind": "docs"}` job would document."""

    datasets: int
    pipelines: int
    nodes: int


class ExplanationResponse(BaseModel):
    execution_id: str
    text: str
    model: str
    created_at: str


class DraftSummary(BaseModel):
    id: str
    kind: str
    request: str
    pipeline: Optional[str] = None
    #: quality: the node; quality and docs: the environment measured.
    target: Optional[str] = None
    env: Optional[str] = None
    provider: str
    model: str
    created_at: str
    ok: bool
    files: List[str]
    applied_at: Optional[str] = None
    revision_of: Optional[str] = None


class DraftFile(BaseModel):
    path: str
    content: str
    #: ``added`` or ``modified``.
    change: str


class DraftResponse(DraftSummary):
    notes: str = ""
    #: What Ducta checked the draft against, in words (a quality draft's data).
    evidence: str = ""
    new_datasets: List[str] = Field(default_factory=list)
    file_contents: List[DraftFile] = Field(default_factory=list)
    diff: str = ""
    problems: List[Dict[str, Any]] = Field(default_factory=list)
    blocking: List[Dict[str, Any]] = Field(default_factory=list)
    attempts: List[AttemptModel] = Field(default_factory=list)
    raw_answer: str = ""
    #: Files that changed since the draft was made: applying it would be refused.
    stale_files: List[str] = Field(default_factory=list)
    #: blueprint: what the model designed, as Ducta read it (``None`` when it could not).
    blueprint: Optional[Dict[str, Any]] = None
    #: blueprint: the same, as the YAML Ducta reads.
    blueprint_yaml: str = ""
    #: blueprint: what Ducta's checks say deserves a second look (not errors).
    warnings: List[str] = Field(default_factory=list)
    #: extend: what it adds — nodes (with what they read and write), functions, datasets.
    added: Optional[Dict[str, Any]] = None


class ApplyRequest(BaseModel):
    force: bool = Field(default=False, description="Write even if the draft does not validate")


class ApplyResponse(BaseModel):
    draft_id: str
    files: List[str]
    committed: bool = False


# ── settings ────────────────────────────────────────────────────────────────


def _providers() -> List[ProviderInfo]:
    from ducta.ai.config import PRESETS, AIConfig

    return [
        ProviderInfo(
            name=name,
            label=preset.label,
            local=AIConfig(provider=name, base_url=preset.base_url).is_local,
            needs_key=preset.api_key_env is not None,
            default_base_url=preset.base_url,
            default_model=preset.model,
            api_key_env=preset.api_key_env,
        )
        for name, preset in PRESETS.items()
    ]


def _settings() -> AISettingsResponse:
    from ducta.ai.config import load_config
    from ducta.ai.errors import AIError
    from ducta.ai.secrets import keychain_available, resolve_key

    base = AISettingsResponse(
        configured=False, keychain_available=keychain_available(), providers=_providers()
    )
    try:
        config = load_config()
    except AIError as e:
        base.error = e.message
        return base
    key = resolve_key(config)
    return base.model_copy(
        update=dict(
            configured=True,
            provider=config.provider,
            label=config.label,
            model=config.model,
            endpoint=config.endpoint,
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            effort=config.effort,
            max_attempts=config.max_attempts,
            timeout_seconds=config.timeout_seconds,
            is_local=config.is_local,
            key=KeyInfo(present=bool(key.value), source=key.source, masked=key.masked),
            error=None,
        )
    )


@router.get(
    "/ai/settings",
    response_model=AISettingsResponse,
    summary="The server's AI provider, model and key source",
    dependencies=[Depends(require_permission("ai.use"))],
)
async def get_ai_settings() -> AISettingsResponse:
    return await asyncio.to_thread(_settings)


#: Key variables the server may be told to read from the UI: a provider's own,
#: or one named for Ducta. Any other name could be a secret the host keeps for
#: something else (a database password), and the key is sent to the endpoint.
_KEY_ENV = re.compile(r"^DUCTA_AI_[A-Z0-9_]+$")


def _check_update(body: AISettingsUpdate) -> None:
    from ducta.ai.config import PRESETS
    from ducta.ai.errors import AIConfigError

    preset = PRESETS.get(body.provider)
    if preset is None:
        return  # build_config names the choices
    if body.api_key_env and not (
        body.api_key_env == preset.api_key_env or _KEY_ENV.match(body.api_key_env)
    ):
        allowed = " or ".join(
            x for x in (preset.api_key_env and f"{preset.api_key_env}", "DUCTA_AI_<NAME>") if x
        )
        raise AIConfigError(
            f"The key variable must be {allowed}: the server sends its value to the provider"
        )


def _check_endpoint(config: Any) -> None:
    from ducta.ai.errors import AIConfigError

    preset = config.preset
    if config.custom_endpoint and preset.api_key_env and config.api_key_env == preset.api_key_env:
        # OPENAI_API_KEY / ANTHROPIC_API_KEY are for their own endpoints only.
        raise AIConfigError(
            f"Another endpoint for {config.label} needs its own key: set api_key_env to a "
            "DUCTA_AI_<NAME> variable, or keep the key in the keychain for that endpoint"
        )


@router.put(
    "/ai/settings",
    response_model=AISettingsResponse,
    summary="Choose the server's AI provider and model",
    description="Kept in ~/.ducta/ai.toml on the server. Fields left out keep their value; "
    "a field sent as null goes back to the provider's default. Never takes a key: see "
    "PUT /ai/key.",
    dependencies=[Depends(require_permission("ai.configure"))],
)
async def put_ai_settings(body: AISettingsUpdate) -> AISettingsResponse:
    from ducta.ai.config import save_config, update_config

    _check_update(body)
    changes = body.model_dump(include=body.model_fields_set - {"provider"})

    def run() -> None:
        config = update_config(body.provider, changes)
        _check_endpoint(config)
        save_config(config)

    await asyncio.to_thread(run)
    return await asyncio.to_thread(_settings)


def _key_target(provider: Optional[str]) -> Tuple[str, Optional[str]]:
    """The provider and endpoint a key is for: the configured ones, or a preset's own."""
    from ducta.ai.config import PRESETS, load_config
    from ducta.ai.errors import AIConfigError, AIError

    try:
        config = load_config()
    except AIError:
        config = None
    name = provider or (config.provider if config else None)
    if not name or name not in PRESETS:
        raise AIConfigError(f"Unknown provider '{name}'")
    if config is not None and config.provider == name:
        return name, config.base_url
    return name, PRESETS[name].base_url


@router.put(
    "/ai/key",
    response_model=AISettingsResponse,
    summary="Keep an API key in the server's system keychain",
    description="The key is stored, never returned, and only ever sent to the endpoint it "
    "was stored for. A key in the provider's environment variable still wins over it.",
    dependencies=[Depends(require_permission("ai.configure"))],
)
async def put_ai_key(body: AIKeyUpdate) -> AISettingsResponse:
    from ducta.ai.secrets import store_key

    provider, base_url = await asyncio.to_thread(_key_target, body.provider)
    await asyncio.to_thread(store_key, provider, body.api_key, base_url)
    return await asyncio.to_thread(_settings)


@router.delete(
    "/ai/key",
    response_model=AISettingsResponse,
    summary="Remove the API key from the server's keychain",
    dependencies=[Depends(require_permission("ai.configure"))],
)
async def delete_ai_key(provider: Optional[str] = Query(default=None)) -> AISettingsResponse:
    from ducta.ai.secrets import delete_key

    name, base_url = await asyncio.to_thread(_key_target, provider)
    await asyncio.to_thread(delete_key, name, base_url)
    return await asyncio.to_thread(_settings)


@router.get(
    "/ai/models",
    response_model=ModelsResponse,
    summary="The models the configured provider serves (also a connection test)",
    dependencies=[Depends(require_permission("ai.use"))],
)
async def get_ai_models() -> ModelsResponse:
    from ducta.ai.config import load_config
    from ducta.ai.providers import make_provider

    def run() -> List[str]:
        return make_provider(load_config()).list_models()

    return ModelsResponse(models=await asyncio.to_thread(run))


@router.post(
    "/ai/models/test",
    response_model=ModelsResponse,
    summary="Test settings before saving them: the models that provider serves",
    description="Takes the same body as PUT /ai/settings and saves nothing. It reaches the "
    "endpoint given, so it needs ``ai.configure`` like saving it would.",
    dependencies=[Depends(require_permission("ai.configure"))],
)
async def test_ai_models(body: AISettingsUpdate) -> ModelsResponse:
    from ducta.ai.config import update_config
    from ducta.ai.providers import make_provider

    _check_update(body)
    changes = body.model_dump(include=body.model_fields_set - {"provider"})

    def run() -> List[str]:
        config = update_config(body.provider, changes)
        _check_endpoint(config)
        return make_provider(config).list_models()

    return ModelsResponse(models=await asyncio.to_thread(run))


@router.get(
    "/projects/{project_id}/ai/reviews/{pipeline}",
    summary="The last review of a whole pipeline, if there was one",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def get_pipeline_review(
    project_id: str, pipeline: str, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.ai.pipeline_review import load_pipeline_review

    root = _project_root(svc, project_id)
    found = await asyncio.to_thread(load_pipeline_review, root, pipeline)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No review of {pipeline} yet")
    return found.to_dict()


@router.post(
    "/projects/{project_id}/ai/reviews/{pipeline}/checks",
    summary="Ducta's own checks of a whole pipeline, without a model (answers at once)",
    description="Every node's checks plus the pipeline's own (no owner, nodes with no "
    "description, nothing checking its data). Kept as the pipeline's last review. Needs no "
    "AI provider.",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def check_pipeline(
    project_id: str, pipeline: str, svc: ProjectServiceDep, env: str = "dev"
) -> Dict[str, Any]:
    from ducta.ai.pipeline_review import review_pipeline, save_pipeline_review

    root = _project_root(svc, project_id)

    def run() -> Dict[str, Any]:
        found = review_pipeline(root, pipeline, None, env=env)
        save_pipeline_review(root, found)
        return found.to_dict()

    return await asyncio.to_thread(run)


@router.get(
    "/projects/{project_id}/ai/reviews/{pipeline}/{node}",
    summary="The last review of a node, if there was one",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def get_review(
    project_id: str, pipeline: str, node: str, svc: ProjectServiceDep
) -> Dict[str, Any]:
    from ducta.ai.review import load_review

    root = _project_root(svc, project_id)
    found = await asyncio.to_thread(load_review, root, pipeline, node)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No review of {pipeline}.{node} yet")
    return found.to_dict()


@router.post(
    "/projects/{project_id}/ai/reviews/{pipeline}/{node}/checks",
    summary="Ducta's own checks of a node, without a model (answers at once)",
    description="The findings Ducta is certain of: a retried node that appends, runs near "
    "their timeout, I/O or collect() inside the function, a credential in the code… Kept "
    "as the node's last review. Needs no AI provider.",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def check_node(
    project_id: str, pipeline: str, node: str, svc: ProjectServiceDep, env: str = "dev"
) -> Dict[str, Any]:
    from ducta.ai.review import review_node, save_review

    root = _project_root(svc, project_id)

    def run() -> Dict[str, Any]:
        found = review_node(root, pipeline, node, None, env=env)
        save_review(root, found)
        return found.to_dict()

    return await asyncio.to_thread(run)


@router.get(
    "/projects/{project_id}/ai/docs-gaps",
    response_model=DocsGaps,
    summary="How many datasets, pipelines and nodes have no description",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def get_docs_gaps(project_id: str, svc: ProjectServiceDep) -> DocsGaps:
    from ducta.ai.proposals import docs_facts

    root = _project_root(svc, project_id)

    def count() -> DocsGaps:
        try:
            facts = docs_facts(root, columns=False, limit=10_000)
        except Exception:  # noqa: BLE001 — a project that does not load has nothing to count
            return DocsGaps(datasets=0, pipelines=0, nodes=0)
        return DocsGaps(
            datasets=len(facts.datasets),
            pipelines=sum(1 for p in facts.pipelines.values() if p.get("needs")),
            nodes=sum(len(p.get("nodes") or {}) for p in facts.pipelines.values()),
        )

    return await asyncio.to_thread(count)


@router.get(
    "/projects/{project_id}/ai/explanations/{execution_id}",
    response_model=ExplanationResponse,
    summary="The kept explanation of a failed run, if one was asked for",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("execution.read")),
    ],
)
async def get_explanation(
    project_id: str, execution_id: str, svc: ProjectServiceDep
) -> ExplanationResponse:
    from ducta.ai.explain import load_explanation

    root = _project_root(svc, project_id)
    found = await asyncio.to_thread(load_explanation, root, execution_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No explanation for run '{execution_id}'")
    return ExplanationResponse(
        execution_id=execution_id, text=found.text, model=found.model, created_at=found.created_at
    )


# ── jobs ────────────────────────────────────────────────────────────────────

_JOB_ID = re.compile(r"^[0-9a-f]{12}$")


def _jobs_dir(root: Path) -> Path:
    return root / ".ducta" / "ai" / "jobs"


class _Jobs:
    """Draft jobs, written through to ``.ducta/ai/jobs/`` in the project.

    The worker thread that runs a job lives in one server process, but any
    process (another uvicorn worker) can read its progress and ask it to stop:
    the file is the job, and ``<id>.cancel`` next to it is the request to stop.
    A restart loses running jobs (they read as failed), never saved drafts.
    """

    def __init__(self) -> None:
        self._live: Dict[str, Path] = {}  # running here: job id → project root
        self._lock = threading.RLock()

    def running(self) -> int:
        with self._lock:
            return len(self._live)

    def _path(self, root: Path, job_id: str) -> Path:
        return _jobs_dir(root) / f"{job_id}.json"

    def _write(self, root: Path, job: JobResponse, owner: Optional[str]) -> None:
        path = self._path(root, job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"job": job.model_dump(), "owner": owner}), encoding="utf-8")
        tmp.replace(path)

    def add(self, root: Path, job: JobResponse, owner: Optional[str]) -> None:
        with self._lock:
            self._live[job.id] = root
            self._write(root, job, owner)
            finished = sorted(
                (p for p in _jobs_dir(root).glob("*.json") if p.stem not in self._live),
                key=lambda p: p.stat().st_mtime,
            )
            for old in finished[: max(0, len(finished) - _MAX_JOBS)]:
                old.unlink(missing_ok=True)
                old.with_suffix(".cancel").unlink(missing_ok=True)

    def read(self, root: Path, job_id: str) -> Optional[Tuple[JobResponse, Optional[str]]]:
        """The job and who started it, or ``None``."""
        if not _JOB_ID.match(job_id):
            return None
        try:
            data = json.loads(self._path(root, job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        job = JobResponse(**data["job"])
        if job.status == "running":
            with self._lock:
                orphan = job_id not in self._live
            # Running in no process of this server and silent for long: lost to a restart.
            age = datetime.now(timezone.utc).timestamp() - self._path(root, job_id).stat().st_mtime
            if orphan and age > 4 * 3600:
                job.status, job.error = "failed", "The server restarted while drafting"
        return job, data.get("owner")

    def finish(self, root: Path, job_id: str, **fields: Any) -> None:
        """The worker is done: record how, unless the job was stopped meanwhile."""
        with self._lock:
            self._live.pop(job_id, None)
            found = self.read(root, job_id)
            if found is None:
                return
            job, owner = found
            if job.status == "cancelled":
                return
            for key, value in fields.items():
                setattr(job, key, value)
            self._write(root, job, owner)

    def add_attempt(self, root: Path, job_id: str, attempt: AttemptModel) -> None:
        with self._lock:
            found = self.read(root, job_id)
            if found is None:
                return
            job, owner = found
            job.attempts.append(attempt)
            self._write(root, job, owner)

    def cancel(self, root: Path, job_id: str) -> Optional[JobResponse]:
        """Ask the worker to stop, and show the job as stopped from now on."""
        with self._lock:
            self._path(root, job_id).with_suffix(".cancel").touch()
            found = self.read(root, job_id)
            if found is None:
                return None
            job, owner = found
            if job.status == "running":
                job.status, job.error, job.finished_at = "cancelled", "Stopped", _now()
                self._write(root, job, owner)
            return job

    def cancelled(self, root: Path, job_id: str) -> bool:
        return self._path(root, job_id).with_suffix(".cancel").exists()


_jobs = _Jobs()
#: Draft jobs get their own threads: they take minutes, and the event loop's
#: default executor serves every ``asyncio.to_thread`` call of the API.
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_RUNNING, thread_name_prefix="ducta-ai")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _project_root(svc: Any, project_id: str) -> Path:
    return Path(svc.store(project_id).root)


def _format_run_errors(execution: Any, summary: Optional[Dict[str, Any]]) -> str:
    """A failed execution's errors as text the model can read."""
    parts: List[str] = []
    for err in (summary or {}).get("errors") or []:
        head = " ".join(
            str(err.get(k)) for k in ("node_id", "error_type", "message") if err.get(k)
        ).strip()
        trace = str(err.get("traceback") or "")[-3000:]
        parts.append(head + ("\n" + trace if trace else ""))
    if not parts and getattr(execution, "error", None):
        parts.append(str(execution.error))
    return "\n\n".join(parts)


@router.post(
    "/projects/{project_id}/ai/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a draft (a new pipeline, a fix, a node's checks, descriptions) or an explanation",
    description="Returns at once; poll GET …/ai/jobs/{job_id}. A draft is saved and validated "
    "but not written; an explanation (kind `explain`) changes nothing and is kept per run.",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("project.read")),
    ],
)
async def start_job(
    project_id: str,
    body: JobRequest,
    svc: ProjectServiceDep,
    request: Request,
    current_user: CurrentUserDep,
) -> JobResponse:
    from ducta.ai.builder import fix, generate, load_draft, revise, save_draft
    from ducta.ai.config import load_config
    from ducta.ai.errors import AICancelledError, AIConfigError, AIError, AINotFoundError
    from ducta.ai.explain import explain_failure, save_explanation
    from ducta.ai.proposals import propose_docs, propose_quality
    from ducta.ai.providers import make_provider

    root = _project_root(svc, project_id)
    if body.kind == "new" and not (body.request or "").strip():
        raise AIConfigError("Describe the pipeline to build")
    if body.kind == "fix" and not body.pipeline:
        raise AIConfigError("Name the pipeline to fix")
    if body.kind == "quality" and not (body.pipeline and body.node):
        raise AIConfigError("Name the pipeline and the node whose checks to propose")
    if body.kind == "review" and not (body.pipeline and body.node):
        raise AIConfigError("Name the pipeline and the node to review")
    if body.kind == "review_pipeline" and not body.pipeline:
        raise AIConfigError("Name the pipeline to review")
    if body.kind == "extend" and not (body.pipeline and (body.request or "").strip()):
        raise AIConfigError("Name the pipeline and say what the new nodes should do")
    if body.kind == "explain" and not body.execution_id:
        raise AIConfigError("Name the failed execution to explain")
    if body.kind == "architect_plan" and not (body.request or "").strip():
        raise AIConfigError("Describe what to build")
    if body.kind == "sentinel_propose":
        if current_user is not None and not current_user.has_permission("sentinel.read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission 'sentinel.read' required",
            )
        from ducta.ai.agents.sentinel.incidents import Incidents

        if (
            not body.incident_id
            or (await asyncio.to_thread(Incidents(root).get, body.incident_id)) is None
        ):
            raise AINotFoundError(f"No incident {body.incident_id or ''}".strip())
    previous = None
    if body.kind == "architect_build":
        if not body.draft_id:
            raise AIConfigError("Name the blueprint draft to build")
        previous = await asyncio.to_thread(load_draft, root, body.draft_id)
        if previous.kind != "blueprint":
            raise AIConfigError(f"Draft {previous.id} is not a blueprint")
    if body.kind == "revise":
        if not body.draft_id or not (body.note or "").strip():
            raise AIConfigError("Name the draft to revise and say what to change")
        previous = await asyncio.to_thread(load_draft, root, body.draft_id)

    error = body.error or ""
    diagnosis: Dict[str, Any] = {}
    if body.kind == "explain":
        from ducta.api.routes.execution import build_diagnosis

        exec_manager = get_execution_manager(request)
        user_id = current_user.id if current_user else None
        execution = await exec_manager.load_execution(body.execution_id or "", user_id=user_id)
        diagnosis = await asyncio.to_thread(build_diagnosis, execution, exec_manager, root)
        summary = exec_manager.get_execution_errors(body.execution_id or "", user_id=user_id)
        error = _format_run_errors(execution, summary)
    if body.kind == "fix" and body.execution_id:
        # Only now: the execution manager is not needed to draft anything else.
        exec_manager = get_execution_manager(request)
        user_id = current_user.id if current_user else None
        execution = await exec_manager.load_execution(body.execution_id, user_id=user_id)
        summary = exec_manager.get_execution_errors(body.execution_id, user_id=user_id)
        error = (error + "\n\n" + _format_run_errors(execution, summary)).strip()

    config = await asyncio.to_thread(load_config)
    config.require_model()
    provider = make_provider(config)
    if _jobs.running() >= _MAX_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Other drafts are being generated; try again when they finish",
        )

    job = JobResponse(
        id=uuid.uuid4().hex[:12],
        project_id=project_id,
        kind=body.kind,
        status="running",
        started_at=_now(),
        model=config.model,
        is_local=config.is_local,
        max_attempts=0
        if body.kind in ("explain", "review", "review_pipeline")
        else body.max_attempts or config.max_attempts,
        execution_id=body.execution_id if body.kind == "explain" else None,
        incident_id=body.incident_id if body.kind == "sentinel_propose" else None,
    )
    await asyncio.to_thread(_jobs.add, root, job, _owner(current_user))

    def report(attempt: Any) -> None:
        _jobs.add_attempt(root, job.id, AttemptModel(**attempt.__dict__))

    def stop() -> bool:
        return _jobs.cancelled(root, job.id)

    def work() -> None:
        try:
            if body.kind == "sentinel_propose":
                from ducta.ai.agents.sentinel.propose import propose_for

                who = str(
                    getattr(current_user, "username", None)
                    or getattr(current_user, "id", None)
                    or "user"
                )
                linked = propose_for(
                    root,
                    body.incident_id or "",
                    provider=provider,
                    requested_by=who,
                    should_stop=stop,
                )
                _jobs.finish(
                    root,
                    job.id,
                    status="done",
                    ok=bool(linked.get("explanation") or linked.get("draft")),
                    draft_id=linked.get("draft"),
                    finished_at=_now(),
                )
                return
            if body.kind == "review_pipeline":
                from ducta.ai.pipeline_review import review_pipeline, save_pipeline_review

                reviewed = review_pipeline(
                    root,
                    body.pipeline or "",
                    provider,
                    env=body.env or "dev",
                    note=body.note or "",
                )
                if stop():
                    raise AICancelledError("Stopped")
                save_pipeline_review(root, reviewed)
                _jobs.finish(
                    root,
                    job.id,
                    status="done",
                    ok=True,
                    review=reviewed.to_dict(),
                    model=reviewed.model,
                    finished_at=_now(),
                )
                return
            if body.kind == "review":
                from ducta.ai.review import review_node, save_review

                found = review_node(
                    root,
                    body.pipeline or "",
                    body.node or "",
                    provider,
                    env=body.env or "dev",
                    note=body.note or "",
                )
                if stop():
                    raise AICancelledError("Stopped")
                save_review(root, found)
                _jobs.finish(
                    root,
                    job.id,
                    status="done",
                    ok=True,
                    review=found.to_dict(),
                    model=found.model,
                    finished_at=_now(),
                )
                return
            if body.kind == "explain":
                explanation = explain_failure(
                    root, diagnosis, error, provider, note=body.note or ""
                )
                if stop():
                    raise AICancelledError("Stopped")
                save_explanation(root, body.execution_id or "", explanation)
                _jobs.finish(
                    root,
                    job.id,
                    status="done",
                    ok=True,
                    explanation=explanation.text,
                    model=explanation.model,
                    finished_at=_now(),
                )
                return
            if body.kind == "quality":
                draft = propose_quality(
                    root,
                    body.pipeline or "",
                    body.node or "",
                    provider,
                    env=body.env or "dev",
                    note=body.note or "",
                    max_attempts=body.max_attempts,
                    on_attempt=report,
                    should_stop=stop,
                )
            elif body.kind == "docs":
                draft = propose_docs(
                    root,
                    provider,
                    env=body.env or "dev",
                    note=body.note or "",
                    max_attempts=body.max_attempts,
                    on_attempt=report,
                    should_stop=stop,
                )
            elif body.kind == "architect_plan":
                from ducta.ai.agents.architect.design import NeedsAnswers, design

                try:
                    draft = design(
                        root,
                        body.request or "",
                        provider,
                        note=body.note or "",
                        max_attempts=body.max_attempts,
                        on_attempt=report,
                        should_stop=stop,
                    )
                except NeedsAnswers as asked:
                    _jobs.finish(
                        root,
                        job.id,
                        status="done",
                        ok=False,
                        questions=asked.questions,
                        finished_at=_now(),
                    )
                    return
            elif body.kind == "architect_build" and previous is not None:
                from ducta.ai.agents.architect.build import build
                from ducta.ai.agents.architect.design import blueprint_of

                draft = build(
                    root,
                    blueprint_of(previous),
                    provider,
                    blueprint_id=previous.id,
                    max_attempts=body.max_attempts,
                    on_attempt=report,
                    should_stop=stop,
                )
            elif body.kind == "extend":
                from ducta.ai.extend import extend

                draft = extend(
                    root,
                    body.pipeline or "",
                    body.request or "",
                    provider,
                    max_attempts=body.max_attempts,
                    on_attempt=report,
                    should_stop=stop,
                )
            elif body.kind == "new":
                draft = generate(
                    root,
                    body.request or "",
                    provider,
                    max_attempts=body.max_attempts,
                    on_attempt=report,
                    should_stop=stop,
                )
            elif body.kind == "revise" and previous is not None:
                draft = revise(
                    root,
                    previous,
                    body.note or "",
                    provider,
                    max_attempts=body.max_attempts,
                    on_attempt=report,
                    should_stop=stop,
                )
            else:
                draft = fix(
                    root,
                    body.pipeline or "",
                    provider,
                    note=body.note or "",
                    error=error,
                    max_attempts=body.max_attempts,
                    on_attempt=report,
                    should_stop=stop,
                )
            if stop():
                raise AICancelledError("Stopped")
            save_draft(root, draft)
            _jobs.finish(
                root, job.id, status="done", draft_id=draft.id, ok=draft.ok, finished_at=_now()
            )
        except AICancelledError as e:
            _jobs.finish(root, job.id, status="cancelled", error=e.message, finished_at=_now())
        except AIError as e:
            _jobs.finish(root, job.id, status="failed", error=e.message, finished_at=_now())
        except Exception as e:  # noqa: BLE001 — a job never takes the server down
            _jobs.finish(
                root, job.id, status="failed", error=f"Unexpected error: {e}", finished_at=_now()
            )

    _EXECUTOR.submit(work)
    return job


def _owner(user: Any) -> Optional[str]:
    return str(user.id) if user is not None and getattr(user, "id", None) is not None else None


def _visible_job(root: Path, project_id: str, job_id: str, user: Any) -> JobResponse:
    """The job, if it is this project's and *user* started it (or configures AI)."""
    found = _jobs.read(root, job_id)
    if found is not None:
        job, owner = found
        mine = owner is None or owner == _owner(user) or user.has_permission("ai.configure")
        if job.project_id == project_id and mine:
            return job
    raise HTTPException(status_code=404, detail=f"No AI job '{job_id}'")


@router.get(
    "/projects/{project_id}/ai/jobs/{job_id}",
    response_model=JobResponse,
    summary="A draft job: its attempts so far, and its draft when done",
    dependencies=[Depends(require_permission("ai.use"))],
)
async def get_job(
    project_id: str, job_id: str, svc: ProjectServiceDep, current_user: CurrentUserDep
) -> JobResponse:
    root = _project_root(svc, project_id)
    return await asyncio.to_thread(_visible_job, root, project_id, job_id, current_user)


@router.delete(
    "/projects/{project_id}/ai/jobs/{job_id}",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Stop a draft job",
    description="The job reads as cancelled at once and no draft is saved; a request already "
    "sent to the model is not interrupted, but no further one is made.",
    dependencies=[Depends(require_permission("ai.use"))],
)
async def cancel_job(
    project_id: str, job_id: str, svc: ProjectServiceDep, current_user: CurrentUserDep
) -> JobResponse:
    root = _project_root(svc, project_id)
    job = await asyncio.to_thread(_visible_job, root, project_id, job_id, current_user)
    if job.status != "running":
        return job
    return await asyncio.to_thread(_jobs.cancel, root, job_id) or job


# ── drafts ──────────────────────────────────────────────────────────────────


def _summary(draft: Any) -> DraftSummary:
    return DraftSummary(
        id=draft.id,
        kind=draft.kind,
        request=draft.request,
        pipeline=draft.pipeline,
        target=draft.target,
        env=draft.env,
        provider=draft.provider,
        model=draft.model,
        created_at=draft.created_at,
        ok=draft.ok,
        files=list(draft.files),
        applied_at=draft.applied_at,
        revision_of=draft.revision_of,
    )


@router.get(
    "/projects/{project_id}/ai/drafts",
    response_model=List[DraftSummary],
    summary="The project's AI drafts, newest first",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def list_ai_drafts(
    project_id: str, svc: ProjectServiceDep, limit: int = Query(default=50, ge=1, le=200)
) -> List[DraftSummary]:
    from ducta.ai.builder import list_drafts

    root = _project_root(svc, project_id)
    return [_summary(d) for d in await asyncio.to_thread(list_drafts, root, limit)]


@router.get(
    "/projects/{project_id}/ai/drafts/{draft_id}",
    response_model=DraftResponse,
    summary="One draft: its files, diff against the project, problems and attempts",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def get_ai_draft(project_id: str, draft_id: str, svc: ProjectServiceDep) -> DraftResponse:
    from ducta.ai.builder import _read, _sha, load_draft

    root = _project_root(svc, project_id)

    def build() -> DraftResponse:
        draft = load_draft(root, draft_id)
        stale = (
            []
            if draft.applied_at
            else [rel for rel, sha in draft.base.items() if _sha(_read(root / rel)) != sha]
        )
        return DraftResponse(
            **_summary(draft).model_dump(),
            notes=draft.notes,
            evidence=draft.evidence,
            new_datasets=draft.new_datasets,
            file_contents=[
                DraftFile(
                    path=rel,
                    content=text,
                    change="modified" if draft.base.get(rel) else "added",
                )
                for rel, text in draft.files.items()
            ],
            diff="" if draft.applied_at else draft.diff(root),
            problems=draft.problems,
            blocking=draft.blocking,
            attempts=[AttemptModel(**a.__dict__) for a in draft.attempts],
            raw_answer=draft.raw_answer,
            stale_files=stale,
            **_blueprint_fields(draft),
            added=_extension_added(root, draft),
        )

    return await asyncio.to_thread(build)


def _extension_added(root: Path, draft: Any) -> Optional[Dict[str, Any]]:
    if draft.kind != "extend" or draft.applied_at:
        return None
    from ducta.ai.extend import extension_summary

    return extension_summary(root, draft)


def _blueprint_fields(draft: Any) -> Dict[str, Any]:
    """A blueprint draft's design, read by Ducta — what the UI shows instead of files."""
    if draft.kind != "blueprint":
        return {}
    from ducta.ai.agents.architect.design import blueprint_of
    from ducta.ai.errors import AIError

    warnings = [w for w in (draft.evidence or "").split("; ") if w]
    try:
        bp = blueprint_of(draft)
    except AIError:
        return {"warnings": warnings}
    return {"blueprint": bp.to_dict(), "blueprint_yaml": bp.to_yaml(), "warnings": warnings}


@router.post(
    "/projects/{project_id}/ai/drafts/{draft_id}/apply",
    response_model=ApplyResponse,
    summary="Write a draft's files to the project",
    description="Refused (409) if a file it touches changed since it was made, or (400) if — "
    "checked again now, against the project as it is — it does not validate and `force` is "
    "not set. Not committed.",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.write")),
    ],
)
async def apply_ai_draft(
    project_id: str, draft_id: str, body: ApplyRequest, svc: ProjectServiceDep
) -> ApplyResponse:
    from ducta.ai.builder import apply_draft, load_draft

    root = _project_root(svc, project_id)

    def run() -> List[str]:
        return apply_draft(root, load_draft(root, draft_id), force=body.force)

    files = await asyncio.to_thread(run)
    return ApplyResponse(draft_id=draft_id, files=files)


@router.delete(
    "/projects/{project_id}/ai/drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard a draft",
    dependencies=[
        Depends(require_permission("ai.use")),
        Depends(require_permission("pipeline.read")),
    ],
)
async def delete_ai_draft(project_id: str, draft_id: str, svc: ProjectServiceDep) -> None:
    from ducta.ai.builder import delete_draft

    root = _project_root(svc, project_id)
    await asyncio.to_thread(delete_draft, root, draft_id)
