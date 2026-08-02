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
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pandas as pd  # type: ignore
from loguru import logger  # type: ignore

from ducta.mlrun.exceptions import MLOpsException, StorageBackendError
from ducta.mlrun.resilience import (
    STORAGE_RETRY_CONFIG,
    CircuitBreaker,
    CircuitBreakerConfig,
    RetryConfig,
    with_retry,
)
from ducta.mlrun.validators import PathValidator


class DiskSpaceError(StorageBackendError):
    """Raised when disk space is insufficient."""

    pass


@dataclass
class StorageMetadata:
    """Metadata for stored objects."""

    path: str
    created_at: str
    updated_at: str
    size_bytes: Optional[int] = None
    format: str = "parquet"
    tags: Optional[Dict[str, str]] = None
    checksum: Optional[str] = None

    def __post_init__(self):
        """Initialize default values."""
        if self.tags is None:
            self.tags = {}

    @classmethod
    def create(
        cls,
        path: str,
        format: str = "parquet",
        size_bytes: Optional[int] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> "StorageMetadata":
        """Factory method for creating metadata with timestamps."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            path=path,
            created_at=now,
            updated_at=now,
            size_bytes=size_bytes,
            format=format,
            tags=tags,
        )


class StorageBackendRegistry:
    """
    Registry for storage backends to enable dynamic registration.
    v2.1+: Promotes Open-Closed Principle for storage providers.
    """

    _backends: Dict[str, type[StorageBackend]] = {}

    @classmethod
    def register(cls, name: str, backend_cls: type[StorageBackend]) -> None:
        """Register a new storage backend."""
        cls._backends[name.lower()] = backend_cls
        # Only log if specifically requested or via trace
        logger.trace(f"Registered storage backend: {name}")

    @classmethod
    def get(cls, name: str) -> type[StorageBackend]:
        """Get a storage backend class by name."""
        backend_cls = cls._backends.get(name.lower())
        if not backend_cls:
            available = ", ".join(cls._backends.keys())
            raise ValueError(f"Storage backend '{name}' not found. Available: {available}")
        return backend_cls

    @classmethod
    def list_available(cls) -> List[str]:
        """List all available storage backends."""
        return list(cls._backends.keys())


class StorageBackend(ABC):
    """
    Abstract base class for storage backends.
    """

    @abstractmethod
    def write_dataframe(
        self, df: pd.DataFrame, path: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """Write DataFrame to storage.

        ``mode``: ``"overwrite"`` replaces existing data; ``"ignore"`` is a
        no-op if the target already exists; ``"append"`` adds rows to
        existing data (Databricks: passed straight to Spark's
        ``DataFrameWriter.mode()``; Local: read-concat-rewrite). Any other
        value fails if the target already exists.
        """
        pass

    @abstractmethod
    def read_dataframe(self, path: str) -> pd.DataFrame:
        """Read DataFrame from storage."""
        pass

    @abstractmethod
    def write_json(
        self, data: Dict[str, Any], path: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """Write JSON object to storage.

        ``mode``: only ``"overwrite"`` vs. anything else (fails if the
        target already exists) is supported — JSON objects have no natural
        "append" semantics the way DataFrame rows do.
        """
        pass

    @abstractmethod
    def read_json(self, path: str) -> Dict[str, Any]:
        """Read JSON object from storage."""
        pass

    @abstractmethod
    def write_artifact(
        self, artifact_path: str, destination: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """Write artifact (file or directory) to storage.

        ``mode``: only ``"overwrite"`` vs. anything else (fails if the
        target already exists) is supported.
        """
        pass

    @abstractmethod
    def read_artifact(self, path: str, local_destination: str) -> None:
        """Download artifact from storage to local path."""
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if path exists."""
        pass

    @abstractmethod
    def list_paths(self, prefix: str) -> List[str]:
        """List all paths with given prefix."""
        pass

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete path (file or directory)."""
        pass

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics (optional override)."""
        return {}


# Constants
PARQUET_EXT = ".parquet"
JSON_EXT = ".json"
TEMP_SUFFIX = ".tmp"


@contextmanager
def _atomic_replace(final_path: Path, temp_path: Path):
    """Write to temp_path, then atomically replace final_path on success."""
    try:
        yield
        os.replace(temp_path, final_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _atomic_copy_artifact(src: Path, dest: Path) -> None:
    """Copy ``src`` to ``dest`` without ever exposing a partially-written file
    or directory at ``dest`` — unlike a direct ``shutil.copy2``/``copytree``,
    which writes straight onto the live path and can leave a truncated file or
    half-populated directory visible to a concurrent reader.

    Files use ``os.replace`` (atomic rename on the same filesystem). POSIX
    ``rename`` cannot atomically replace a non-empty directory, so for
    directories the previous ``dest`` (if any) is renamed aside, the staged
    copy is renamed into place, and only then is the old copy removed.
    """
    tmp = dest.parent / f".{dest.name}.tmp-{uuid4().hex}"
    try:
        if src.is_file():
            shutil.copy2(src, tmp)
            os.replace(tmp, dest)
        else:
            shutil.copytree(src, tmp)
            backup: Optional[Path] = None
            if dest.exists():
                backup = dest.parent / f".{dest.name}.old-{uuid4().hex}"
                os.rename(dest, backup)
            try:
                os.rename(tmp, dest)
            except Exception:
                # Best-effort: restore the previous directory if the final
                # rename failed, so a failed write doesn't leave `dest` gone.
                if backup is not None:
                    os.rename(backup, dest)
                    backup = None
                raise
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
    finally:
        if tmp.exists():
            if tmp.is_dir():
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                tmp.unlink(missing_ok=True)


class LocalStorageBackend(StorageBackend):
    """
    Local file system storage backend using Parquet for DataFrames.
    """

    def __init__(
        self,
        base_path: str,
        retry_config: Optional[RetryConfig] = None,
        enable_circuit_breaker: bool = True,
    ):
        """
        Initialize local storage backend.
        """
        self.base_path = Path(base_path).resolve()

        self._retry_config = retry_config or STORAGE_RETRY_CONFIG

        self._circuit_breaker: Optional[CircuitBreaker] = None
        if enable_circuit_breaker:
            self._circuit_breaker = CircuitBreaker(
                name=f"local_storage_{base_path}",
                config=CircuitBreakerConfig(
                    failure_threshold=10,
                    timeout=60.0,
                ),
            )

        # Statistics tracking
        self._stats = {
            "reads": 0,
            "writes": 0,
            "deletes": 0,
            "errors": 0,
        }

        logger.info(f"LocalStorageBackend initialized at {self.base_path}")

    def _get_full_path(self, path: str) -> Path:
        """
        Get full path with security validation.
        """
        try:
            return PathValidator.validate_path(path, self.base_path)
        except MLOpsException:
            # Preserve the original exception type (e.g. ValidationError) so
            # code catching MLOpsException uniformly still sees it — wrapping
            # it in a bare ValueError here would discard that type info.
            raise
        except Exception as e:
            logger.error(f"Invalid path '{path}': {e}")
            raise ValueError(f"Invalid path '{path}': {e}") from e

    def _check_circuit_breaker(self) -> None:
        """Check circuit breaker before operation."""
        if self._circuit_breaker:
            self._circuit_breaker.check()

    def _record_success(self) -> None:
        """Record successful operation."""
        if self._circuit_breaker:
            self._circuit_breaker.record_success()

    def _record_failure(self, error: Exception) -> None:
        """Record failed operation."""
        self._stats["errors"] += 1
        if self._circuit_breaker:
            self._circuit_breaker.record_failure(error)

    def _create_metadata(
        self,
        path: Path,
        fmt: str,
        checksum: Optional[str] = None,
    ) -> StorageMetadata:
        """Create metadata for a stored object."""
        now = datetime.now(timezone.utc).isoformat()
        size_bytes = 0

        if path.exists():
            if path.is_file():
                size_bytes = path.stat().st_size
            else:
                size_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

        return StorageMetadata(
            path=str(path.relative_to(self.base_path)),
            created_at=now,
            updated_at=now,
            size_bytes=size_bytes,
            format=fmt,
            checksum=checksum,
        )

    def _validate_disk_space(self, bytes_needed: int) -> None:
        """
        Validate that sufficient disk space is available.
        Raises DiskSpaceError if not enough space.
        """
        try:
            stat = shutil.disk_usage(self.base_path)
            available = stat.free

            # Safety margin: require 10% more than needed
            required = int(bytes_needed * 1.1)

            if available < required:
                logger.error(
                    f"Insufficient disk space: need {required:,} bytes, "
                    f"available {available:,} bytes"
                )
                raise DiskSpaceError(
                    "write_dataframe",
                    str(self.base_path),
                    ValueError(f"Disk space insufficient: {available:,} < {required:,} bytes"),
                )
        except DiskSpaceError:
            raise
        except Exception as e:
            logger.warning(f"Could not validate disk space: {e}")
            # Don't fail if we can't check disk space

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="write_dataframe")
    def write_dataframe(
        self, df: pd.DataFrame, path: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """Write DataFrame to Parquet file with disk space validation.

        ``mode`` accepts the same values as ``DatabricksStorageBackend``
        (which passes them straight to Spark's ``DataFrameWriter.mode()``):
        ``"overwrite"`` replaces any existing file; ``"ignore"`` is a no-op
        if the file already exists; ``"append"`` concatenates onto the
        existing file's rows (creating it if absent); any other value
        (including Spark's ``"error"``/``"errorifexists"``) fails if the
        file already exists — matching this backend's original behavior.
        """
        self._check_circuit_breaker()

        try:
            full_path = self._get_full_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Add .parquet extension if not present
            if not full_path.suffix:
                full_path = full_path.with_suffix(PARQUET_EXT)

            file_exists = full_path.exists()

            if file_exists and mode == "ignore":
                logger.debug(f"write_dataframe mode='ignore': {full_path} already exists, skipping")
                return self._create_metadata(full_path, "parquet")

            if file_exists and mode == "append":
                existing = pd.read_parquet(str(full_path), engine="pyarrow")
                df = pd.concat([existing, df], ignore_index=True)
            elif file_exists and mode not in ("overwrite", "append"):
                raise FileExistsError(f"File {full_path} already exists")

            # C2: Validate disk space BEFORE writing
            estimated_bytes = int(df.memory_usage(deep=True).sum())
            self._validate_disk_space(estimated_bytes)

            temp_path = full_path.with_suffix(PARQUET_EXT + TEMP_SUFFIX)
            with _atomic_replace(full_path, temp_path):
                df.to_parquet(str(temp_path), engine="pyarrow", index=False)

            self._stats["writes"] += 1
            metadata = self._create_metadata(full_path, "parquet")

            self._record_success()
            logger.debug(f"DataFrame written to {full_path}")
            return metadata

        except DiskSpaceError:
            self._record_failure(Exception("Disk space insufficient"))
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("write_dataframe", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="read_dataframe")
    def read_dataframe(self, path: str) -> pd.DataFrame:
        """Read DataFrame from Parquet file."""
        self._check_circuit_breaker()

        try:
            full_path = self._get_full_path(path)
            if not full_path.exists():
                raise FileNotFoundError(f"File {full_path} not found")

            df = pd.read_parquet(str(full_path), engine="pyarrow")

            self._stats["reads"] += 1
            self._record_success()
            logger.debug(f"DataFrame read from {full_path}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("read_dataframe", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="write_json")
    def write_json(
        self, data: Dict[str, Any], path: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """Write JSON object to file with disk space validation."""
        self._check_circuit_breaker()

        try:
            full_path = self._get_full_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Add .json extension if not present
            if not full_path.suffix:
                full_path = full_path.with_suffix(JSON_EXT)

            if full_path.exists() and mode != "overwrite":
                raise FileExistsError(f"File {full_path} already exists")

            # C2: Estimate and validate disk space
            json_str = json.dumps(data, default=str, ensure_ascii=False)
            estimated_bytes = len(json_str.encode("utf-8"))
            self._validate_disk_space(estimated_bytes)

            temp_path = full_path.with_suffix(JSON_EXT + TEMP_SUFFIX)
            with _atomic_replace(full_path, temp_path):
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(json_str)

            self._stats["writes"] += 1
            metadata = self._create_metadata(full_path, "json")

            self._record_success()
            logger.debug(f"JSON written to {full_path}")
            return metadata

        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("write_json", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="read_json")
    def read_json(self, path: str) -> Dict[str, Any]:
        """Read JSON object from file."""
        self._check_circuit_breaker()

        try:
            full_path = self._get_full_path(path)
            if not full_path.exists():
                raise FileNotFoundError(f"File {full_path} not found")

            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._stats["reads"] += 1
            self._record_success()
            logger.debug(f"JSON read from {full_path}")
            return data

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("read_json", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="write_artifact")
    def write_artifact(
        self, artifact_path: str, destination: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """Copy artifact to storage, atomically (temp path + rename)."""
        self._check_circuit_breaker()

        try:
            src = Path(artifact_path)
            dest = self._get_full_path(destination)

            if not src.exists():
                raise FileNotFoundError(f"Source artifact {src} not found")

            if dest.exists() and mode != "overwrite":
                raise FileExistsError(f"Destination {dest} already exists")

            dest.parent.mkdir(parents=True, exist_ok=True)
            _atomic_copy_artifact(src, dest)

            self._stats["writes"] += 1
            metadata = self._create_metadata(dest, "artifact")

            self._record_success()
            logger.debug(f"Artifact copied from {src} to {dest}")
            return metadata

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("write_artifact", destination, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="read_artifact")
    def read_artifact(self, path: str, local_destination: str) -> None:
        """Download artifact to local path."""
        self._check_circuit_breaker()

        try:
            # local_destination is a caller-chosen download target outside
            # this backend's storage sandbox (unlike `destination` in
            # write_artifact), so it isn't containment-checked against a
            # root — but it should still reject the obviously-malformed
            # values that no legitimate caller would pass.
            if not str(local_destination).strip():
                raise ValueError("local_destination cannot be empty")
            if "\x00" in str(local_destination):
                raise ValueError("local_destination contains a null byte")

            src = self._get_full_path(path)
            dest = Path(local_destination)

            if not src.exists():
                raise FileNotFoundError(f"Source artifact {src} not found")

            dest.parent.mkdir(parents=True, exist_ok=True)

            if src.is_file():
                shutil.copy2(src, dest)
            else:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)

            self._stats["reads"] += 1
            self._record_success()
            logger.debug(f"Artifact copied from {src} to {dest}")

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("read_artifact", path, e) from e

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        try:
            full_path = self._get_full_path(path)
            return full_path.exists()
        except Exception:
            return False

    def list_paths(self, prefix: str) -> List[str]:
        """List all paths with given prefix."""
        try:
            base = self._get_full_path(prefix)
            if not base.exists():
                return []

            paths = []
            for path in base.rglob("*"):
                if path.is_file():
                    paths.append(str(path.relative_to(self.base_path)))
            return sorted(paths)

        except Exception as e:
            logger.warning(f"Error listing paths with prefix '{prefix}': {e}")
            return []

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="delete")
    def delete(self, path: str) -> None:
        """Delete path (file or directory)."""
        self._check_circuit_breaker()

        try:
            full_path = self._get_full_path(path)
            if not full_path.exists():
                raise FileNotFoundError(f"Path {full_path} not found")

            if full_path.is_file():
                full_path.unlink()
            else:
                shutil.rmtree(full_path)

            self._stats["deletes"] += 1
            self._record_success()
            logger.debug(f"Deleted {full_path}")

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("delete", path, e) from e

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        stats = self._stats.copy()
        if self._circuit_breaker:
            stats["circuit_breaker_state"] = self._circuit_breaker.state.value
        return stats


class DatabricksStorageBackend(StorageBackend):
    """
    Databricks Unity Catalog storage backend.
    """

    def __init__(
        self,
        catalog: str,
        schema: str,
        volume_name: str = "mlops_artifacts",
        enable_circuit_breaker: bool = True,
        local_cache: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize Databricks storage backend.
        """
        self.catalog = catalog
        self.schema = schema
        self.volume_name = volume_name

        self._spark: Optional[Any] = None
        if local_cache:
            cache_path = local_cache
        else:
            # Use system temp directory for cross-platform compatibility
            cache_path = str(
                Path(tempfile.gettempdir()) / "Ducta_mlops_cache" / f"{catalog}_{schema}"
            )
        self._local_cache_path = Path(cache_path)
        self._local_cache_path.mkdir(parents=True, exist_ok=True)

        # Circuit breaker for Databricks operations
        self._circuit_breaker: Optional[CircuitBreaker] = None
        if enable_circuit_breaker:
            self._circuit_breaker = CircuitBreaker(
                name=f"databricks_storage_{catalog}_{schema}",
                config=CircuitBreakerConfig(
                    failure_threshold=5,
                    timeout=120.0,
                ),
            )

        # Statistics
        self._stats = {
            "spark_reads": 0,
            "spark_writes": 0,
            "local_fallbacks": 0,
            "errors": 0,
        }

        # Initialize Spark session
        self._init_spark_session()

        logger.info(f"DatabricksStorageBackend initialized for {catalog}.{schema}")

    def _init_spark_session(self) -> None:
        """
        Initialize Spark session using databricks-connect or runtime.
        """
        try:
            # Try databricks-connect first (local development)
            from databricks.connect import DatabricksSession  # type: ignore

            self._spark = DatabricksSession.builder.getOrCreate()
            logger.info("Using databricks-connect session. ")
            return
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"databricks-connect not available: {e}")

        try:
            # Fallback to regular SparkSession (Databricks Runtime)
            from pyspark.sql import SparkSession  # type: ignore

            self._spark = SparkSession.builder.getOrCreate()
            logger.info("Using existing SparkSession from Databricks Runtime")
            return
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"SparkSession not available: {e}")

        logger.warning(
            "No Spark session available. Some operations will use local fallback. "
            "Install databricks-connect or run in Databricks environment."
        )

    @property
    def spark(self) -> Optional[Any]:
        """Get the Spark session."""
        if self._spark is None:
            self._init_spark_session()
        return self._spark

    def _check_circuit_breaker(self) -> None:
        """Check circuit breaker before operation."""
        if self._circuit_breaker:
            self._circuit_breaker.check()

    def _record_success(self) -> None:
        """Record successful operation."""
        if self._circuit_breaker:
            self._circuit_breaker.record_success()

    def _record_failure(self, error: Exception) -> None:
        """Record failed operation."""
        self._stats["errors"] += 1
        if self._circuit_breaker:
            self._circuit_breaker.record_failure(error)

    def _get_volume_path(self, path: str) -> str:
        """Get the full Unity Catalog volume path.

        Note: /Volumes is a Databricks Unity Catalog path convention,
        not a local filesystem path. This format is required by Databricks.
        """
        # Use forward slashes as required by Databricks Unity Catalog
        return f"/Volumes/{self.catalog}/{self.schema}/{self.volume_name}/{path}"

    def _get_table_name(self, path: str) -> str:
        """Get full table name from path."""
        # Sanitize path to valid table name
        table_name = (
            path.replace("/", "_")
            .replace(PARQUET_EXT, "")
            .replace(JSON_EXT, "")
            .replace("-", "_")
            .replace(".", "_")
        )
        return f"{self.catalog}.{self.schema}.{table_name}"

    def _get_local_cache_path(self, path: str) -> Path:
        """Get local cache path for a given storage path."""
        return self._local_cache_path / path

    def _use_spark(self) -> bool:
        """Check if Spark should be used for operations."""
        return self.spark is not None

    def _get_dbutils(self) -> Optional[Any]:
        """Get dbutils if available."""
        if not self._use_spark():
            return None
        try:
            from pyspark.dbutils import DBUtils  # type: ignore

            return DBUtils(self.spark)
        except Exception:
            return None

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="databricks_write_dataframe")
    def write_dataframe(
        self, df: pd.DataFrame, path: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """
        Write DataFrame to Unity Catalog table.
        """
        self._check_circuit_breaker()

        try:
            now = datetime.now(timezone.utc).isoformat()

            if self._use_spark():
                # Convert to Spark DataFrame and write as Delta
                spark_df = self.spark.createDataFrame(df)
                table_name = self._get_table_name(path)

                spark_df.write.format("delta").mode(mode).saveAsTable(table_name)

                self._stats["spark_writes"] += 1
                self._record_success()

                logger.info(f"DataFrame written to table: {table_name}")

                return StorageMetadata(
                    path=table_name,
                    created_at=now,
                    updated_at=now,
                    format="delta",
                    size_bytes=df.memory_usage(deep=True).sum(),
                )
            else:
                # Fallback to local cache
                self._stats["local_fallbacks"] += 1
                local_path = self._get_local_cache_path(path)
                local_path.parent.mkdir(parents=True, exist_ok=True)

                if not local_path.suffix:
                    local_path = local_path.with_suffix(PARQUET_EXT)

                df.to_parquet(str(local_path), engine="pyarrow", index=False)

                logger.warning(f"Spark unavailable, DataFrame cached locally: {local_path}")

                return StorageMetadata(
                    path=str(local_path),
                    created_at=now,
                    updated_at=now,
                    format="parquet",
                    size_bytes=local_path.stat().st_size if local_path.exists() else 0,
                )

        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("write_dataframe", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="databricks_read_dataframe")
    def read_dataframe(self, path: str) -> pd.DataFrame:
        """
        Read DataFrame from Unity Catalog table.
        """
        self._check_circuit_breaker()

        try:
            if self._use_spark():
                table_name = self._get_table_name(path)

                spark_df = self.spark.table(table_name)
                df = spark_df.toPandas()

                self._stats["spark_reads"] += 1
                self._record_success()

                logger.info(f"DataFrame read from table: {table_name}")
                return df
            else:
                # Try local cache
                local_path = self._get_local_cache_path(path)
                if not local_path.suffix:
                    local_path = local_path.with_suffix(PARQUET_EXT)

                if local_path.exists():
                    self._stats["local_fallbacks"] += 1
                    logger.warning(f"Reading from local cache: {local_path}")
                    return pd.read_parquet(str(local_path), engine="pyarrow")

                raise FileNotFoundError(
                    f"No Spark session available and no local cache found for: {path}. "
                    f"Run in Databricks environment or use from_context() with proper config."
                )

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("read_dataframe", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="databricks_write_json")
    def write_json(
        self, data: Dict[str, Any], path: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """
        Write JSON to Unity Catalog volume.
        """
        self._check_circuit_breaker()

        try:
            now = datetime.now(timezone.utc).isoformat()
            json_content = json.dumps(data, indent=2, default=str, ensure_ascii=False)

            dbutils = self._get_dbutils()
            if dbutils is not None:
                volume_path = self._get_volume_path(path)
                if not volume_path.endswith(JSON_EXT):
                    volume_path += JSON_EXT

                dbutils.fs.put(volume_path, json_content, overwrite=(mode == "overwrite"))

                self._stats["spark_writes"] += 1
                self._record_success()

                logger.info(f"JSON written to volume: {volume_path}")

                return StorageMetadata(
                    path=volume_path,
                    created_at=now,
                    updated_at=now,
                    format="json",
                    size_bytes=len(json_content.encode("utf-8")),
                )

            # Local cache fallback
            self._stats["local_fallbacks"] += 1
            local_path = self._get_local_cache_path(path)
            if not local_path.suffix:
                local_path = local_path.with_suffix(JSON_EXT)

            local_path.parent.mkdir(parents=True, exist_ok=True)

            with open(local_path, "w", encoding="utf-8") as f:
                f.write(json_content)

            logger.warning(f"JSON cached locally: {local_path}")

            return StorageMetadata(
                path=str(local_path),
                created_at=now,
                updated_at=now,
                format="json",
                size_bytes=local_path.stat().st_size if local_path.exists() else 0,
            )

        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("write_json", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="databricks_read_json")
    def read_json(self, path: str) -> Dict[str, Any]:
        """
        Read JSON from Unity Catalog volume.
        """
        self._check_circuit_breaker()

        try:
            dbutils = self._get_dbutils()
            if dbutils is not None:
                volume_path = self._get_volume_path(path)
                if not volume_path.endswith(JSON_EXT):
                    volume_path += JSON_EXT

                max_bytes = 10 * 1024 * 1024  # 10MB max
                content = dbutils.fs.head(volume_path, max_bytes)

                # Warn if content may have been truncated
                if len(content.encode("utf-8")) >= max_bytes:
                    logger.warning(
                        f"JSON at '{volume_path}' may have been truncated at "
                        f"{max_bytes // (1024 * 1024)}MB. Consider splitting large JSON files."
                    )

                self._stats["spark_reads"] += 1
                self._record_success()

                return json.loads(content)

            # Try local cache
            local_path = self._get_local_cache_path(path)
            if not local_path.suffix:
                local_path = local_path.with_suffix(JSON_EXT)

            if local_path.exists():
                self._stats["local_fallbacks"] += 1
                with open(local_path, "r", encoding="utf-8") as f:
                    return json.load(f)

            raise FileNotFoundError(f"JSON not found at volume path or local cache: {path}")

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("read_json", path, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="databricks_write_artifact")
    def write_artifact(
        self, artifact_path: str, destination: str, mode: str = "overwrite"
    ) -> StorageMetadata:
        """
        Upload artifact to Unity Catalog volume.
        """
        self._check_circuit_breaker()

        try:
            now = datetime.now(timezone.utc).isoformat()
            src = Path(artifact_path)

            if not src.exists():
                raise FileNotFoundError(f"Source artifact not found: {artifact_path}")

            dbutils = self._get_dbutils()
            if dbutils is not None:
                volume_path = self._get_volume_path(destination)

                # Copy to volume
                local_path = f"file:{src.absolute()}"
                dbutils.fs.cp(local_path, volume_path, recurse=src.is_dir())

                self._stats["spark_writes"] += 1
                self._record_success()

                logger.info(f"Artifact uploaded to volume: {volume_path}")

                size_bytes = (
                    src.stat().st_size
                    if src.is_file()
                    else sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
                )

                return StorageMetadata(
                    path=volume_path,
                    created_at=now,
                    updated_at=now,
                    format="artifact",
                    size_bytes=size_bytes,
                )

            # Local cache fallback
            self._stats["local_fallbacks"] += 1
            local_dest = self._get_local_cache_path(destination)
            local_dest.parent.mkdir(parents=True, exist_ok=True)

            if src.is_file():
                shutil.copy2(src, local_dest)
            else:
                if local_dest.exists():
                    shutil.rmtree(local_dest)
                shutil.copytree(src, local_dest)

            logger.warning(f"Artifact cached locally: {local_dest}")

            size_bytes = (
                local_dest.stat().st_size
                if local_dest.is_file()
                else sum(f.stat().st_size for f in local_dest.rglob("*") if f.is_file())
            )

            return StorageMetadata(
                path=str(local_dest),
                created_at=now,
                updated_at=now,
                format="artifact",
                size_bytes=size_bytes,
            )

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("write_artifact", destination, e) from e

    @with_retry(config=STORAGE_RETRY_CONFIG, operation_name="databricks_read_artifact")
    def read_artifact(self, path: str, local_destination: str) -> None:
        """
        Download artifact from Unity Catalog volume.
        """
        self._check_circuit_breaker()

        try:
            dest = Path(local_destination)
            dest.parent.mkdir(parents=True, exist_ok=True)

            dbutils = self._get_dbutils()
            if dbutils is not None:
                volume_path = self._get_volume_path(path)

                local_path = f"file:{dest.absolute()}"
                dbutils.fs.cp(volume_path, local_path, recurse=True)

                self._stats["spark_reads"] += 1
                self._record_success()

                logger.info(f"Artifact downloaded from volume: {volume_path}")
                return

            # Try local cache
            local_src = self._get_local_cache_path(path)

            if local_src.exists():
                self._stats["local_fallbacks"] += 1

                if local_src.is_file():
                    shutil.copy2(local_src, dest)
                else:
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(local_src, dest)

                logger.warning(f"Artifact read from local cache: {local_src}")
                return

            raise FileNotFoundError(f"Artifact not found at volume path or local cache: {path}")

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("read_artifact", path, e) from e

    def exists(self, path: str) -> bool:
        """Check if path exists in volume or local cache."""
        try:
            dbutils = self._get_dbutils()
            if dbutils is not None:
                volume_path = self._get_volume_path(path)
                try:
                    dbutils.fs.ls(volume_path)
                    return True
                except Exception:
                    pass

            # Check local cache
            local_path = self._get_local_cache_path(path)
            return local_path.exists()

        except Exception:
            return False

    def list_paths(self, prefix: str) -> List[str]:
        """List paths in volume or local cache."""
        paths: List[str] = []

        try:
            dbutils = self._get_dbutils()
            if dbutils is not None:
                volume_path = self._get_volume_path(prefix)
                try:
                    for file_info in dbutils.fs.ls(volume_path):
                        paths.append(file_info.path)
                except Exception:
                    pass

            # Also check local cache
            local_base = self._get_local_cache_path(prefix)
            if local_base.exists():
                for p in local_base.rglob("*"):
                    if p.is_file():
                        paths.append(str(p.relative_to(self._local_cache_path)))

        except Exception as e:
            logger.warning(f"Error listing paths: {e}")

        return sorted(set(paths))

    def delete(self, path: str) -> None:
        """Delete path from volume and local cache."""
        self._check_circuit_breaker()

        deleted = False

        try:
            dbutils = self._get_dbutils()
            if dbutils is not None:
                volume_path = self._get_volume_path(path)
                try:
                    dbutils.fs.rm(volume_path, recurse=True)
                    deleted = True
                    logger.info(f"Deleted from volume: {volume_path}")
                except Exception as e:
                    logger.debug(f"dbutils delete failed: {e}")

            # Also delete from local cache
            local_path = self._get_local_cache_path(path)
            if local_path.exists():
                if local_path.is_file():
                    local_path.unlink()
                else:
                    shutil.rmtree(local_path)
                deleted = True
                logger.info(f"Deleted from local cache: {local_path}")

            if not deleted:
                raise FileNotFoundError(f"Path not found: {path}")

            self._record_success()

        except FileNotFoundError:
            raise
        except Exception as e:
            self._record_failure(e)
            raise StorageBackendError("delete", path, e) from e

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        stats = self._stats.copy()
        stats["spark_available"] = self._use_spark()
        if self._circuit_breaker:
            stats["circuit_breaker_state"] = self._circuit_breaker.state.value
        return stats

    def sync_to_volume(self) -> int:
        """
        Sync local cache to Unity Catalog volume.
        """
        if not self._use_spark():
            logger.warning("Cannot sync: Spark not available")
            return 0

        synced = 0

        for local_file in self._local_cache_path.rglob("*"):
            if local_file.is_file():
                relative_path = str(local_file.relative_to(self._local_cache_path))

                try:
                    self.write_artifact(str(local_file), relative_path)
                    synced += 1
                except Exception as e:
                    logger.error(f"Failed to sync {relative_path}: {e}")

        logger.info(f"Synced {synced} files to volume")
        return synced


# Default registration of built-in backends
StorageBackendRegistry.register("local", LocalStorageBackend)
StorageBackendRegistry.register("databricks", DatabricksStorageBackend)
