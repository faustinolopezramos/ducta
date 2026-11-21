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
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from ducta.project_store.errors import ValidationError, WorkspaceNotFoundError
from ducta.project_store.fileops import safe_path
from ducta_server.utils.fsio import atomic_write
from ducta_server.utils.git_utils import (
    GIT_AVAILABLE,
    commit_files,
    format_commit,
    get_repo,
    is_git_repo,
    sanitize_git_remote_url,
)
from ducta_server.utils.platform_utils import posix_relative
from ducta_server.utils.validators import validate_identifier


class FileTooLargeError(ValueError):
    """The requested file exceeds ``WorkspaceManager.MAX_READ_BYTES``."""


class SecretFileError(PermissionError):
    """The file holds secrets (``.env``) and the file browser does not serve it."""


class ProtectedPathError(SecretFileError):
    """The path is Ducta's or git's own state (``.git/``, ``.ducta/``), not the project's.

    A subclass of :class:`SecretFileError` so every route that answers 403 for a secrets file
    answers it for these.
    """


#: Folders the file API never writes to. ``.git/config`` takes commands (``core.fsmonitor``,
#: ``core.sshCommand``) that git runs on the next ``git status`` the server makes, and
#: ``.ducta/`` holds the audit trail and the lock the server itself keeps.
_WRITE_PROTECTED_DIRS = frozenset({".git", ".ducta"})
#: Folders the file API never reads: the repository's own files (its config holds remote URLs).
_READ_PROTECTED_DIRS = frozenset({".git"})


def protected_dir(rel_path: str, folders: "frozenset[str]") -> "str | None":
    """The first of *folders* that a component of *rel_path* names (case-insensitively), or None."""
    for part in str(rel_path).replace("\\", "/").split("/"):
        if part.strip().lower() in folders:
            return part.strip().lower()
    return None


#: ``.env`` variants that are templates, not secrets — the browser shows these.
_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template", ".env.dist"})


#: Files that are credentials by name: private keys, keystores, password files.
_SECRET_NAMES = frozenset(
    {
        ".pgpass",
        ".netrc",
        "_netrc",
        ".pypirc",
        ".npmrc",
        ".htpasswd",
        "credentials",  # ~/.aws/credentials copied into a project
        "credentials.json",
        "service-account.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx")


def is_secret_file(name: str) -> bool:
    """Whether a file name holds secrets: a ``.env`` file with real values (``.env``,
    ``.env.local``…), a private key or keystore (``*.pem``, ``*.key``, ``*.jks``, ``*.p12``…)
    or a credentials file (``.pgpass``, ``.netrc``, ``credentials.json``, ``id_rsa``…)."""
    name = str(name).rsplit("/", 1)[-1]
    lower = name.lower()
    if lower == ".env" or lower.startswith(".env."):
        return lower not in _ENV_TEMPLATES
    return lower in _SECRET_NAMES or lower.endswith(_SECRET_SUFFIXES)


def _hidden_in_diff(rel_path: str) -> bool:
    """A path a diff must leave out: what the file API refuses to read."""
    return is_secret_file(rel_path) or protected_dir(rel_path, _READ_PROTECTED_DIRS) is not None


def _diff_without_secrets(
    repo: Any, commit_a: str, commit_b: str, hide: Optional[Callable[[str], bool]] = None
) -> str:
    """``git diff commit_a commit_b`` without the files the file API refuses to read.

    A ``.env`` (or a key) committed once was otherwise handed whole to anyone who can read
    the history. The files are listed first (``-z``: names as they are, unquoted) and
    excluded by literal pathspec, so the diff itself never contains them.
    """
    names = [
        n
        for n in str(repo.git.diff(commit_a, commit_b, "--name-only", "-z", "--no-renames")).split(
            "\0"
        )
        if n
    ]
    hidden = [n for n in names if _hidden_in_diff(n) or (hide is not None and hide(n))]
    if not hidden:
        return str(repo.git.diff(commit_a, commit_b))
    if len(hidden) == len(names):
        return ""
    excludes = [f":(top,exclude,literal){n}" for n in hidden]
    return str(repo.git.diff(commit_a, commit_b, "--", ":/", *excludes))


class WorkspaceManager:
    """Abstraction over a Ducta workspace backed by a local Git repository."""

    def __init__(self, workspace_path: Path, strict: bool = True) -> None:
        from ducta.setting.workspace import normalize_workspace_path

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

    def _project_root(self) -> Optional[Path]:
        from ducta.setting.project.loader import find_project_root

        for candidate in (self._project_path, self.root):
            if candidate is not None:
                found = find_project_root(candidate)
                if found is not None:
                    return found
        return None

    def list_environments(self) -> List[str]:
        """The canonical environments, plus any other the project declares overrides for."""
        from ducta.setting.environments import DEFAULT_ENVIRONMENTS

        envs = list(DEFAULT_ENVIRONMENTS)
        envs += [e for e in self._declared_environments() if e not in envs]
        return envs

    def declared_environments(self) -> List[str]:
        """``base`` plus the environments the project declares overrides for.

        A canonical environment the project does not declare still runs, with
        the base configuration — the environment picker says so.
        """
        return ["base", *[e for e in self._declared_environments() if e != "base"]]

    def _project_document(self) -> Dict[str, Any]:
        """The project's ``ducta.*`` file as data, whichever format it is written in."""
        from ducta.setting.project import files as pf
        from ducta.setting.project.loader import project_file

        root = self._project_root()
        if root is None:
            return {}
        data = pf.load(project_file(root))
        return data if isinstance(data, dict) else {}

    def _declared_environments(self) -> List[str]:
        return [str(e) for e in (self._project_document().get("environments") or {})]

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

    def load_context(self, env: str) -> Any:
        """The Context of this workspace's project for ``env`` (server runs never
        import Python from configuration: ``allow_python_config=False``)."""
        from ducta.runs.context import load_project_context

        return load_project_context(self._project_path or self.root, env)

    # ── Workspace file browser ──────────────────────────────────────────────

    #: Largest file ``read_file`` will load into memory (matches the write cap).
    MAX_READ_BYTES = 10 * 1024 * 1024

    _SKIP_DIRS = frozenset({".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", "dist"})

    def _browsable(self, rel_path: str, *, write: bool = False) -> Path:
        """*rel_path* inside the workspace, refused when it is a secrets file or, to write,
        a path under ``.git/`` or ``.ducta/``."""
        folder = protected_dir(rel_path, _WRITE_PROTECTED_DIRS if write else _READ_PROTECTED_DIRS)
        if folder is not None:
            raise ProtectedPathError(
                f"'{rel_path}' is inside '{folder}/', which is not editable here"
            )
        target = safe_path(self.root, rel_path)
        # A symlink inside the project may lead into one of them.
        for resolved_part in target.relative_to(self.root.resolve()).parts:
            if resolved_part.lower() in (_WRITE_PROTECTED_DIRS if write else _READ_PROTECTED_DIRS):
                raise ProtectedPathError(
                    f"'{rel_path}' is inside '{resolved_part}/', which is not editable here"
                )
        if is_secret_file(target.name):
            raise SecretFileError(f"'{rel_path}' holds secrets; edit it outside Ducta")
        return target

    def ensure_readable(self, rel_path: str) -> Path:
        """Refuse a path the file API would not serve (a ``.env`` file, ``.git/``).

        For callers that return a file's content by other means — the git routes' diffs,
        blame, ``file-at``: they read the file themselves, so without this check a viewer
        got through git what the file browser answers 403.
        """
        return self._browsable(rel_path)

    def ensure_writable(self, rel_path: str) -> Path:
        """Refuse a path the file API would not write (secrets, ``.git/``, ``.ducta/``)."""
        return self._browsable(rel_path, write=True)

    def list_directory(self, rel_path: str = "") -> List[Dict[str, Any]]:
        """Return sorted directory entries (dirs first) for *rel_path* inside the workspace."""
        if rel_path:
            self._browsable(rel_path)  # not .git/; a directory is no secret file
        target = safe_path(self.root, rel_path) if rel_path else self.root
        if not target.is_dir():
            raise ValueError(f"'{rel_path}' is not a directory in this workspace")
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name in self._SKIP_DIRS or (item.is_file() and is_secret_file(item.name)):
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
        target = self._browsable(rel_path)
        if not target.is_file():
            raise ValueError(f"'{rel_path}' is not a file in this workspace")
        size = target.stat().st_size
        if size > self.MAX_READ_BYTES:
            raise FileTooLargeError(
                f"'{rel_path}' is {size} bytes; the file reader serves at most "
                f"{self.MAX_READ_BYTES} bytes"
            )
        return target.read_text(encoding="utf-8", errors="replace")

    def write_file(self, rel_path: str, content: str) -> None:
        """Create or overwrite a file in the workspace atomically."""
        target = self._browsable(rel_path, write=True)
        atomic_write(target, content.encode("utf-8"))

    def delete_file(self, rel_path: str) -> None:
        """Delete a file from the workspace."""
        target = self._browsable(rel_path, write=True)
        if not target.is_file():
            raise ValueError(f"'{rel_path}' is not a file in this workspace")
        target.unlink()

    def get_git_status(self) -> Dict[str, List[str]]:
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            return {"modified": [], "added": [], "deleted": []}
        repo = get_repo(self.root)
        diff_index = repo.index.diff(None)
        return {
            "modified": [str(item.a_path) for item in diff_index if not item.deleted_file],
            "deleted": [str(item.a_path) for item in diff_index if item.deleted_file],
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
        hide: Optional[Callable[[str], bool]] = None,
    ) -> str:
        """``git diff``, without secret files and, given *hide*, without the paths it names."""
        if not GIT_AVAILABLE or not is_git_repo(self.root):
            return ""
        if path:
            safe_path(self.root, path)
        try:
            repo = get_repo(self.root)
            if path:
                return str(repo.git.diff(commit_a, commit_b, "--", path))
            return _diff_without_secrets(repo, commit_a, commit_b, hide)
        except Exception as exc:
            logger.debug("get_git_diff failed: {exc}", exc=exc)
            return ""

    def get_commit_diff(
        self, sha: str, hide: Optional[Callable[[str], bool]] = None
    ) -> tuple[str, str]:
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
        return _diff_without_secrets(repo, parent_sha, sha, hide), parent_sha

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
            blame: Any = repo.blame("HEAD", path) or []
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
            settings = self._project_document().get("settings") or {}
            active_env = settings.get("environment") or settings.get("env")
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
                name = str(reader.get_value("user", "name", "")) or None
            except Exception:
                pass
            try:
                email = str(reader.get_value("user", "email", "")) or None
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
