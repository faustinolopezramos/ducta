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

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ducta.api.dependencies import (
    ConfigLockManagerDep,
    CurrentUserDep,
    GitSyncManagerDep,
    WorkspaceManagerDep,
    require_permission,
)
from ducta.api.exceptions import http_error_on
from ducta.api.models.git import (
    BlameLine,
    BlameResponse,
    CommitInfo,
    DiffResponse,
    GitIdentityConfig,
    GitIdentityResponse,
    RevertRequest,
    RevertResponse,
)
from ducta.api.models.git_sync import (
    GitChange,
    GitChangesResponse,
    GitCommitRequest,
    GitCommitResponse,
    GitStageRequest,
    GitStageResponse,
    GitSyncStatus,
    GitWorkingDiffResponse,
)
from ducta.api.utils.git_utils import safe_path

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def _validate_sha(sha: str) -> None:
    if not _SHA_RE.match(sha):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid commit SHA: '{sha}'. Expected 7–40 hexadecimal characters.",
        )


def _safe_rel(root, path: str) -> str:
    with http_error_on(400):
        return str(safe_path(root, path).relative_to(root))


def _build_git_status(status: dict) -> GitSyncStatus:
    return GitSyncStatus(
        staged=status.get("staged", []),
        unstaged=status.get("unstaged", []),
        untracked=status.get("untracked", []),
        branch=status.get("branch", "unknown"),
        head=status.get("head", "unknown"),
        available=status.get("available", False),
        error=status.get("error"),
    )


def _validate_git_paths(paths: Optional[list[str]], workspace_root: Path) -> Optional[list[Path]]:
    if paths is None:
        return None
    return [safe_path(workspace_root, p) for p in paths]


# ── Git history routes ────────────────────────────────────────────────────────

router = APIRouter(prefix="/git", tags=["Git"])


class GitLogResponse(BaseModel):
    commits: List[CommitInfo]
    count: int


@router.get(
    "/log", response_model=GitLogResponse, dependencies=[Depends(require_permission("git.read"))]
)
async def git_log(
    manager: WorkspaceManagerDep,
    path: Optional[str] = Query(default=None, description="Filter by file path"),
    limit: int = Query(default=50, ge=1, le=500),
) -> GitLogResponse:
    safe_file_path = _safe_rel(manager.root, path) if path else None
    raw = manager.get_git_log(path=safe_file_path, limit=limit)
    commits = [CommitInfo(**c) for c in raw]
    return GitLogResponse(commits=commits, count=len(commits))


@router.get(
    "/log/{path:path}",
    response_model=GitLogResponse,
    dependencies=[Depends(require_permission("git.read"))],
)
async def git_log_for_file(
    path: str,
    manager: WorkspaceManagerDep,
    limit: int = Query(default=50, ge=1, le=500),
) -> GitLogResponse:
    safe_file_path = _safe_rel(manager.root, path)
    raw = manager.get_git_log(path=safe_file_path, limit=limit)
    commits = [CommitInfo(**c) for c in raw]
    return GitLogResponse(commits=commits, count=len(commits))


@router.get(
    "/commit/{sha}",
    response_model=CommitInfo,
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_commit(sha: str, manager: WorkspaceManagerDep) -> CommitInfo:
    _validate_sha(sha)
    with http_error_on(404):
        return CommitInfo(**manager.get_commit(sha))


@router.get(
    "/diff/{sha}",
    response_model=DiffResponse,
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_commit_diff(sha: str, manager: WorkspaceManagerDep) -> DiffResponse:
    _validate_sha(sha)
    with http_error_on(404):
        diff_text, parent_sha = manager.get_commit_diff(sha)
    return DiffResponse(commit_a=parent_sha, commit_b=sha, diff=diff_text)


@router.get(
    "/diff/{sha1}/{sha2}",
    response_model=DiffResponse,
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_diff_between(
    sha1: str,
    sha2: str,
    manager: WorkspaceManagerDep,
    path: Optional[str] = Query(default=None, description="Restrict diff to a specific file"),
) -> DiffResponse:
    _validate_sha(sha1)
    _validate_sha(sha2)
    safe_file_path = _safe_rel(manager.root, path) if path else None
    diff_text = manager.get_git_diff(sha1, sha2, path=safe_file_path)
    return DiffResponse(commit_a=sha1, commit_b=sha2, path=safe_file_path, diff=diff_text)


@router.post(
    "/revert",
    response_model=RevertResponse,
    dependencies=[Depends(require_permission("git.revert"))],
)
async def revert_file(body: RevertRequest, manager: WorkspaceManagerDep) -> RevertResponse:
    _validate_sha(body.commit)
    safe_file_path = _safe_rel(manager.root, body.path)
    with http_error_on(400):
        new_sha = manager.revert_file(safe_file_path, body.commit, message=body.message)
    return RevertResponse(path=safe_file_path, restored_from=body.commit, new_commit_sha=new_sha)


@router.get(
    "/blame/{path:path}",
    response_model=BlameResponse,
    dependencies=[Depends(require_permission("git.read"))],
)
async def git_blame(path: str, manager: WorkspaceManagerDep) -> BlameResponse:
    safe_file_path = _safe_rel(manager.root, path)
    with http_error_on(400):
        lines = [BlameLine(**line) for line in manager.get_file_blame(safe_file_path)]
    return BlameResponse(path=safe_file_path, lines=lines)


@router.get(
    "/config",
    response_model=GitIdentityResponse,
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_git_config(manager: WorkspaceManagerDep) -> GitIdentityResponse:
    identity = manager.get_git_identity()
    return GitIdentityResponse(
        name=identity.get("name"),
        email=identity.get("email"),
        configured=bool(identity.get("name") and identity.get("email")),
    )


@router.put(
    "/config",
    response_model=GitIdentityResponse,
    dependencies=[Depends(require_permission("git.write"))],
)
async def set_git_config(
    body: GitIdentityConfig, manager: WorkspaceManagerDep
) -> GitIdentityResponse:
    with http_error_on(400):
        manager.set_git_identity(body.name, body.email)
    return GitIdentityResponse(name=body.name, email=body.email, configured=True)


# ── Git Sync operations ───────────────────────────────────────────────────────


class GitPushPullResponse(BaseModel):
    success: bool
    message: str
    git_status: Optional[GitSyncStatus] = None


@router.get(
    "/status",
    response_model=GitSyncStatus,
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_git_status(git_sync: GitSyncManagerDep) -> GitSyncStatus:
    return _build_git_status(git_sync.status())


@router.post(
    "/stage",
    response_model=GitStageResponse,
    dependencies=[Depends(require_permission("git.write"))],
)
async def stage_changes(
    request: GitStageRequest,
    git_sync: GitSyncManagerDep,
    lock_mgr: ConfigLockManagerDep,
    user: CurrentUserDep,
) -> GitStageResponse:
    return await run_in_threadpool(_do_stage, request, git_sync, lock_mgr)


def _do_stage(request: GitStageRequest, git_sync, lock_mgr) -> GitStageResponse:
    # Runs on a worker thread: acquires the file lock (blocking fcntl polling)
    # and calls into GitPython, neither of which is safe on the event loop.
    with lock_mgr.write_lock(timeout=5.0):
        with http_error_on(400):
            paths = _validate_git_paths(request.paths, git_sync.workspace_root)
        staged_count = git_sync.stage_changes(paths=paths, force=request.force)
        status = _build_git_status(git_sync.status())
        return GitStageResponse(
            success=True,
            staged_count=staged_count,
            message=f"Staged {staged_count} files",
            git_status=status,
        )


@router.post(
    "/commit",
    response_model=GitCommitResponse,
    dependencies=[Depends(require_permission("git.write"))],
)
async def commit_changes(
    request: GitCommitRequest,
    git_sync: GitSyncManagerDep,
    lock_mgr: ConfigLockManagerDep,
    user: CurrentUserDep,
) -> GitCommitResponse:
    return await run_in_threadpool(_do_commit, request, git_sync, lock_mgr)


def _do_commit(request: GitCommitRequest, git_sync, lock_mgr) -> GitCommitResponse:
    with lock_mgr.write_lock(timeout=5.0):
        if request.paths is not None:
            with http_error_on(400):
                paths = _validate_git_paths(request.paths, git_sync.workspace_root)
            # force: a deleted file is staged as a deletion.
            git_sync.stage_changes(paths=paths, force=True)
        author = None
        if request.author_name and request.author_email:
            author = (request.author_name, request.author_email)
        committed = git_sync.auto_commit_if_staged(message=request.message, author=author)
        status = _build_git_status(git_sync.status())
        return GitCommitResponse(
            success=committed,
            commit_hash=status.head if committed else None,
            message=(
                f"Committed: {request.message or 'Auto: config update via API'}"
                if committed
                else "No staged changes to commit"
            ),
            git_status=status,
        )


@router.get(
    "/changes",
    response_model=GitChangesResponse,
    summary="Uncommitted changes in the working tree",
    description="Every changed, added, deleted or untracked file, and whether it is staged — "
    "what the UI's Changes panel lists before a commit.",
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_changes(git_sync: GitSyncManagerDep) -> GitChangesResponse:
    return await run_in_threadpool(_changes, git_sync)


def _changes(git_sync) -> GitChangesResponse:
    if not git_sync.is_available():
        return GitChangesResponse(available=False, branch="unknown")
    repo = git_sync._require_repo()
    out: dict[str, GitChange] = {}
    _KIND = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "T": "modified"}
    try:
        for d in repo.index.diff("HEAD", R=True):
            out[d.b_path or d.a_path] = GitChange(
                path=d.b_path or d.a_path, status=_KIND.get(d.change_type, "modified"), staged=True
            )
    except Exception:  # noqa: BLE001 — no HEAD yet: nothing is staged against it
        pass
    for d in repo.index.diff(None):
        path = d.a_path
        if path not in out:
            out[path] = GitChange(
                path=path, status=_KIND.get(d.change_type, "modified"), staged=False
            )
    for path in list(repo.untracked_files)[:1000]:
        out.setdefault(path, GitChange(path=path, status="untracked", staged=False))
    status = git_sync.status()
    return GitChangesResponse(
        available=True,
        branch=status.get("branch", "unknown"),
        changes=sorted(out.values(), key=lambda c: c.path),
    )


@router.get(
    "/working-diff",
    response_model=GitWorkingDiffResponse,
    summary="A file at HEAD and on disk, for a side-by-side diff",
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_working_diff(path: str, git_sync: GitSyncManagerDep) -> GitWorkingDiffResponse:
    with http_error_on(400):
        safe_path(git_sync.workspace_root, path)
    if not git_sync.is_available():
        raise HTTPException(status_code=409, detail="Git is not available in this workspace")
    result = await run_in_threadpool(git_sync.working_diff, path)
    return GitWorkingDiffResponse(path=path, **result)


@router.get(
    "/branches",
    summary="Branches (local and remote-tracking) and the commit each points at",
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_branches(git_sync: GitSyncManagerDep) -> Dict[str, Any]:
    if not git_sync.is_available():
        raise HTTPException(status_code=409, detail="Git is not available in this workspace")
    return {"branches": await run_in_threadpool(git_sync.branches)}


class GitFileAtResponse(BaseModel):
    path: str
    rev: str
    exists: bool
    content: str = ""


@router.get(
    "/file-at",
    response_model=GitFileAtResponse,
    summary="A file as it was at a commit",
    dependencies=[Depends(require_permission("git.read"))],
)
async def get_file_at(path: str, rev: str, git_sync: GitSyncManagerDep) -> GitFileAtResponse:
    with http_error_on(400):
        safe_path(git_sync.workspace_root, path)
        _validate_sha(rev)
    if not git_sync.is_available():
        raise HTTPException(status_code=409, detail="Git is not available in this workspace")
    content = await run_in_threadpool(git_sync.file_at, path, rev)
    return GitFileAtResponse(path=path, rev=rev, exists=content is not None, content=content or "")


@router.post(
    "/pull",
    response_model=GitPushPullResponse,
    dependencies=[Depends(require_permission("git.write"))],
)
async def pull_remote_changes(
    git_sync: GitSyncManagerDep,
    lock_mgr: ConfigLockManagerDep,
    user: CurrentUserDep,
) -> GitPushPullResponse:
    return await run_in_threadpool(_do_pull, git_sync, lock_mgr)


def _do_pull(git_sync, lock_mgr) -> GitPushPullResponse:
    with lock_mgr.write_lock(timeout=20.0):
        success, msg = git_sync.pull_changes()
        return GitPushPullResponse(
            success=success,
            message=msg,
            git_status=_build_git_status(git_sync.status()) if success else None,
        )


@router.post(
    "/push",
    response_model=GitPushPullResponse,
    dependencies=[Depends(require_permission("git.write"))],
)
async def push_local_changes(
    git_sync: GitSyncManagerDep,
    lock_mgr: ConfigLockManagerDep,
    user: CurrentUserDep,
) -> GitPushPullResponse:
    return await run_in_threadpool(_do_push, git_sync, lock_mgr)


def _do_push(git_sync, lock_mgr) -> GitPushPullResponse:
    with lock_mgr.write_lock(timeout=15.0):
        success, msg = git_sync.push_changes()
        return GitPushPullResponse(
            success=success,
            message=msg,
            git_status=_build_git_status(git_sync.status()) if success else None,
        )
