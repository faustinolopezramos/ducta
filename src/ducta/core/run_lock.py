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

Run lock: at most one run writes a given output dataset at a time.

Without it, an orchestrator retry that overlaps a still-running attempt — or
two people launching the same backfill — has two processes writing the same
destination, and the result depends on which write lands last.

The lock is keyed by **output dataset**, not by pipeline name: two different
pipelines writing the same table collide just as badly. Keys are acquired in
sorted order so two runs sharing several outputs cannot deadlock.

Two backends:

``local``
    An OS advisory lock (``flock``/``msvcrt``) on a file per key. The OS drops
    it when the process dies, so a crashed run never leaves a lock behind. Only
    meaningful on one host.

``storage``
    A lease file per key, created exclusively and renewed by a heartbeat until
    released. A holder that dies stops renewing; once ``ttl_seconds`` passes the
    lease can be taken over. Works across hosts on any shared filesystem that
    honours ``O_EXCL`` (local disk, NFS, mounted cloud storage) and on S3 via
    conditional writes (``s3://`` lock directory).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger

from ducta.core.errors import ConfigurationError, PipelineLockedError
from ducta.core.locking import try_lock_fd, unlock_fd

BACKEND_LOCAL = "local"
BACKEND_STORAGE = "storage"
BACKENDS = (BACKEND_LOCAL, BACKEND_STORAGE)
ON_CONFLICT_FAIL = "fail"
ON_CONFLICT_WAIT = "wait"
ON_CONFLICT_CHOICES = (ON_CONFLICT_FAIL, ON_CONFLICT_WAIT)
DEFAULT_LOCK_DIR = "${output_path}/${environment}/.ducta/locks"

_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class RunLockSettings:
    enabled: bool = True
    backend: str = BACKEND_LOCAL
    ttl_seconds: int = 300
    on_conflict: str = ON_CONFLICT_FAIL
    wait_timeout_seconds: int = 600
    lock_dir: str = ".ducta/locks"


def lock_filename(key: str) -> str:
    """A filesystem-safe, collision-free file name for ``key``.

    Dataset keys contain dots and may contain characters no filesystem likes;
    the readable prefix is for humans listing the directory, the digest is what
    keeps ``a/b`` and ``a_b`` apart.
    """
    readable = re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:80]
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{readable}.{digest}.lock"


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── lease stores ─────────────────────────────────────────────────────────────


class _LeaseStore:
    """Compare-and-swap storage for small lease documents.

    ``token`` identifies the exact version of a lease a caller read, so a
    replace or delete only succeeds if nobody changed it in between.
    """

    def create(self, name: str, body: bytes) -> Optional[Any]:
        raise NotImplementedError

    def read(self, name: str) -> Optional[Tuple[bytes, Any]]:
        raise NotImplementedError

    def replace(self, name: str, body: bytes, token: Any) -> Optional[Any]:
        raise NotImplementedError

    def delete(self, name: str, token: Any) -> None:
        raise NotImplementedError


class _FileLeaseStore(_LeaseStore):
    """Leases as files. Creation relies on ``O_CREAT | O_EXCL`` being atomic.

    Replace is a rename-based compare-and-swap: move the current file aside,
    check it is the version we expected, then create the new one exclusively.
    If it was not ours, it is put back. The file is briefly absent during a
    replace; a competing ``create`` in that instant wins, and the replacer sees
    its own ``create`` fail and reports the lease as lost — which is the safe
    outcome.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.directory / name

    def create(self, name: str, body: bytes) -> Optional[Any]:
        try:
            fd = os.open(str(self._path(name)), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return None
        try:
            os.write(fd, body)
            os.fsync(fd)
        finally:
            os.close(fd)
        return body

    def read(self, name: str) -> Optional[Tuple[bytes, Any]]:
        try:
            body = self._path(name).read_bytes()
        except FileNotFoundError:
            return None
        return body, body

    def replace(self, name: str, body: bytes, token: Any) -> Optional[Any]:
        path = self._path(name)
        aside = path.with_name(f"{path.name}.{uuid.uuid4().hex}.cas")
        try:
            os.rename(path, aside)
        except FileNotFoundError:
            return None
        if aside.read_bytes() != token:
            # Someone else's lease: put it back untouched.
            try:
                os.link(aside, path)
            except FileExistsError:
                pass
            except OSError:
                self.create(name, aside.read_bytes())
            aside.unlink(missing_ok=True)
            return None
        aside.unlink(missing_ok=True)
        return self.create(name, body)

    def delete(self, name: str, token: Any) -> None:
        path = self._path(name)
        aside = path.with_name(f"{path.name}.{uuid.uuid4().hex}.cas")
        try:
            os.rename(path, aside)
        except FileNotFoundError:
            return
        if aside.read_bytes() != token:
            try:
                os.link(aside, path)
            except FileExistsError:
                pass
            except OSError:
                self.create(name, aside.read_bytes())
        aside.unlink(missing_ok=True)


class _S3LeaseStore(_LeaseStore):
    """Leases as S3 objects, using conditional writes (``If-None-Match`` /
    ``If-Match`` on the ETag) as the compare-and-swap."""

    def __init__(self, uri: str, client: Any = None) -> None:
        match = re.match(r"s3a?://([^/]+)/?(.*)$", uri)
        if not match:
            raise ConfigurationError(f"run_lock: invalid S3 lock directory {uri!r}")
        self.bucket = match.group(1)
        self.prefix = match.group(2).strip("/")
        if client is None:
            try:
                import boto3  # type: ignore
            except ImportError as e:
                raise ConfigurationError(
                    "run_lock: an s3:// lock directory needs boto3 (pip install boto3)"
                ) from e
            client = boto3.client("s3")
        self.client = client

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    @staticmethod
    def _precondition_failed(exc: Exception) -> bool:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        return code in ("PreconditionFailed", "ConditionalRequestConflict", "412", "409")

    def create(self, name: str, body: bytes) -> Optional[Any]:
        try:
            resp = self.client.put_object(
                Bucket=self.bucket, Key=self._key(name), Body=body, IfNoneMatch="*"
            )
        except Exception as e:  # noqa: BLE001
            if self._precondition_failed(e):
                return None
            raise
        return resp.get("ETag")

    def read(self, name: str) -> Optional[Tuple[bytes, Any]]:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self._key(name))
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                return None
            raise
        return resp["Body"].read(), resp.get("ETag")

    def replace(self, name: str, body: bytes, token: Any) -> Optional[Any]:
        try:
            resp = self.client.put_object(
                Bucket=self.bucket, Key=self._key(name), Body=body, IfMatch=token
            )
        except Exception as e:  # noqa: BLE001
            if self._precondition_failed(e):
                return None
            raise
        return resp.get("ETag")

    def delete(self, name: str, token: Any) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(name), IfMatch=token)
        except Exception as e:  # noqa: BLE001
            if not self._precondition_failed(e):
                logger.debug("run_lock: could not delete lease {}: {}", name, e)


# ── per-key locks ────────────────────────────────────────────────────────────


class _KeyLock:
    key: str

    def try_acquire(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """(acquired, current_holder_if_not)."""
        raise NotImplementedError

    def renew(self) -> bool:
        return True

    def release(self) -> None:
        raise NotImplementedError


class _LocalKeyLock(_KeyLock):
    def __init__(self, key: str, directory: Path, owner: Dict[str, Any]) -> None:
        self.key = key
        self.path = directory / lock_filename(key)
        self.owner = owner
        self._fd: Optional[int] = None

    def try_acquire(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o644)
        if not try_lock_fd(fd):
            os.close(fd)
            return False, _parse(self.path.read_bytes() if self.path.exists() else b"")
        # Record who holds it, for the other side's error message.
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, json.dumps({**self.owner, "key": self.key}).encode("utf-8"))
        self._fd = fd
        return True, None

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            os.ftruncate(self._fd, 0)
        except OSError:
            pass
        unlock_fd(self._fd)
        os.close(self._fd)
        self._fd = None


class _LeaseKeyLock(_KeyLock):
    def __init__(
        self, key: str, store: _LeaseStore, owner: Dict[str, Any], ttl_seconds: int
    ) -> None:
        self.key = key
        self.name = lock_filename(key)
        self.store = store
        self.owner = owner
        self.ttl = ttl_seconds
        self._token: Any = None

    def _body(self) -> bytes:
        now = _now()
        doc = {**self.owner, "key": self.key, "renewed_at": _iso(now), "expires_at": now + self.ttl}
        return json.dumps(doc).encode("utf-8")

    def try_acquire(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        token = self.store.create(self.name, self._body())
        if token is not None:
            self._token = token
            return True, None
        current = self.store.read(self.name)
        if current is None:
            # Released between our create and our read: try again next poll.
            return False, None
        body, token = current
        holder = _parse(body)
        expires_at = holder.get("expires_at") if holder else None
        if isinstance(expires_at, (int, float)) and expires_at < _now():
            new_token = self.store.replace(self.name, self._body(), token)
            if new_token is not None:
                logger.warning(
                    "run_lock: took over expired lease on '{}' from run {} (host {}, "
                    "expired {:.0f}s ago) — that run stopped renewing, most likely it died.",
                    self.key,
                    holder.get("run_id"),
                    holder.get("host"),
                    _now() - expires_at,
                )
                self._token = new_token
                return True, None
        return False, holder

    def renew(self) -> bool:
        if self._token is None:
            return False
        new_token = self.store.replace(self.name, self._body(), self._token)
        if new_token is None:
            self._token = None
            return False
        self._token = new_token
        return True

    def release(self) -> None:
        if self._token is not None:
            self.store.delete(self.name, self._token)
            self._token = None


def _parse(body: bytes) -> Dict[str, Any]:
    try:
        doc = json.loads(body.decode("utf-8")) if body else {}
        return doc if isinstance(doc, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


# ── the run lock ─────────────────────────────────────────────────────────────


class RunLock:
    """Exclusive hold on a set of output keys for the duration of one run.

    ``acquire`` raises :class:`PipelineLockedError` when a key is held (after
    waiting, with ``on_conflict: wait``). ``lost`` becomes True if a storage
    lease could not be renewed — another run may then be writing too, and the
    caller should record that as an evidence gap.
    """

    def __init__(
        self,
        settings: RunLockSettings,
        keys: Iterable[str],
        *,
        pipeline: str,
        run_id: str,
        store: Optional[_LeaseStore] = None,
    ) -> None:
        self.settings = settings
        self.pipeline = pipeline
        self.keys = sorted(set(keys))
        self.owner = {
            "run_id": run_id,
            "pipeline": pipeline,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "acquired_at": _iso(_now()),
        }
        self._store = store
        self._locks: List[_KeyLock] = []
        self._held: List[_KeyLock] = []
        self._stop = threading.Event()
        self._heartbeat: Optional[threading.Thread] = None
        self.lost = False

    def _build_locks(self) -> List[_KeyLock]:
        directory = self.settings.lock_dir
        if self.settings.backend == BACKEND_LOCAL:
            if "://" in directory:
                raise ConfigurationError(
                    "run_lock: backend 'local' needs a filesystem lock directory, got "
                    f"{directory!r}; use backend 'storage' for object storage"
                )
            return [_LocalKeyLock(k, Path(directory), self.owner) for k in self.keys]
        store = self._store
        if store is None:
            if directory.startswith(("s3://", "s3a://")):
                store = _S3LeaseStore(directory)
            else:
                store = _FileLeaseStore(Path(directory))
        return [_LeaseKeyLock(k, store, self.owner, self.settings.ttl_seconds) for k in self.keys]

    def acquire(self) -> None:
        if not self.settings.enabled or not self.keys:
            return
        self._locks = self._build_locks()
        deadline = _now() + max(0, self.settings.wait_timeout_seconds)
        waiting_logged = False
        while True:
            blocked_key, holder = self._try_all()
            if blocked_key is None:
                self._start_heartbeat()
                logger.debug(
                    "run_lock: acquired {} key(s) for run {}", len(self.keys), self.owner["run_id"]
                )
                return
            if self.settings.on_conflict != ON_CONFLICT_WAIT or _now() >= deadline:
                raise PipelineLockedError(self.pipeline, blocked_key, holder or None)
            if not waiting_logged:
                logger.info(
                    "run_lock: '{}' is held by run {}; waiting up to {}s",
                    blocked_key,
                    (holder or {}).get("run_id", "?"),
                    self.settings.wait_timeout_seconds,
                )
                waiting_logged = True
            time.sleep(_POLL_SECONDS)

    def _try_all(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Acquire every key in order, or none of them."""
        for lock in self._locks:
            acquired, holder = lock.try_acquire()
            if not acquired:
                self._release_held()
                return lock.key, holder
            self._held.append(lock)
        return None, None

    def _release_held(self) -> None:
        for lock in reversed(self._held):
            try:
                lock.release()
            except Exception as e:  # noqa: BLE001 — releasing must not mask the real outcome
                logger.warning("run_lock: could not release '{}': {}", lock.key, e)
        self._held = []

    def _start_heartbeat(self) -> None:
        if self.settings.backend != BACKEND_STORAGE:
            return
        interval = max(1.0, self.settings.ttl_seconds / 3)

        def beat() -> None:
            while not self._stop.wait(interval):
                for lock in list(self._held):
                    try:
                        renewed = lock.renew()
                    except Exception as e:  # noqa: BLE001
                        logger.warning("run_lock: heartbeat for '{}' failed: {}", lock.key, e)
                        continue
                    if not renewed and not self.lost:
                        self.lost = True
                        logger.error(
                            "run_lock: lost the lease on '{}' — another run may now be "
                            "writing it concurrently. This run's certificate records it.",
                            lock.key,
                        )

        self._heartbeat = threading.Thread(target=beat, name="ducta-run-lock", daemon=True)
        self._heartbeat.start()

    def release(self) -> None:
        self._stop.set()
        if self._heartbeat is not None:
            self._heartbeat.join(timeout=5)
            self._heartbeat = None
        self._release_held()

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


def output_keys(
    context: Any, pipeline: Dict[str, Any], node_name: Optional[str] = None
) -> List[str]:
    """The output datasets a run of ``pipeline`` (or of one node) will write."""
    from ducta.core.utils import extract_pipeline_nodes

    nodes_config = getattr(context, "nodes_config", None) or {}
    if isinstance(context, dict):
        nodes_config = context.get("nodes_config", {}) or {}
    names = [node_name] if node_name else extract_pipeline_nodes(pipeline)
    keys: List[str] = []
    for name in names:
        outputs = (nodes_config.get(name) or {}).get("output") or []
        if isinstance(outputs, str):
            outputs = [outputs]
        keys.extend(str(o) for o in outputs)
    return sorted(set(keys))
