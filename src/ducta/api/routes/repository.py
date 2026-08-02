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
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from loguru import logger

from ducta.api.config import Settings
from ducta.api.dependencies import SettingsDep, WorkspaceManagerDep, require_permission
from ducta.api.exceptions import RepositoryAdapterError
from ducta.api.models.repository import (
    PushPullRequest,
    PushPullResponse,
    RepositoryConnectRequest,
    RepositoryInfo,
)
from ducta.api.repository.base import RepositoryAdapter

router = APIRouter(prefix="/repository", tags=["Repository"])

# Path inside the workspace where non-sensitive repo config is persisted
_REPO_CONFIG_FILENAME = ".ducta_repo.json"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/connect",
    response_model=RepositoryInfo,
    summary="Connect workspace to a remote repository",
    status_code=200,
    dependencies=[Depends(require_permission("repository.write"))],
)
async def connect_repository(
    body: RepositoryConnectRequest,
    manager: WorkspaceManagerDep,
    settings: SettingsDep,
) -> RepositoryInfo:
    """Validate and configure a remote repository connection."""
    config = _build_adapter_config(body, settings)

    try:
        adapter = RepositoryAdapter.from_config(config)
    except (ValueError, ImportError) as exc:
        raise HTTPException(status_code=400, detail="Invalid repository configuration") from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Failed to create repository adapter") from exc

    adapter.set_local_path(manager.root)

    try:
        remote_url = adapter.get_remote_url()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not get remote URL: {exc}") from exc

    # Persist non-sensitive config so push/pull can reconstruct the adapter
    stored: Dict[str, Any] = {
        "type": body.type,
        "org": body.org,
        "repo": body.repo,
        "project": body.project,
        "region": body.region,
        "branch": body.branch,
    }
    _save_repo_config(manager.root, stored)
    logger.info(
        "Repository connected: type={type} url={url}",
        type=body.type,
        url=remote_url,
    )

    return RepositoryInfo(
        type=body.type,
        remote_url=remote_url,
        branch=body.branch,
        connected=True,
        warning=_ephemeral_token_warning(body, settings),
    )


@router.get(
    "/",
    response_model=RepositoryInfo,
    summary="Get current repository configuration",
    dependencies=[Depends(require_permission("repository.read"))],
)
async def get_repository(
    manager: WorkspaceManagerDep,
    settings: SettingsDep,
) -> RepositoryInfo:
    """Return the repository configuration for the current workspace."""
    stored = _load_repo_config(manager.root)

    if stored is None:
        local = _local_adapter(manager.root)
        return RepositoryInfo(
            type="local",
            remote_url=local.get_remote_url(),
            branch="main",
            connected=True,
        )

    config = _merge_stored_with_settings(stored, settings)
    connected = True
    remote_url = ""

    try:
        adapter = RepositoryAdapter.from_config(config)
        adapter.set_local_path(manager.root)
        remote_url = adapter.get_remote_url()
    except Exception as exc:
        logger.warning("Could not build adapter from stored config: {exc}", exc=exc)
        connected = False

    return RepositoryInfo(
        type=stored.get("type", "local"),
        remote_url=remote_url,
        branch=stored.get("branch", "main"),
        connected=connected,
    )


@router.post(
    "/push",
    response_model=PushPullResponse,
    summary="Push commits to the configured remote repository",
    dependencies=[Depends(require_permission("repository.write"))],
)
async def push_repository(
    manager: WorkspaceManagerDep,
    settings: SettingsDep,
    body: PushPullRequest = Body(default_factory=PushPullRequest),
) -> PushPullResponse:
    """Push the latest local commits to the remote repository."""
    adapter = _get_adapter(manager.root, settings)
    try:
        adapter.push(body.branch)
    except RepositoryAdapterError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PushPullResponse(
        success=True,
        branch=body.branch,
        message=f"Successfully pushed to '{body.branch}'.",
    )


@router.post(
    "/pull",
    response_model=PushPullResponse,
    summary="Pull changes from the configured remote repository",
    dependencies=[Depends(require_permission("repository.write"))],
)
async def pull_repository(
    manager: WorkspaceManagerDep,
    settings: SettingsDep,
    body: PushPullRequest = Body(default_factory=PushPullRequest),
) -> PushPullResponse:
    """Pull the latest remote changes into the local workspace."""
    adapter = _get_adapter(manager.root, settings)
    try:
        adapter.pull(body.branch)
    except RepositoryAdapterError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PushPullResponse(
        success=True,
        branch=body.branch,
        message=f"Successfully pulled from '{body.branch}'.",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _repo_config_path(workspace_root: Path) -> Path:
    return workspace_root / _REPO_CONFIG_FILENAME


def _save_repo_config(workspace_root: Path, config: Dict[str, Any]) -> None:
    path = _repo_config_path(workspace_root)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    logger.debug("Saved repo config to {path}", path=path)


def _load_repo_config(workspace_root: Path) -> Optional[Dict[str, Any]]:
    path = _repo_config_path(workspace_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read {path}: {exc}", path=path, exc=exc)
        return None


def _ephemeral_token_warning(body: RepositoryConnectRequest, settings: Settings) -> Optional[str]:
    """Warn when the token used for `connect` won't survive to future push/pull.

    Only the non-sensitive parts of the config are persisted to
    ``.ducta_repo.json`` (see `_build_adapter_config`); credentials are always
    re-derived from server-side settings on later requests
    (`_merge_stored_with_settings`). If the caller supplied a token that
    doesn't match the configured env var, `connect` succeeds but the next
    push/pull will silently fail to authenticate.
    """
    env_var_by_type = {"github": "GITHUB_TOKEN", "azure": "AZURE_TOKEN"}
    env_var = env_var_by_type.get(body.type)
    if env_var is None or not body.token:
        return None

    configured_token = settings.github_token if body.type == "github" else settings.azure_token
    if body.token == configured_token:
        return None

    return (
        f"The token you provided is not persisted. Future push/pull operations "
        f"will use the server's {env_var} environment variable instead (or fail "
        f"if it isn't set) — configure {env_var} on the server for this token "
        "to persist across requests."
    )


def _build_adapter_config(body: RepositoryConnectRequest, settings: Settings) -> Dict[str, Any]:
    """Merge request body with settings into an adapter config."""
    config: Dict[str, Any] = {"type": body.type}

    if body.type == "github":
        config["token"] = body.token or settings.github_token or ""
        config["org"] = body.org or settings.github_org or ""
        config["repo"] = body.repo or ""

    elif body.type == "azure":
        config["token"] = body.token or settings.azure_token or ""
        config["org"] = body.org or settings.azure_org or ""
        config["project"] = body.project or settings.azure_project or ""
        config["repo"] = body.repo or ""

    elif body.type == "aws":
        config["region"] = body.region or settings.aws_region or ""
        config["repo"] = body.repo or ""
        config["aws_access_key_id"] = settings.aws_access_key_id
        config["aws_secret_access_key"] = settings.aws_secret_access_key
        config["aws_https_username"] = body.aws_https_username
        config["aws_https_password"] = body.aws_https_password

    # "local" type needs no credentials
    return config


def _merge_stored_with_settings(stored: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    """Re-add credential fields from env vars to a stored config."""
    config: Dict[str, Any] = dict(stored)
    repo_type = stored.get("type", "local")

    if repo_type == "github":
        config["token"] = settings.github_token or ""
    elif repo_type == "azure":
        config["token"] = settings.azure_token or ""
    elif repo_type == "aws":
        config["aws_access_key_id"] = settings.aws_access_key_id
        config["aws_secret_access_key"] = settings.aws_secret_access_key

    return config


def _get_adapter(workspace_root: Path, settings: Settings) -> RepositoryAdapter:
    """Build an adapter from the stored workspace config."""
    stored = _load_repo_config(workspace_root)

    if stored is None:
        return _local_adapter(workspace_root)

    config = _merge_stored_with_settings(stored, settings)
    try:
        adapter = RepositoryAdapter.from_config(config)
    except (ValueError, ImportError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    adapter.set_local_path(workspace_root)
    return adapter


def _local_adapter(workspace_root: Path) -> RepositoryAdapter:
    from ducta.api.repository.local import LocalAdapter  # noqa: PLC0415

    adapter = LocalAdapter()
    adapter.set_local_path(workspace_root)
    return adapter
