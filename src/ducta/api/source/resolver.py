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

import hashlib
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Dict, List, Optional

from loguru import logger

from ducta.api.source.models import ResolvedSource, SourceInfo
from ducta.api.utils.git_utils import sanitize_git_remote_url
from ducta.api.utils.validators import URLValidationError, validate_git_url
from ducta.api.workspace.utils import CONFIG_EXTENSIONS, has_config_file

_MAX_CLONE_LOCKS = 256


@dataclass
class _CloneLockEntry:
    lock: threading.Lock
    in_use: bool = False
    last_used: float = 0.0


_clone_url_locks: Dict[str, _CloneLockEntry] = {}
_clone_url_locks_mutex = threading.Lock()


def _prune_clone_locks_locked() -> None:
    if len(_clone_url_locks) < _MAX_CLONE_LOCKS:
        return
    evictable = [
        (key, entry)
        for key, entry in _clone_url_locks.items()
        if not entry.in_use and not entry.lock.locked()
    ]
    if not evictable:
        return
    evict_key, _ = min(evictable, key=lambda item: item[1].last_used)
    del _clone_url_locks[evict_key]


def _get_clone_entry(url: str) -> _CloneLockEntry:
    with _clone_url_locks_mutex:
        entry = _clone_url_locks.get(url)
        if entry is not None:
            return entry
        _prune_clone_locks_locked()
        entry = _CloneLockEntry(lock=threading.Lock(), last_used=time.monotonic())
        _clone_url_locks[url] = entry
        return entry


@contextmanager
def _clone_url_lock(url: str):
    entry = _get_clone_entry(url)
    entry.lock.acquire()
    try:
        with _clone_url_locks_mutex:
            entry.in_use = True
            entry.last_used = time.monotonic()
        yield
    finally:
        with _clone_url_locks_mutex:
            entry.in_use = False
            entry.last_used = time.monotonic()
        entry.lock.release()


_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")
_WINDOWS_UNC_RE = re.compile(r"^(\\\\|//)[^\\/]+[\\/][^\\/]+")

# Injected via env (GIT_CONFIG_*) rather than a `-c` CLI flag: GitPython's
# `Repo.clone_from` treats `-c`/`--config` as an unsafe clone option and
# raises unless `allow_unsafe_options=True`, which would also disable its
# other clone-option safety checks. A redirect could otherwise re-point the
# connection at a host this resolver already rejected (the internal-range /
# allow-list check in `_enforce_clone_host_allowlist` only inspects the
# original URL).
_NO_REDIRECT_GIT_ENV: Dict[str, str] = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "http.followRedirects",
    "GIT_CONFIG_VALUE_0": "false",
}


class SourceResolver:
    """Resolve a user-provided source (local path or Git URL) to a local directory."""

    CLONES_DIR = Path.home() / ".ducta" / "clones"

    @classmethod
    def resolve(cls, source: str) -> ResolvedSource:
        source = cls._normalize_source_input(source)
        if not source:
            raise ValueError("Source path or URL cannot be empty")

        pull_failed = False
        if cls.is_git_url(source):
            cls._enforce_clone_host_allowlist(source)
            local_path, pull_failed = cls._clone_or_update(source)
            source_type = "git"
        else:
            local_path = cls.resolve_local(source)
            source_type = "local"

        return ResolvedSource(
            path=local_path,
            source_type=source_type,
            original_source=source,
            has_git=(local_path / ".git").exists(),
            has_environment_yaml=(local_path / "environment.yaml").exists()
            or (local_path / "environment.yml").exists(),
            pull_failed=pull_failed,
        )

    @classmethod
    def get_info(cls, source: str) -> SourceInfo:
        resolved = cls.resolve(source)

        git_remote: Optional[str] = None
        if resolved.has_git:
            try:
                from ducta.api.utils.git_utils import get_repo

                repo = get_repo(resolved.path)
                if repo.remotes:
                    git_remote = sanitize_git_remote_url(repo.remotes[0].url)
            except Exception as exc:
                logger.debug("Could not read git remote: {exc}", exc=exc)

        environments: List[str] = []
        if resolved.has_environment_yaml:
            try:
                from ducta.api.workspace.loaders import load_environment_yaml

                env_data = load_environment_yaml(resolved.path)
                environments = list(env_data.get("env_config", {}).keys())
            except Exception as exc:
                logger.debug("Could not load environments: {exc}", exc=exc)

        config_files: List[str] = []
        config_dir = resolved.path / "config"
        if config_dir.is_dir():
            for f in config_dir.rglob("*"):
                if f.is_file() and f.suffix in CONFIG_EXTENSIONS:
                    config_files.append(str(f.relative_to(resolved.path)))

        projects: List[str] = []
        projects_dir = resolved.path / "projects"
        if projects_dir.is_dir():
            for project_dir in sorted(projects_dir.iterdir()):
                if project_dir.is_dir() and (
                    has_config_file(project_dir, "environment")
                    or has_config_file(project_dir, "ducta")
                ):
                    projects.append(project_dir.name)

        return SourceInfo(
            name=resolved.path.name,
            path=str(resolved.path),
            source_type=resolved.source_type,
            has_git=resolved.has_git,
            git_remote=git_remote,
            has_environment_yaml=resolved.has_environment_yaml,
            environments=environments,
            config_files=config_files,
            projects=projects,
        )

    #: How far up from the starting directory to look for an enclosing workspace.
    _MAX_WORKSPACE_WALK_UP: ClassVar[int] = 5

    #: Files whose presence marks a directory as a Ducta workspace root.
    _WORKSPACE_MARKERS: ClassVar[tuple[str, ...]] = (
        "environment.yaml",
        "environment.yml",
        "environment.toml",
        "environment.json",
        "ducta.yaml",
        "ducta.yml",
    )

    @classmethod
    def _looks_like_workspace(cls, path: Path) -> bool:
        """Mirrors what `normalize_workspace_path` already treats as a root.

        The `projects/` case is not optional: a multi-project workspace holds
        its environment files inside `projects/<name>/` and has none of its own,
        which is exactly the layout `ducta ui` is normally launched into.
        """
        try:
            if any((path / name).exists() for name in cls._WORKSPACE_MARKERS):
                return True
            return (path / "config").is_dir() or (path / "projects").is_dir()
        except OSError:
            return False

    @classmethod
    def _confinement_base(cls) -> Path:
        """The directory a local source has to live inside.

        This used to be the process cwd, full stop, which contradicted the rest
        of the system: `normalize_workspace_path` and `_detect_ducta_workspace`
        both walk *upward* to find a workspace, and `ducta ui` is normally run
        from inside a project. Launching from `<workspace>/projects/<name>` and
        then opening `<workspace>` — the ordinary case — was rejected as a
        traversal attempt, taking all 100+ source-dependent endpoints with it.

        The base is now the outermost enclosing *workspace*, so a run started
        anywhere inside a workspace can address the whole of it and nothing
        beyond. When there is no workspace above the starting point, the cwd
        remains the base and behaviour is unchanged.
        """
        start_raw = os.environ.get("DUCTA_WORKSPACE") or ""
        start: Optional[Path] = None
        if start_raw.strip():
            try:
                candidate = Path(start_raw.strip()).expanduser().resolve()
                if candidate.is_dir():
                    start = candidate
            except OSError:
                start = None
        if start is None:
            start = Path.cwd()

        base = start
        candidate = start
        home = Path.home()
        for _ in range(cls._MAX_WORKSPACE_WALK_UP):
            parent = candidate.parent
            if parent == candidate:
                break
            # Never treat $HOME or a filesystem root as a workspace: a stray
            # `~/config` directory must not open the entire home directory.
            if parent == home or parent == Path(parent.anchor):
                break
            candidate = parent
            if cls._looks_like_workspace(candidate):
                base = candidate
        return base

    @staticmethod
    def resolve_local(raw_path: str) -> Path:
        normalized = SourceResolver._normalize_local_path(raw_path)
        # Expand user (~) but NOT environment variables (security)
        expanded = os.path.expanduser(normalized)
        resolved = Path(expanded).resolve()

        if not resolved.exists():
            raise ValueError(f"Path does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Path is not a directory: {resolved}")

        # `source_path` resolved here ends up inserted into `sys.path` and
        # imported from by execution/runner.py — `ModuleIsolationManager` only
        # does sys.modules bookkeeping, it is not a sandbox (see isolation.py).
        # Absolute paths used to skip the relative-to-base confinement
        # entirely and rely only on a denylist of a handful of sensitive
        # directories (/etc, /proc, /root, ...), which meant "any other
        # readable directory on the server's filesystem" was accepted as a
        # workspace. Always confining to a real base (the server process's
        # cwd, same as the relative-path case below) turns that into a real
        # whitelist. This intentionally removes the "open any external
        # project folder" convenience in exchange for closing that gap.
        base = SourceResolver._confinement_base()
        try:
            from ducta.console.core import SecurityValidator

            SecurityValidator.validate_path(base, resolved)
        except Exception as exc:
            # "Path traversal attempt blocked" reads as an accusation when the
            # cause is almost always a workspace/server mismatch. Say what the
            # server can actually reach and how to change it.
            if resolved.is_relative_to(base):
                raise ValueError(f"Path validation failed: {exc}") from exc
            raise ValueError(
                f"'{resolved}' is outside the workspace this server can reach "
                f"('{base}'). Restart the server from that directory, run "
                f"`ducta ui --source {resolved}`, or pick a source inside it."
            ) from exc

        return resolved

    @classmethod
    def _clone_or_update(cls, git_url: str) -> tuple[Path, bool]:
        """Clone or update a Git repository. Returns (path, pull_failed)."""
        try:
            from git import Repo
        except ImportError as exc:
            raise RuntimeError(
                "GitPython is required for Git clone operations. Install with: pip install gitpython"
            ) from exc

        clone_dir = cls._clone_path(git_url)
        pull_failed = False

        with _clone_url_lock(git_url):
            # Re-validate immediately before the network call, not just once at
            # entry (SourceResolver.resolve): DNS can change between the two,
            # and GitPython does its own independent resolution when it connects.
            # This doesn't eliminate the TOCTOU window (GitPython's resolution is
            # still a separate step we don't control) but shrinks it to the
            # smallest span possible without intercepting GitPython's transport.
            cls._enforce_clone_host_allowlist(git_url)

            if clone_dir.exists() and (clone_dir / ".git").exists():
                logger.info("Updating existing clone: {path}", path=clone_dir)
                try:
                    repo = Repo(str(clone_dir))
                    if repo.remotes:
                        with repo.git.custom_environment(**_NO_REDIRECT_GIT_ENV):
                            repo.remotes.origin.pull(no_tags=True)
                except Exception as exc:
                    logger.error(
                        "Git pull failed for {url} (using existing clone): {exc}",
                        url=git_url,
                        exc=exc,
                    )
                    pull_failed = True
            else:
                logger.info("Cloning {url} -> {path}", url=git_url, path=clone_dir)
                clone_dir.parent.mkdir(parents=True, exist_ok=True)
                try:
                    Repo.clone_from(
                        git_url,
                        str(clone_dir),
                        env=_NO_REDIRECT_GIT_ENV,
                        no_tags=True,
                    )
                except Exception as exc:
                    if clone_dir.exists():
                        import shutil

                        try:
                            shutil.rmtree(clone_dir)
                        except Exception:
                            pass
                    raise RuntimeError(f"Failed to clone repository: {exc}") from exc

        return clone_dir.resolve(), pull_failed

    @classmethod
    def _clone_path(cls, git_url: str) -> Path:
        repo_name = cls._extract_repo_name(git_url)
        url_hash = hashlib.sha256(git_url.encode()).hexdigest()[:8]
        return cls.CLONES_DIR / f"{repo_name}-{url_hash}"

    @staticmethod
    def _extract_repo_name(git_url: str) -> str:
        name = git_url.rstrip("/")
        if name.endswith(".git"):
            name = name[:-4]
        name = name.split("/")[-1]
        if ":" in name:
            name = name.split(":")[-1].split("/")[-1]
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return name or "repo"

    @staticmethod
    def _extract_git_host(git_url: str) -> Optional[str]:
        """Return the lowercase hostname of a Git URL (HTTPS or scp-style SSH)."""
        from urllib.parse import urlparse

        url = git_url.strip()
        if "://" not in url and "@" in url:
            # scp-style: user@host:path/to/repo.git or user@host.com:22/path/to/repo.git
            host_part = url.split("@", 1)[1]
            host = host_part.split(":", 1)[0]
            if ":" in host:
                host = host.split(":", 1)[0]
            host = host.strip("[]")
            return host.lower() if host else None

        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname.lower()
        return None

    @classmethod
    def _enforce_clone_host_allowlist(cls, git_url: str) -> None:
        """Guard clone sources against SSRF / arbitrary-clone abuse.

        Behavior:
        * When ``git_clone_allowed_hosts`` is set, only those hosts are permitted
          (an explicitly allow-listed host bypasses the internal-range check below,
          so you can intentionally allow an internal mirror).
        * When the allow-list is empty (default), public hosts are permitted but
          internal / non-routable targets (loopback, private, link-local such as the
          cloud metadata endpoint 169.254.169.254, reserved, multicast) are rejected.
        """
        from ducta.api.config import get_settings

        host = cls._extract_git_host(git_url)
        allowed = get_settings().git_clone_allowed_hosts
        if allowed:
            allowed_lower = {h.lower() for h in allowed}
            if host is None or host not in allowed_lower:
                raise ValueError(
                    f"Git host '{host}' is not allowed. Permitted hosts: "
                    f"{', '.join(sorted(allowed_lower))}"
                )
            return  # explicitly allow-listed — caller opted in, skip range check
        cls._reject_internal_host(host)

    @staticmethod
    def _reject_internal_host(host: Optional[str]) -> None:
        """Reject hosts that resolve to internal / non-routable IP addresses."""
        import ipaddress
        import socket

        if not host:
            raise ValueError("Cannot determine Git clone host for SSRF validation")

        try:
            candidates = [ipaddress.ip_address(host)]
        except ValueError:
            # Not an IP literal — resolve the hostname to every address it maps to.
            try:
                infos = socket.getaddrinfo(host, None)
            except OSError as exc:
                raise ValueError(f"Cannot resolve Git clone host '{host}': {exc}") from exc
            candidates = []
            for info in infos:
                try:
                    candidates.append(ipaddress.ip_address(info[4][0]))
                except ValueError:
                    continue

        for ip in candidates:
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise ValueError(
                    f"Refusing to clone from internal/non-routable host '{host}' ({ip}). "
                    "Add it to git_clone_allowed_hosts to allow this explicitly."
                )

    @classmethod
    def is_git_url(cls, source: str) -> bool:
        try:
            validate_git_url(source)
            return True
        except URLValidationError:
            return False

    @staticmethod
    def _normalize_source_input(source: str) -> str:
        value = source.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1].strip()
        return value

    @staticmethod
    def _normalize_local_path(raw_path: str) -> str:
        path = SourceResolver._normalize_source_input(raw_path)

        if os.name == "nt":
            if _WINDOWS_DRIVE_RE.match(path) or _WINDOWS_UNC_RE.match(path):
                path = path.replace("/", "\\")
                path = re.sub(r"\\{3,}", r"\\\\", path)
                return path
            return path.replace("/", "\\")

        if path.startswith(("~/", "/", "./", "../")):
            path = path.replace("\\", "/")
            path = re.sub(r"/{2,}", "/", path)

        return path
