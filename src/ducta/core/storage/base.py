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
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
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
        target_dir = self._resolve_path(prefix) if prefix else self.root_dir
        if not target_dir.exists():
            return []
        if target_dir.is_file():
            return [prefix]
        results: List[str] = []
        for p in target_dir.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(self.root_dir))
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
        full = self._full_key(key)
        self._get_client().delete_object(Bucket=self.bucket, Key=full)
        return True

    def exists(self, key: str) -> bool:
        full = self._full_key(key)
        try:
            self._get_client().head_object(Bucket=self.bucket, Key=full)
            return True
        except Exception:
            return False

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


def get_storage_backend(backend_type: Optional[str] = None) -> StorageBackend:
    """Factory function returning configured StorageBackend singleton."""
    global _storage_instance
    if _storage_instance is not None and backend_type is None:
        return _storage_instance

    btype = (backend_type or os.getenv("DUCTA_STORAGE_BACKEND", "local")).lower()

    if btype in ("s3", "minio"):
        bucket = os.getenv("DUCTA_STORAGE_BUCKET", "ducta-artifacts")
        prefix = os.getenv("DUCTA_STORAGE_PREFIX", "")
        backend = S3StorageBackend(bucket=bucket, prefix=prefix)
        logger.info(f"Initialized S3StorageBackend (bucket={bucket})")
    else:
        root_dir = os.getenv("DUCTA_STORAGE_PATH")
        path_obj = Path(root_dir) if root_dir else None
        backend = LocalStorageBackend(root_dir=path_obj)
        logger.info(f"Initialized LocalStorageBackend (path={backend.root_dir})")

    if backend_type is None:
        _storage_instance = backend
    return backend
