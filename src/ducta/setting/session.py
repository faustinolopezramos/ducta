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

import atexit
import contextlib
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Literal, Optional

from loguru import logger  # type: ignore


class SparkSessionManager:
    """
    Manager for Spark sessions with lifecycle management, cleanup, and memory leak prevention.
    """

    _sessions: Dict[str, Any] = {}
    _session_metadata: Dict[str, Dict[str, Any]] = {}
    _lock = threading.RLock()
    _cleanup_registered = False
    _session_timeout = 3600  # 1 hour default

    @classmethod
    def _register_cleanup(cls) -> None:
        """Register cleanup handler to run at program exit."""
        with cls._lock:
            if not cls._cleanup_registered:
                atexit.register(cls.cleanup_all)
                cls._cleanup_registered = True
                logger.debug("Registered SparkSessionManager cleanup handler")

    @classmethod
    def _generate_session_key(
        cls,
        mode: str,
        ml_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate a unique key for session caching based on configuration.

        Uses json.dumps for hashing so nested dicts/lists in ml_config
        (which are not hashable) do not raise TypeError.
        """
        try:
            config_str = json.dumps(ml_config or {}, sort_keys=True, default=str)
        except (TypeError, ValueError):
            config_str = str(sorted((ml_config or {}).items()))
        return f"{mode}_{hash(config_str)}"

    @classmethod
    def get_or_create_session(
        cls,
        mode: Literal["local", "databricks", "distributed"] = "databricks",
        ml_config: Optional[Dict[str, Any]] = None,
        force_new: bool = False,
    ):
        """Get existing session or create new one with thread-safe caching."""
        cls._register_cleanup()

        session_key = cls._generate_session_key(mode, ml_config)

        with cls._lock:
            if not force_new and session_key in cls._sessions:
                session = cls._sessions[session_key]
                if cls._is_session_valid(session, session_key):
                    logger.debug("Reusing existing Spark session: {}", session_key)
                    cls._update_session_access_time(session_key)
                    return session
                else:
                    logger.info("Existing session invalid, creating new one: {}", session_key)
                    cls._cleanup_session(session_key)

            logger.info("Creating new Spark session: {} (mode={})", session_key, mode)
            session = SparkSessionFactory.create_session(mode, ml_config)

            cls._sessions[session_key] = session
            cls._session_metadata[session_key] = {
                "created_at": time.time(),
                "last_accessed": time.time(),
                "mode": mode,
                "ml_config": ml_config,
            }

            return session

    @classmethod
    def _is_session_valid(cls, session: Any, session_key: str) -> bool:
        """Check if a session is still valid and active."""
        try:
            if session is None or session_key not in cls._session_metadata:
                return False
            if not cls._check_session_timeout(session_key):
                return False
            _ = session.version
            return True
        except Exception as e:
            logger.debug("Session validation failed for {}: {}", session_key, e)
            return False

    @classmethod
    def _check_session_timeout(cls, session_key: str) -> bool:
        """Check if session has timed out."""
        metadata = cls._session_metadata[session_key]
        elapsed = time.time() - metadata.get("last_accessed", 0)
        if elapsed > cls._session_timeout:
            logger.warning(
                "Session {} timed out ({:.0f}s > {}s)",
                session_key,
                elapsed,
                cls._session_timeout,
            )
            return False
        return True

    @classmethod
    def _update_session_access_time(cls, session_key: str) -> None:
        """Update last access time for a session."""
        if session_key in cls._session_metadata:
            cls._session_metadata[session_key]["last_accessed"] = time.time()

    @classmethod
    def _cleanup_session(cls, session_key: str) -> None:
        """Cleanup a specific session."""
        if session_key in cls._sessions:
            session = cls._sessions.pop(session_key)
            cls._session_metadata.pop(session_key, None)
            try:
                cls._stop_session_quietly(session)
                logger.debug("Stopped Spark session: {}", session_key)
            except (ValueError, OSError):
                pass
            except Exception as e:
                logger.warning("Error stopping session {}: {}", session_key, e)

    @classmethod
    def _stop_session_quietly(cls, session: Any) -> None:
        """Stop active streaming queries and then stop a Spark session."""
        cls._stop_active_streams_quietly(session)

        if sys.platform == "win32":
            with open(os.devnull, "w", encoding="utf-8") as devnull:
                with contextlib.redirect_stderr(devnull):
                    session.stop()
            time.sleep(0.3)
        else:
            session.stop()

    @classmethod
    def _stop_active_streams_quietly(cls, session: Any, timeout_seconds: float = 5.0) -> None:
        """Best-effort graceful shutdown for active Structured Streaming queries."""
        try:
            streams = getattr(session, "streams", None)
            active_queries = getattr(streams, "active", []) if streams is not None else []
        except Exception:
            return

        if not isinstance(active_queries, (list, tuple, set)):
            try:
                active_queries = list(active_queries)
            except TypeError:
                return

        for query in list(active_queries or []):
            try:
                is_active_attr = getattr(query, "isActive", None)
                is_active = bool(is_active_attr() if callable(is_active_attr) else is_active_attr)
                if not is_active:
                    continue

                query.stop()
                await_termination = getattr(query, "awaitTermination", None)
                if callable(await_termination):
                    await_termination(timeout_seconds)
            except TypeError:
                try:
                    query.awaitTermination()  # type: ignore[attr-defined]
                except Exception:
                    pass
            except Exception as e:
                logger.debug("Could not stop active streaming query gracefully: {}", e)

    @classmethod
    def cleanup_all(cls) -> None:
        """Cleanup all managed sessions."""
        with cls._lock:
            if not sys.is_finalizing():
                try:
                    logger.info("Cleaning up {} Spark session(s)", len(cls._sessions))
                except (ValueError, OSError):
                    pass
            for session_key in tuple(cls._sessions):
                cls._cleanup_session(session_key)
            cls._sessions.clear()
            cls._session_metadata.clear()

    @classmethod
    def cleanup_stale_sessions(cls, max_age: Optional[int] = None) -> int:
        """Cleanup sessions that haven't been accessed recently."""
        max_age = max_age or cls._session_timeout
        cleaned = 0

        with cls._lock:
            current_time = time.time()
            for session_key in tuple(cls._sessions):
                metadata = cls._session_metadata.get(session_key, {})
                last_accessed = metadata.get("last_accessed", 0)
                age = current_time - last_accessed
                if age > max_age:
                    logger.info(
                        "Cleaning up stale session {} (age: {:.0f}s)",
                        session_key,
                        age,
                    )
                    cls._cleanup_session(session_key)
                    cleaned += 1

        return cleaned

    @classmethod
    def get_session_info(cls, check_health: bool = False) -> Dict[str, Dict[str, Any]]:
        """Get information about all active sessions."""
        with cls._lock:
            info = {}
            current_time = time.time()
            for key, metadata in cls._session_metadata.items():
                age = current_time - metadata.get("created_at", current_time)
                last_access_age = current_time - metadata.get("last_accessed", current_time)
                is_valid = (
                    cls._is_session_valid(cls._sessions.get(key), key)
                    if check_health
                    else key in cls._sessions
                )
                info[key] = {
                    "mode": metadata.get("mode"),
                    "age_seconds": age,
                    "last_access_seconds_ago": last_access_age,
                    "is_valid": is_valid,
                }
            return info


class SparkSessionFactory:
    """
    Factory for creating Spark sessions based on the execution mode with ML optimizations.
    """

    _protected_configs_lock = threading.RLock()

    @classmethod
    def get_session(
        cls,
        mode: Literal["local", "databricks", "distributed"] = "databricks",
        ml_config: Optional[Dict[str, Any]] = None,
    ):
        """Get or create a Spark session, delegating to SparkSessionManager for full
        lifecycle management (per-config caching, timeout detection, cleanup).
        """
        return SparkSessionManager.get_or_create_session(mode=mode, ml_config=ml_config)

    @classmethod
    def reset_session(cls):
        """Stop and remove all managed sessions (for testing or reconfiguration)."""
        SparkSessionManager.cleanup_all()
        logger.info("All Spark sessions reset via SparkSessionManager")

    PROTECTED_CONFIGS: frozenset = frozenset(
        [
            "spark.sql.shuffle.partitions",
            "spark.executor.memory",
            "spark.driver.memory",
            "spark.master",
            "spark.submit.deployMode",
            "spark.dynamicAllocation.enabled",
            "spark.executor.instances",
        ]
    )

    _JAVA_ADD_OPENS = (
        "--add-opens=java.base/java.nio=ALL-UNNAMED "
        "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED "
        "--add-opens=java.base/java.util=ALL-UNNAMED "
        "--add-opens=java.base/java.lang=ALL-UNNAMED "
        "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED "
        "--add-opens=java.base/java.util.concurrent=ALL-UNNAMED "
        "--add-opens=java.base/java.util.concurrent.atomic=ALL-UNNAMED "
        "--add-opens=java.base/java.net=ALL-UNNAMED "
        "--add-opens=java.base/java.text=ALL-UNNAMED "
        "--add-opens=java.sql/java.sql=ALL-UNNAMED"
    )

    PERFORMANCE_CONFIGS: Dict[str, Any] = {
        "spark.scheduler.mode": "FAIR",
        "spark.sql.adaptive.enabled": "true",
        "spark.sql.adaptive.coalescePartitions.enabled": "true",
        "spark.sql.adaptive.skewJoin.enabled": "true",
        "spark.sql.streaming.metricsEnabled": "true",
        "spark.sql.streaming.stateStore.providerClass": "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider",
        "spark.sql.streaming.stateStore.rocksdb.changelogCheckpointing.enabled": "true",
        "spark.databricks.delta.properties.defaults.enableChangeDataFeed": "true",
        "spark.sql.execution.arrow.pyspark.enabled": "true",
        "spark.sql.execution.arrow.pyspark.fallback.enabled": "true",
        "spark.sql.streaming.stateStore.rocksdb.blockCacheSize": "256mb",
        "spark.sql.streaming.stateStore.rocksdb.lockAcquireTimeoutMs": "60000",
        "spark.sql.streaming.stateStore.rocksdb.useBloomFilter": "true",
        "spark.sql.streaming.stateStore.rocksdb.compactOnClose": "true",
        "spark.driver.extraJavaOptions": _JAVA_ADD_OPENS,
        "spark.executor.extraJavaOptions": _JAVA_ADD_OPENS,
    }

    LOCAL_DEFAULT_CONFIGS: Dict[str, Any] = {
        "spark.sql.shuffle.partitions": "2",
        "spark.default.parallelism": "2",
        "spark.ui.enabled": "false",
    }

    @classmethod
    def _apply_configs(cls, builder: Any, configs: Dict[str, Any]) -> Any:
        """Apply a flat dict of Spark config keys/values to the builder."""
        for k, v in configs.items():
            try:
                builder = builder.config(k, v)
            except Exception:
                pass
        return builder

    @staticmethod
    def _apply_jdbc_jars(builder: Any) -> Any:
        """Register JDBC driver JARs (declarative ingestion) on the Spark classpath."""
        try:
            from ducta.gate.gateway.spark_setup import collect_jdbc_jars

            jars = collect_jdbc_jars()
            if jars:
                builder = builder.config("spark.jars", ",".join(jars))
                logger.info("Registered {} JDBC driver JAR(s) with Spark", len(jars))
        except Exception as e:
            logger.debug("Could not register JDBC driver JARs: {}", e)
        return builder

    @classmethod
    def set_protected_configs(cls, configs: Optional[List[str]]) -> None:
        """Set custom protected configurations (thread-safe)."""
        with cls._protected_configs_lock:
            cls.PROTECTED_CONFIGS = frozenset(configs or [])

    @staticmethod
    def create_session(
        mode: Literal["local", "databricks", "distributed"] = "databricks",
        ml_config: Optional[Dict[str, Any]] = None,
    ):
        """Create a Spark session based on the specified mode with ML configurations."""
        logger.info(f"Attempting to create Spark session in {mode} mode")

        if ml_config:
            logger.info("Applying ML-specific Spark configurations")

        normalized = str(mode).lower()

        if normalized in ("databricks", "distributed"):
            return SparkSessionFactory._create_databricks_session(ml_config)
        elif normalized == "local":
            return SparkSessionFactory._create_local_session(ml_config)
        else:
            raise ValueError(
                f"Invalid execution mode: {mode}. Use 'local', 'databricks' or 'distributed'."
            )

    @staticmethod
    def _create_databricks_session(ml_config: Optional[Dict[str, Any]] = None):
        """
        Create a Databricks Connect session for remote execution with ML configs.
        """
        try:
            from databricks.connect import DatabricksSession  # type: ignore
            from databricks.sdk.core import Config  # type: ignore

            config = Config()

            SparkSessionFactory._validate_databricks_config(config)

            logger.info("Creating remote session with Databricks Connect")
            builder = DatabricksSession.builder.remote(
                host=config.host, token=config.token, cluster_id=config.cluster_id
            )

            builder = SparkSessionFactory._apply_configs(
                builder, SparkSessionFactory.PERFORMANCE_CONFIGS
            )

            if ml_config:
                builder = SparkSessionFactory._apply_ml_configs(builder, ml_config)

            return builder.getOrCreate()

        except ImportError as e:
            logger.error(f"Databricks Connect not installed: {str(e)}")
            raise
        except ValueError as e:
            logger.error(f"Invalid configuration: {str(e)}")
            raise
        except RuntimeError as e:
            logger.error(f"Connection failed: {str(e)}")
            raise
        except Exception as e:
            logger.critical(f"Unhandled exception: {str(e)}")
            raise RuntimeError("Critical error creating session") from e

    @staticmethod
    def _create_local_session(ml_config: Optional[Dict[str, Any]] = None):
        """Create a local Spark session with ML optimizations."""
        try:
            from pyspark.sql import SparkSession  # type: ignore

            os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
            builder = SparkSession.builder.appName("DuctaLocal").master("local[*]")

            builder = SparkSessionFactory._apply_configs(
                builder, SparkSessionFactory.PERFORMANCE_CONFIGS
            )
            builder = SparkSessionFactory._apply_configs(
                builder, SparkSessionFactory.LOCAL_DEFAULT_CONFIGS
            )
            builder = SparkSessionFactory._apply_jdbc_jars(builder)

            if ml_config and isinstance(ml_config, dict):
                builder = SparkSessionFactory._apply_ml_configs(builder, ml_config)

            return builder.getOrCreate()
        except Exception as e:
            SparkSessionFactory._raise_if_databricks_connect_shadows_pyspark(e)
            logger.error("Session creation failed", exc_info=True)
            raise

    @staticmethod
    def _raise_if_databricks_connect_shadows_pyspark(error: Exception) -> None:
        """Re-raise a local-session failure as an actionable install diagnostic."""
        if "Only remote Spark sessions" not in str(error):
            return
        raise RuntimeError(
            "Local Spark mode is unavailable because 'databricks-connect' has "
            "replaced the 'pyspark' package in this environment. The two cannot "
            "coexist: databricks-connect installs its own 'pyspark' module that "
            "supports remote Databricks sessions only.\n"
            "  • To run locally:     pip uninstall -y databricks-connect && "
            "pip install --force-reinstall 'pyspark>=3.5,<4'\n"
            "  • To use Databricks:  keep databricks-connect and set mode: "
            "databricks (not 'local') in global_config.\n"
            "Install 'ducta[spark]' or 'ducta[databricks]' — never both."
        ) from error

    @staticmethod
    def _validate_databricks_config(config) -> None:
        """Validate required Databricks configuration parameters."""
        required = ["host", "token", "cluster_id"]
        missing = [k for k in required if not getattr(config, k, None)]
        if missing:
            raise ValueError(f"Missing Databricks config values: {', '.join(missing)}")

    @staticmethod
    def _apply_ml_configs(builder: Any, ml_config: Dict[str, Any]) -> Any:
        """Apply ML-related configurations to the Spark builder."""
        protected = SparkSessionFactory.PROTECTED_CONFIGS
        for k, v in (ml_config or {}).items():
            if k in protected:
                logger.warning("Skipping ML config '{}' because it's in PROTECTED_CONFIGS", k)
                continue
            try:
                builder = builder.config(k, v)
            except Exception:
                logger.debug("Failed to apply Spark config {}={}", k, v, exc_info=True)
        return builder
