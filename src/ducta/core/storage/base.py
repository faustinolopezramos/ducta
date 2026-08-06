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

import os
import tempfile
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional

from loguru import logger


class StorageBackend(ABC):
    """Abstract interface for object & artifact storage backends."""

    @abstractmethod
    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Store bytes at the given object key and return URI / key."""
        pass

    @abstractmethod
    def get_object(self, key: str) -> bytes:
        """Retrieve bytes stored at the given object key."""
        pass

    @abstractmethod
    def delete_object(self, key: str) -> bool:
        """Delete object stored at key."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if object key exists."""
        pass

    @abstractmethod
    def list_objects(self, prefix: str = "") -> List[str]:
        """List all object keys under prefix."""
        pass


class LocalStorageBackend(StorageBackend):
    """Local filesystem implementation of StorageBackend."""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        self.root_dir = (root_dir or Path.home() / ".ducta" / "storage").resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        clean_key = key.lstrip("/")
        target = (self.root_dir / clean_key).resolve()
        if target != self.root_dir and self.root_dir not in target.parents:
            raise ValueError(f"Path traversal detected: {key}")
        return target

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        target = self._resolve_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        return str(target)

    def get_object(self, key: str) -> bytes:
        target = self._resolve_path(key)
        if not target.is_file():
            raise FileNotFoundError(f"Storage object '{key}' not found at {target}")
        return target.read_bytes()

    def delete_object(self, key: str) -> bool:
        target = self._resolve_path(key)
        if target.is_file():
            target.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        target = self._resolve_path(key)
        return target.is_file()

    def list_objects(self, prefix: str = "") -> List[str]:
        """List object keys starting with *prefix*."""
        clean_prefix = prefix.lstrip("/")

        base = self._resolve_path(clean_prefix) if clean_prefix else self.root_dir
        if not base.is_dir():
            base = base.parent
        if not base.is_dir() or (base != self.root_dir and self.root_dir not in base.parents):
            return []

        results: List[str] = []
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(self.root_dir))
            if rel.startswith(clean_prefix):
                results.append(rel)
        return sorted(results)


class S3StorageBackend(StorageBackend):
    """AWS S3 / MinIO compatible object storage backend."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: Optional[str] = None,
        region_name: Optional[str] = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url or os.getenv("AWS_S3_ENDPOINT_URL")
        self.region_name = region_name or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # type: ignore

                self._client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    region_name=self.region_name,
                )
            except ImportError:
                raise RuntimeError(
                    "boto3 is required for S3StorageBackend. Install with: pip install boto3"
                )
        return self._client

    def _full_key(self, key: str) -> str:
        k = key.lstrip("/")
        return f"{self.prefix}/{k}" if self.prefix else k

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        full = self._full_key(key)
        self._get_client().put_object(
            Bucket=self.bucket,
            Key=full,
            Body=data,
            ContentType=content_type,
        )
        return f"s3://{self.bucket}/{full}"

    def get_object(self, key: str) -> bytes:
        full = self._full_key(key)
        res = self._get_client().get_object(Bucket=self.bucket, Key=full)
        return res["Body"].read()

    def delete_object(self, key: str) -> bool:
        """Delete an object; False when it did not exist."""
        if not self.exists(key):
            return False
        full = self._full_key(key)
        self._get_client().delete_object(Bucket=self.bucket, Key=full)
        return True

    def exists(self, key: str) -> bool:
        """True if the key exists. Raises on errors that are not "not found"."""
        full = self._full_key(key)
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=full)
            return True
        except Exception as exc:
            status = getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
            error_code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if status == 404 or error_code in ("404", "NoSuchKey", "NotFound"):
                return False
            logger.error("S3 head_object failed for '{}' (not a 404): {}", full, exc)
            raise

    def list_objects(self, prefix: str = "") -> List[str]:
        full_prefix = self._full_key(prefix)
        paginator = self._get_client().get_paginator("list_objects_v2")
        keys: List[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                k = obj["Key"]
                if self.prefix and k.startswith(self.prefix + "/"):
                    k = k[len(self.prefix) + 1 :]
                keys.append(k)
        return sorted(keys)


_storage_instance: Optional[StorageBackend] = None
_storage_lock = threading.Lock()


def _build_storage_backend(backend_type: Optional[str]) -> StorageBackend:
    """Construct a backend from *backend_type* (or the DUCTA_STORAGE_* env)."""
    btype = (backend_type or os.getenv("DUCTA_STORAGE_BACKEND", "local")).lower()

    if btype in ("s3", "minio"):
        bucket = os.getenv("DUCTA_STORAGE_BUCKET", "ducta-artifacts")
        prefix = os.getenv("DUCTA_STORAGE_PREFIX", "")
        backend: StorageBackend = S3StorageBackend(bucket=bucket, prefix=prefix)
        logger.info(f"Initialized S3StorageBackend (bucket={bucket})")
    else:
        root_dir = os.getenv("DUCTA_STORAGE_PATH")
        path_obj = Path(root_dir) if root_dir else None
        backend = LocalStorageBackend(root_dir=path_obj)
        logger.info(f"Initialized LocalStorageBackend (path={backend.root_dir})")

    return backend


def get_storage_backend(backend_type: Optional[str] = None) -> StorageBackend:
    """Factory function returning configured StorageBackend singleton."""
    global _storage_instance

    if backend_type is not None:
        return _build_storage_backend(backend_type)

    if _storage_instance is not None:
        return _storage_instance

    with _storage_lock:
        if _storage_instance is None:
            _storage_instance = _build_storage_backend(None)
    return _storage_instance
