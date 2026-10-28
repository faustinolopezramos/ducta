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

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger

from .circuit_breaker import CircuitBreaker
from .connector import JDBCConnector
from .credentials import project_root_for, resolve_credentials
from .exceptions import JDBCCircuitOpenError


class ConnectionManager:
    """Manages JDBC connections from declarative configuration."""

    def __init__(self, config_path: Path, project_root: Optional[Path] = None):
        """Initialize ConnectionManager with config file.

        ``project_root`` is the project whose ``.env`` holds the credentials; by default the
        one :func:`project_root_for` finds for the sources file.
        """
        self.config_path = Path(config_path)
        self.project_root = Path(project_root) if project_root is not None else None
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        self.config = self._load_config()
        if not isinstance(self.config, dict):
            raise ValueError(f"{self.config_path} must hold a mapping with a 'sources' key")
        self.sources = self.config.get("sources") or {}
        if not isinstance(self.sources, dict):
            raise ValueError(f"'sources' in {self.config_path} must be a mapping")
        self._connectors: Dict[str, JDBCConnector] = {}
        self._lib_dir = Path.cwd() / "lib" / "jdbc"
        self._ivy_dir = Path.home() / ".ivy2" / "jars"
        self._breaker_config = self._parse_breaker_config(self.config.get("circuit_breaker") or {})
        self._breakers: Dict[str, CircuitBreaker] = {}

    @staticmethod
    def _parse_breaker_config(top_level: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "enabled": bool(top_level.get("enabled", False)),
            "failure_threshold": int(top_level.get("failure_threshold", 5)),
            "cooldown_seconds": float(top_level.get("cooldown_seconds", 60.0)),
        }

    def _breaker_for(self, source_name: str) -> Optional[CircuitBreaker]:
        """Opt-in per source_name; merges the top-level `circuit_breaker:` block
        with a per-source override (same pattern as `driver:` overrides). Returns
        None (disabled) unless explicitly enabled — ConnectionManager has no access
        to pipeline global_config, so this is configured in sources.yaml itself."""
        source_cfg = self.sources.get(source_name, {}) or {}
        override = source_cfg.get("circuit_breaker")
        override = override if isinstance(override, dict) else {}
        cfg = {**self._breaker_config, **override}
        if not cfg.get("enabled"):
            return None
        if source_name not in self._breakers:
            self._breakers[source_name] = CircuitBreaker(
                failure_threshold=int(cfg["failure_threshold"]),
                cooldown_seconds=float(cfg["cooldown_seconds"]),
            )
        return self._breakers[source_name]

    def record_success(self, source_name: str) -> None:
        """Feed a successful call into the source's circuit breaker, if enabled."""
        breaker = self._breakers.get(source_name)
        if breaker is not None:
            breaker.record_success()

    def record_failure(self, source_name: str) -> None:
        """Feed a failed call into the source's circuit breaker, if enabled."""
        breaker = self._breakers.get(source_name)
        if breaker is not None:
            breaker.record_failure()

    def is_circuit_open(self, source_name: str) -> bool:
        """True if the source's circuit breaker is open (disabled sources always False)."""
        breaker = self._breakers.get(source_name)
        return bool(breaker and breaker.is_open())

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file (auto-detect format)."""
        suffix = self.config_path.suffix.lower()

        if suffix in [".yaml", ".yml"]:
            with open(self.config_path, "r") as f:
                return yaml.safe_load(f) or {}
        elif suffix == ".json":
            import json

            with open(self.config_path, "r") as f:
                return json.load(f)
        elif suffix == ".toml":
            try:
                import toml

                with open(self.config_path, "r") as f:
                    return toml.load(f)
            except ImportError:
                raise ImportError(
                    "toml library required for TOML format. Install with: pip install toml"
                )
        else:
            raise ValueError(f"Unsupported format: {suffix}. Use: .yaml, .yml, .json, or .toml")

    def get(self, source_name: str) -> "Connection":
        """Get a connection by source name."""
        if source_name not in self.sources:
            available = ", ".join(self.sources.keys())
            raise ValueError(f"Source '{source_name}' not found. Available: {available}")

        if source_name not in self._connectors:
            self._connectors[source_name] = self._create_connector(source_name)

        return Connection(self._connectors[source_name], breaker=self._breaker_for(source_name))

    def _driver_overrides(self, source_config: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Return the optional per-source driver override block, if any."""
        driver = source_config.get("driver")
        return driver if isinstance(driver, dict) else None

    def _load_driver_class(self, connector: JDBCConnector) -> None:
        """Load a connector's JDBC driver class explicitly in the Spark JVM."""
        try:
            from pyspark.sql import SparkSession  # type: ignore

            spark = SparkSession.getActiveSession()
            if spark is None:
                logger.debug("No active SparkSession. Driver will be loaded during execution.")
                return

            # Resolve driver class + JAR honoring per-source overrides.
            driver_class = connector.get_driver_class()
            jar_path = self._lib_dir / connector.get_driver_jar()

            if not jar_path.exists():
                logger.debug(f"Driver JAR not found: {jar_path}")
                return

            jvm = spark.sparkContext._jvm

            try:
                jar_url = jvm.java.io.File(str(jar_path)).toURI().toURL()
                url_array = jvm.java.lang.reflect.Array.newInstance(jvm.java.net.URL, 1)
                jvm.java.lang.reflect.Array.set(url_array, 0, jar_url)

                parent_loader = jvm.java.lang.Thread.currentThread().getContextClassLoader()
                url_class_loader = jvm.java.net.URLClassLoader(url_array, parent_loader)

                jvm.java.lang.Thread.currentThread().setContextClassLoader(url_class_loader)

                # Now load the driver class
                jvm.java.lang.Class.forName(driver_class, True, url_class_loader)
                logger.info(f"Loaded JDBC driver via URLClassLoader: {driver_class}")

            except Exception:
                # Fallback: try simple Class.forName
                jvm.java.lang.Class.forName(driver_class)
                logger.info(f"Loaded JDBC driver: {driver_class}")

        except Exception as e:
            logger.debug(f"Could not load driver class {connector.source_type}: {e}")

    def _add_jar_to_spark(self, jar_path: Path) -> None:
        """Add JAR to Spark session if available."""
        try:
            from pyspark.sql import SparkSession

            spark = SparkSession.getActiveSession()
            if spark is not None:
                # Add JAR to the Spark classpath
                spark.sparkContext.addJar(str(jar_path))
                logger.info(f"Added JAR to Spark: {jar_path}")
            else:
                logger.debug(f"No active SparkSession. JAR will be available at: {jar_path}")
        except Exception as e:
            logger.debug(f"Could not add JAR to Spark: {e}")

    def _create_connector(self, source_name: str) -> JDBCConnector:
        """Create JDBCConnector from source config."""
        source_config = self.sources[source_name]

        source_type = source_config.get("type")
        host = source_config.get("host")
        port = source_config.get("port")
        database = source_config.get("database")

        missing = [
            key
            for key, value in (
                ("type", source_type),
                ("host", host),
                ("port", port),
                ("database", database),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                f"Source '{source_name}' is missing required field(s): {', '.join(missing)}"
            )

        name_prefix = source_name.upper()

        # The environment, then the ``.env`` of the project the sources file belongs to
        # (wherever the process was started), then the deprecated type-wide pair.
        project_root = self.project_root or project_root_for(self.config_path.parent)
        credentials = resolve_credentials(source_name, source_type, project_root)
        username, password = credentials.username, credentials.password

        if not username or not password:
            raise ValueError(
                f"Missing credentials for {source_name}. "
                f"Set environment variables: {name_prefix}_USER, {name_prefix}_PASSWORD\n"
                f"Or create .env file with:\n"
                f"  {name_prefix}_USER=your_username\n"
                f"  {name_prefix}_PASSWORD=your_password"
            )

        url_params = source_config.get("url_params")
        connector = JDBCConnector(
            source_type=source_type,
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            driver=self._driver_overrides(source_config),
            url_params=url_params if isinstance(url_params, dict) else None,
        )

        # Ensure driver is available and added to Spark
        try:
            jar_path = connector.download_driver(self._lib_dir)
            self._add_jar_to_spark(jar_path)
            self._load_driver_class(connector)
        except Exception as e:
            logger.warning(f"Could not download driver for {source_name}: {e}")

        return connector

    def list_sources(self) -> List[str]:
        """List all configured sources."""
        return list(self.sources.keys())

    def get_source_info(self, source_name: str) -> Dict[str, Any]:
        """Get information about a source (without credentials)."""
        if source_name not in self.sources:
            raise ValueError(f"Source '{source_name}' not found")

        source_config = self.sources[source_name]
        return {
            "name": source_name,
            "type": source_config.get("type"),
            "host": source_config.get("host"),
            "port": source_config.get("port"),
            "database": source_config.get("database"),
            "description": source_config.get("description", ""),
        }


class Connection:
    """Wrapper for a JDBC connection with Spark-ready properties."""

    def __init__(self, connector: JDBCConnector, breaker: Optional[CircuitBreaker] = None):
        """Initialize Connection wrapper. `breaker` is None unless the source has
        circuit_breaker.enabled=true in sources.yaml (see ConnectionManager docstring)."""
        self.connector = connector
        self._breaker = breaker

    @property
    def jdbc_url(self) -> str:
        """JDBC URL ready for spark.read.jdbc()"""
        return self.connector.get_jdbc_url()

    @property
    def jdbc_properties(self) -> Dict[str, str]:
        """Properties dict ready for spark.read.jdbc()"""
        return {
            "user": self.connector.username,
            "password": self.connector.password,
            "driver": self.connector.get_driver_class(),
        }

    def test_connection(self, timeout_seconds: int = 10) -> Optional[bool]:
        """Whether the connection answers; ``None`` when it could not be tested."""
        if self._breaker is not None and self._breaker.is_open():
            raise JDBCCircuitOpenError(
                "Circuit open for this source (too many consecutive failures); "
                "still within cooldown."
            )
        result = self.connector.test_connection(timeout_seconds)
        # An untested connection is neither a success nor a failure for the breaker.
        if self._breaker is not None and result is not None:
            if result:
                self._breaker.record_success()
            else:
                self._breaker.record_failure()
        return result
