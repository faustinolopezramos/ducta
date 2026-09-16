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

from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from ducta.api.exceptions import ValidationError, WorkspaceNotFoundError
from ducta.api.utils.fsio import atomic_write
from ducta.api.utils.git_utils import (
    GIT_AVAILABLE,
    commit_files,
    format_commit,
    get_repo,
    is_git_repo,
    safe_path,
    sanitize_git_remote_url,
)
from ducta.api.utils.platform_utils import posix_relative
from ducta.api.utils.validators import validate_identifier
from ducta.api.workspace.loaders import load_config_file, load_environment_yaml
from ducta.api.workspace.utils import find_base_global_config, find_config_files


class WorkspaceManager:
    """Abstraction over a Ducta workspace backed by a local Git repository."""

    def __init__(self, workspace_path: Path, strict: bool = True) -> None:
        from ducta.api.workspace.utils import normalize_workspace_path

        original_path = Path(workspace_path).resolve()
        workspace_path = normalize_workspace_path(workspace_path)
        self.root = workspace_path.resolve()

        self._project_path: Optional[Path] = original_path if original_path != self.root else None
        if strict and not self.root.is_dir():
            raise WorkspaceNotFoundError(
                f"Directory not found: {self.root}",
                detail={"path": str(self.root)},
            )
        logger.debug(
            "WorkspaceManager initialised for: {root} (strict={strict})",
            root=self.root,
            strict=strict,
        )

    def get_env_config(self, env: str) -> Dict[str, Path]:
        return find_config_files(self.root, env)

    def list_environments(self) -> List[str]:
        env_settings = load_environment_yaml(self.root)
        return list(env_settings.get("env_config", {}).keys())

    def for_project(self, project_id: Optional[str]) -> "WorkspaceManager":
        """Return a manager scoped to *project_id* within this same workspace
        root, or ``self`` unchanged when no override is given or it just
        names this manager's own root project.
        """
        if not project_id or project_id == self.root.name:
            return self
        try:
            validate_identifier(project_id, field="project_id")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        candidate = self.root / "projects" / project_id
        if not candidate.is_dir():
            return self
        return WorkspaceManager(candidate)

    _CONTEXT_KEY_MAP: Dict[str, str] = {
        "global_config": "global_config_path",
        "pipelines": "pipelines_config_path",
        "nodes": "nodes_config_path",
        "input": "input_config_path",
        "output": "output_config_path",
    }

    def load_context(self, env: str) -> Any:
        from ducta.setting.context_loader import ContextLoader

        config_root = self.root
        if self._project_path is not None:
            _ENV_EXTS = (".yml", ".yaml", ".toml", ".json")
            has_env = any((self._project_path / f"environment{ext}").exists() for ext in _ENV_EXTS)
            if has_env:
                config_root = self._project_path

        config_paths = find_config_files(config_root, env)
        path_dict: Dict[str, str] = {}
        for name, path in config_paths.items():
            original_key = self._CONTEXT_KEY_MAP.get(name, f"{name}_path")
            path_dict[original_key] = str(path)

        # Deep-merge the environment's global config over the base one, exactly
        # as the CLI does — see `find_base_global_config`.
        base_global = find_base_global_config(config_root, env)
        if base_global is not None:
            path_dict["base_global_config_path"] = str(base_global)

        ctx = ContextLoader(allow_python_config=False).load_from_paths(path_dict, env)

        env_dir = self.root / env if (self.root / env).is_dir() else self.root
        for attr, value in (
            ("workspace_root", self.root),
            ("source_path", self.root),
            ("env_dir", env_dir),
            ("path_resolution_base", env_dir),
        ):
            try:
                setattr(ctx, attr, value)
            except Exception:
                pass

        return ctx

    # ── Workspace file browser ──────────────────────────────────────────────

    _SKIP_DIRS = frozenset({".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", "dist"})

    def list_directory(self, rel_path: str = "") -> List[Dict[str, Any]]:
        """Return sorted directory entries (dirs first) for *rel_path* inside the workspace."""
        target = safe_path(self.root, rel_path) if rel_path else self.root
        if not target.is_dir():
            raise ValueError(f"'{rel_path}' is not a directory in this workspace")
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name in self._SKIP_DIRS:
                continue
            rel = posix_relative(item, self.root)
            entries.append(
                {
                    "name": item.name,
                    "path": rel,
                    "type": "file" if item.is_file() else "dir",
                    "size": item.stat().st_size if item.is_file() else None,
                }
            )
        return entries

    def read_file(self, rel_path: str) -> str:
        """Read a text file from the workspace."""
        target = safe_path(self.root, rel_path)
        if not target.is_file():
            raise ValueError(f"'{rel_path}' is not a file in this workspace")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_file(self, rel_path: str, content: str) -> None:
        """Create or overwrite a file in the workspace atomically."""
        target = safe_path(self.root, rel_path)
        atomic_write(target, content.encode("utf-8"))

    def delete_file(self, rel_path: str) -> None:
        """Delete a file from the workspace."""
        target = safe_path(self.root, rel_path)
        if not target.is_file():
            raise ValueError(f"'{rel_path}' is not a file in this workspace")
        target.unlink()

    def get_git_status(self) -> Dict[str, List[str]]:
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            return {"modified": [], "added": [], "deleted": []}
        repo = get_repo(self.root)
        diff_index = repo.index.diff(None)
        return {
            "modified": [item.a_path for item in diff_index if not item.deleted_file],
            "deleted": [item.a_path for item in diff_index if item.deleted_file],
            "added": list(repo.untracked_files),
        }

    def get_git_log(self, path: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            return []
        try:
            repo = get_repo(self.root)
            kwargs: Dict[str, Any] = {"max_count": min(limit, 500)}
            if path:
                kwargs["paths"] = path
            return [format_commit(c) for c in repo.iter_commits(**kwargs)]
        except Exception as exc:
            logger.debug("get_git_log skipped: {exc}", exc=exc)
            return []

    def get_commit(self, sha: str) -> Dict[str, Any]:
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            raise ValueError("Git not available in this workspace")
        repo = get_repo(self.root)
        try:
            commit = repo.commit(sha)
            return format_commit(commit)
        except Exception as exc:
            raise ValueError(f"Commit '{sha}' not found: {exc}") from exc

    def get_git_diff(
        self,
        commit_a: str,
        commit_b: str = "HEAD",
        path: Optional[str] = None,
    ) -> str:
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            return ""
        if path:
            safe_path(self.root, path)
        try:
            repo = get_repo(self.root)
            args = [commit_a, commit_b]
            if path:
                args += ["--", path]
            return repo.git.diff(*args)
        except Exception as exc:
            logger.debug("get_git_diff failed: {exc}", exc=exc)
            return ""

    def get_commit_diff(self, sha: str) -> tuple[str, str]:
        _EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            raise ValueError("Git not available in this workspace")
        repo = get_repo(self.root)
        try:
            commit = repo.commit(sha)
            _ = commit.authored_date
        except Exception as exc:
            raise ValueError(f"Commit '{sha}' not found: {exc}") from exc

        parent_sha = commit.parents[0].hexsha if commit.parents else _EMPTY_TREE
        return repo.git.diff(parent_sha, sha), parent_sha

    def revert_file(self, path: str, commit: str, message: Optional[str] = None) -> str:
        safe_path(self.root, path)
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            raise ValueError("Git not available for revert operation")
        try:
            repo = get_repo(self.root)
            target = repo.commit(commit)
            try:
                blob = target.tree[path]
            except KeyError:
                raise ValueError(f"File '{path}' not found in commit '{commit}'")
            abs_path = self.root / path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(blob.data_stream.read())
            return commit_files(
                self.root,
                [abs_path],
                message or f"revert: restore {path} to {commit[:8]}",
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Revert failed: {exc}") from exc

    def get_file_blame(self, path: str) -> List[Dict[str, Any]]:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        safe_path(self.root, path)
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            return []
        try:
            repo = get_repo(self.root)
            blame = repo.blame("HEAD", path)
            result: List[Dict[str, Any]] = []
            line_number = 1
            for blame_commit, lines in blame:
                for line in lines:
                    content = (
                        line.decode("utf-8", errors="replace")
                        if isinstance(line, bytes)
                        else str(line)
                    )
                    result.append(
                        {
                            "line_number": line_number,
                            "content": content.rstrip("\n"),
                            "sha": blame_commit.hexsha,
                            "author": blame_commit.author.name,
                            "email": blame_commit.author.email,
                            "timestamp": _dt.fromtimestamp(
                                blame_commit.authored_date, tz=_tz.utc
                            ).isoformat(),
                        }
                    )
                    line_number += 1
            return result
        except Exception as exc:
            logger.debug("get_file_blame failed: {exc}", exc=exc)
            return []

    def info(self) -> Dict[str, Any]:
        has_git = is_git_repo(self.root) if GIT_AVAILABLE else (self.root / ".git").exists()
        git_remote: Optional[str] = None
        if has_git and GIT_AVAILABLE:
            try:
                repo = get_repo(self.root)
                if repo.remotes:
                    git_remote = repo.remotes[0].url
            except Exception:
                pass

        if git_remote is not None:
            git_remote = sanitize_git_remote_url(git_remote)

        active_env: Optional[str] = None
        try:
            base_paths = find_config_files(self.root, "base")
            gs_path = base_paths.get("global_config")
            if gs_path and gs_path.exists():
                gs = load_config_file(gs_path)
                active_env = gs.get("environment") or gs.get("env")
        except Exception:
            pass

        return {
            "name": self.root.name,
            "path": str(self.root),
            "has_git": has_git,
            "git_remote": git_remote,
            "environment": active_env,
            "marker": "none",
        }

    def get_git_identity(self) -> Dict[str, Optional[str]]:
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            return {"name": None, "email": None}
        try:
            repo = get_repo(self.root)
            reader = repo.config_reader()
            name: Optional[str] = None
            email: Optional[str] = None
            try:
                name = reader.get_value("user", "name", None)
            except Exception:
                pass
            try:
                email = reader.get_value("user", "email", None)
            except Exception:
                pass
            return {"name": name or None, "email": email or None}
        except Exception as exc:
            logger.debug("get_git_identity failed: {exc}", exc=exc)
            return {"name": None, "email": None}

    def set_git_identity(self, name: str, email: str) -> None:
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            raise ValueError("Git not available in this workspace — cannot write git identity")
        repo = get_repo(self.root)
        with repo.config_writer(config_level="repository") as writer:
            writer.set_value("user", "name", name)
            writer.set_value("user", "email", email)
        logger.info("Git identity set: name={name} email={email}", name=name, email=email)

    def __repr__(self) -> str:
        return f"WorkspaceManager(root={self.root!r})"
