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

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger  # type: ignore

try:
    from git import GitCommandError, Repo  # type: ignore
    from git.exc import InvalidGitRepositoryError  # type: ignore

    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False
    logger.debug("GitPython not installed - git sync disabled")


class GitSyncError(Exception):
    pass


class GitSyncManager:
    """Manages Git repository operations for workspace synchronization."""

    def __init__(
        self,
        workspace_root: Path,
        auto_commit: bool = True,
        auto_commit_author: str = "Ducta Auto-Commit",
        auto_commit_email: str = "api@ducta.local",
    ):
        self.workspace_root = Path(workspace_root)
        self.auto_commit = auto_commit
        self.auto_commit_author = auto_commit_author
        self.auto_commit_email = auto_commit_email

        self._repo: Optional[Repo] = None
        self._lock = threading.RLock()
        self._last_fetch: Optional[datetime] = None
        self._fetch_interval = 30

        self._initialize_repo()

    def _initialize_repo(self) -> None:
        if not GIT_AVAILABLE:
            return

        try:
            self._repo = Repo(str(self.workspace_root))
            logger.info("GitSyncManager: Initialized repo at {root}", root=self.workspace_root)
        except InvalidGitRepositoryError:
            logger.warning("Not a Git repository: {root}", root=self.workspace_root)
        except Exception as e:
            logger.error("Failed to initialize Git repo: {err}", err=e)

    def is_available(self) -> bool:
        with self._lock:
            return self._repo is not None

    def _require_repo(self) -> Repo:
        if not GIT_AVAILABLE:
            raise GitSyncError("Git not available")
        with self._lock:
            if self._repo is None:
                raise GitSyncError("Git not available")
            return self._repo

    def stage_changes(
        self,
        paths: Optional[List[Path]] = None,
        force: bool = False,
    ) -> int:
        repo = self._require_repo()
        with self._lock:
            try:
                if paths is None:
                    return self._stage_config_changes(repo)
                return self._stage_specific_files(repo, paths, force)
            except GitCommandError as e:
                raise GitSyncError(f"Git command failed: {e}")
            except Exception as e:
                raise GitSyncError(f"Failed to stage changes: {e}")

    def _stage_config_changes(self, repo: Repo) -> int:
        config_path = self.workspace_root / "config"
        if config_path.exists():
            repo.index.add([str(config_path)])
            return len(repo.index.diff("HEAD"))
        return 0

    def _stage_specific_files(self, repo: Repo, paths: List[Path], force: bool) -> int:
        staged = 0
        for path in paths:
            path = Path(path)
            if not force and not path.exists():
                continue
            try:
                repo.index.add([str(path)])
                staged += 1
            except Exception as e:
                logger.warning("Failed to stage {p}: {err}", p=path, err=e)
        return staged

    def auto_commit_if_staged(
        self,
        message: Optional[str] = None,
        author: Optional[Tuple[str, str]] = None,
    ) -> bool:
        if not self.auto_commit or not self.is_available():
            return False

        repo = self._require_repo()
        with self._lock:
            try:
                # Only what is staged is committed — a dirty working tree alone
                # is not something to commit.
                try:
                    if not repo.index.diff("HEAD"):
                        return False
                except Exception:  # noqa: BLE001 — no HEAD yet: anything in the index counts
                    if not repo.index.entries:
                        return False

                from git import Actor

                # The author goes on this commit only — never into the repo's
                # config, where it would replace the user's own identity.
                if author:
                    name, email = author
                else:
                    reader = repo.config_reader()
                    name = reader.get_value("user", "name", self.auto_commit_author)
                    email = reader.get_value("user", "email", self.auto_commit_email)
                actor = Actor(name, email)
                repo.index.commit(
                    message or "Auto: config update via API/CLI", author=actor, committer=actor
                )
                logger.info("Auto-committed: {msg}", msg=message)
                return True
            except GitCommandError as e:
                logger.error("Git commit failed: {err}", err=e)
                raise GitSyncError(f"Commit failed: {e}")
            except Exception as e:
                logger.error("Failed to auto-commit: {err}", err=e)
                raise GitSyncError(f"Auto-commit failed: {e}")

    def status(self) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "staged": [],
                "unstaged": [],
                "untracked": [],
                "branch": "unknown",
                "head": "unknown",
                "available": False,
            }

        repo = self._require_repo()
        with self._lock:
            try:
                staged = [item.a_path for item in repo.index.diff("HEAD")]
                unstaged = [item.a_path for item in repo.index.diff(None)]
                # Every untracked file: a new pipeline or source file is a change
                # to commit as much as an edited one (format 2 has no config/).
                untracked = list(repo.untracked_files)[:1000]

                try:
                    branch = repo.active_branch.name
                except TypeError:
                    branch = "detached"

                return {
                    "staged": staged,
                    "unstaged": unstaged,
                    "untracked": untracked,
                    "branch": branch,
                    "head": repo.head.commit.hexsha[:7],
                    "available": True,
                }
            except Exception as e:
                logger.error("Failed to get Git status: {err}", err=e)
                return {
                    "staged": [],
                    "unstaged": [],
                    "untracked": [],
                    "branch": "error",
                    "head": "error",
                    "available": False,
                    "error": str(e),
                }

    def detect_external_changes(self, force_fetch: bool = False) -> bool:
        if not self.is_available():
            return False

        repo = self._require_repo()
        with self._lock:
            try:
                now = datetime.now()
                if (
                    not force_fetch
                    and self._last_fetch
                    and (now - self._last_fetch).total_seconds() < self._fetch_interval
                ):
                    return False

                origin = repo.remote("origin")
                origin.fetch()
                self._last_fetch = now

                local_commit = repo.head.commit.hexsha

                tracking_branch = None
                try:
                    tracking_branch = repo.active_branch.tracking_branch()
                except TypeError:
                    pass

                if tracking_branch is not None:
                    remote_commit = tracking_branch.commit.hexsha
                else:
                    remote_commit = None
                    for ref_name in ("main", "master"):
                        ref = getattr(origin.refs, ref_name, None)
                        if ref is not None:
                            remote_commit = ref.commit.hexsha
                            break
                    if remote_commit is None:
                        return False

                has_changes = local_commit != remote_commit
                if has_changes:
                    logger.warning(
                        "External changes detected: {local} vs {remote}",
                        local=local_commit[:7],
                        remote=remote_commit[:7],
                    )
                return has_changes

            except (AttributeError, IndexError):
                return False
            except Exception as e:
                logger.debug("Failed to detect external changes: {err}", err=e)
                return False

    def branches(self) -> List[Dict[str, Any]]:
        """Local and remote-tracking branches, each with the commit it points at."""
        repo = self._require_repo()
        with self._lock:
            try:
                current = repo.active_branch.name
            except TypeError:  # detached HEAD
                current = None
            out = [
                {
                    "name": h.name,
                    "sha": h.commit.hexsha,
                    "current": h.name == current,
                    "remote": False,
                }
                for h in repo.heads
            ]
            for remote in repo.remotes:
                for ref in remote.refs:
                    if ref.remote_head == "HEAD":
                        continue
                    out.append(
                        {
                            "name": ref.name,
                            "sha": ref.commit.hexsha,
                            "current": False,
                            "remote": True,
                        }
                    )
            return out

    def file_at(self, rel_path: str, rev: str) -> Optional[str]:
        """*rel_path* as it was at commit *rev*; None when it did not exist there."""
        repo = self._require_repo()
        with self._lock:
            try:
                blob = repo.commit(rev).tree / rel_path
            except (KeyError, ValueError):
                return None
            return blob.data_stream.read().decode("utf-8", "replace")

    def working_diff(self, rel_path: str) -> Dict[str, str]:
        """``{original, modified}``: *rel_path* at HEAD ("" if new) and on disk ("" if deleted)."""
        repo = self._require_repo()
        with self._lock:
            try:
                original = (
                    (repo.head.commit.tree / rel_path).data_stream.read().decode("utf-8", "replace")
                )
            except (KeyError, ValueError):
                original = ""
        path = self.workspace_root / rel_path
        modified = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        return {"original": original, "modified": modified}

    def get_remote_url(self) -> Optional[str]:
        if not self.is_available():
            return None
        repo = self._require_repo()
        with self._lock:
            try:
                return repo.remote("origin").url
            except (AttributeError, ValueError):
                return None

    def get_commit_history(self, max_count: int = 10) -> List[Dict]:
        if not self.is_available():
            return []

        repo = self._require_repo()
        with self._lock:
            try:
                return [
                    {
                        "sha": c.hexsha[:7],
                        "message": c.message.strip(),
                        "author": c.author.name,
                        "date": datetime.fromtimestamp(
                            c.committed_date, tz=timezone.utc
                        ).isoformat(),
                    }
                    for c in repo.iter_commits(max_count=max_count)
                ]
            except Exception as e:
                logger.error("Failed to get commit history: {err}", err=e)
                return []

    def _git_operation(self, operation: str, **kwargs) -> Tuple[bool, str]:
        """Generic helper for pull/push operations."""
        if not self.is_available():
            return False, "Git not available"

        repo = self._require_repo()
        with self._lock:
            try:
                origin = repo.remote("origin")
                try:
                    branch_name = repo.active_branch.name
                except TypeError:
                    return False, f"Cannot {operation} in detached HEAD state"

                if operation == "pull":
                    origin.fetch()
                    repo.git.pull("--rebase", "origin", branch_name)
                    msg = f"Successfully pulled latest changes from origin/{branch_name}"
                else:  # push
                    push_info = origin.push(branch_name)
                    if not push_info:
                        return False, "Push returned no status"
                    info = push_info[0]
                    if info.flags & (info.ERROR | info.REJECTED):
                        return False, f"Push rejected: {info.summary}"
                    msg = f"Successfully pushed to origin/{branch_name}"

                return True, msg
            except GitCommandError as e:
                stderr = e.stderr if hasattr(e, "stderr") else str(e)
                return False, f"{operation.capitalize()} failed: {stderr}"
            except Exception as e:
                return False, f"Unexpected error: {str(e)}"

    def pull_changes(self) -> Tuple[bool, str]:
        return self._git_operation("pull")

    def push_changes(self) -> Tuple[bool, str]:
        return self._git_operation("push")
