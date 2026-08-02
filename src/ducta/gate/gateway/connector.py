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

import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger  # type: ignore

from ducta.gate.exceptions import ConfigurationError


class JDBCConnector:
    """Manages JDBC configuration and driver download for database ingestion."""

    # Each entry pins a default driver `version` and provides `jar_template` /
    # `maven_template` (with a `{version}` placeholder). `get_driver_jar()` /
    # `get_driver_download_url()` always render these against the effective
    # version (override or default) — there is a single source of truth per driver.
    DRIVERS = {
        "sqlserver": {
            "class": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
            "version": "9.4.1.jre11",
            "jar_template": "mssql-jdbc-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/com/microsoft/sqlserver/mssql-jdbc/{version}/mssql-jdbc-{version}.jar",
            "url": "jdbc:sqlserver://{host}:{port};databaseName={database}",
            # Encrypted by default; self-signed certs accepted unless the source
            # overrides trustServerCertificate via `url_params`.
            "default_url_params": {"encrypt": "true", "trustServerCertificate": "true"},
            "url_param_separator": ";",
            "default_port": 1433,
            "test_query": "(SELECT 1 AS test_col) AS test_table",
        },
        "oracle": {
            "class": "oracle.jdbc.driver.OracleDriver",
            "version": "21.9.0.0",
            "jar_template": "ojdbc8-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/com/oracle/database/jdbc/ojdbc8/{version}/ojdbc8-{version}.jar",
            "url": "jdbc:oracle:thin:@{host}:{port}:{database}",
            "default_port": 1521,
            "test_query": "(SELECT 1 AS test_col FROM dual) AS test_table",
        },
        "postgresql": {
            "class": "org.postgresql.Driver",
            "version": "42.6.0",
            "jar_template": "postgresql-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/org/postgresql/postgresql/{version}/postgresql-{version}.jar",
            "url": "jdbc:postgresql://{host}:{port}/{database}",
            "default_port": 5432,
            "test_query": "(SELECT 1 AS test_col) AS test_table",
        },
        "mysql": {
            "class": "com.mysql.cj.jdbc.Driver",
            "version": "8.0.33",
            "jar_template": "mysql-connector-java-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/mysql/mysql-connector-java/{version}/mysql-connector-java-{version}.jar",
            "url": "jdbc:mysql://{host}:{port}/{database}",
            "default_port": 3306,
            "test_query": "(SELECT 1 AS test_col) AS test_table",
        },
        "mariadb": {
            "class": "org.mariadb.jdbc.Driver",
            "version": "3.1.4",
            "jar_template": "mariadb-java-client-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/org/mariadb/jdbc/mariadb-java-client/{version}/mariadb-java-client-{version}.jar",
            "url": "jdbc:mariadb://{host}:{port}/{database}",
            "default_port": 3306,
            "test_query": "(SELECT 1 AS test_col) AS test_table",
        },
        "snowflake": {
            "class": "net.snowflake.client.jdbc.SnowflakeDriver",
            "version": "3.13.29",
            "jar_template": "snowflake-jdbc-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/net/snowflake/snowflake-jdbc/{version}/snowflake-jdbc-{version}.jar",
            "url": "jdbc:snowflake://{host}/?db={database}",
            "default_port": 443,
            "test_query": "(SELECT 1 AS test_col) AS test_table",
        },
    }

    def __init__(
        self,
        source_type: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        driver: Optional[Dict[str, str]] = None,
        url_params: Optional[Dict[str, str]] = None,
    ):
        if source_type not in self.DRIVERS:
            raise ValueError(
                f"Unsupported source type: {source_type}. Supported: {list(self.DRIVERS.keys())}"
            )

        self.source_type = source_type
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        # Optional per-source driver overrides: {version, jar, maven, class, sha256}.
        self.driver_overrides: Dict[str, str] = driver or {}
        # Optional JDBC URL parameters, merged over the type's secure defaults.
        self.url_params: Dict[str, str] = {str(k): str(v) for k, v in (url_params or {}).items()}

    _REQUIRED_DRIVER_CONFIG_KEYS = frozenset(
        {"class", "version", "jar_template", "maven_template", "url", "default_port", "test_query"}
    )

    @classmethod
    def register_driver(cls, name: str, config: Dict[str, Any]) -> None:
        """Register a brand-new source_type, process-wide.

        This mutates `DRIVERS` at the class level, so it affects every
        ConnectionManager/JDBCConnector in the process — use it only to add
        support for a database type not already in DRIVERS. To tweak the
        version/jar/maven/class/sha256 of an *existing* type, use the per-source
        `driver:` override block in sources.yaml instead (see `driver_overrides`);
        that does not require touching this registry at all.
        """
        missing = cls._REQUIRED_DRIVER_CONFIG_KEYS - config.keys()
        if missing:
            raise ValueError(
                f"Driver config for '{name}' missing required key(s): {sorted(missing)}"
            )
        cls.DRIVERS[name.lower()] = dict(config)

    def get_jdbc_url(self) -> str:
        """Returns formatted JDBC URL for the configured database."""
        config = self.DRIVERS[self.source_type]
        url = config["url"].format(host=self.host, port=self.port, database=self.database)

        params = {**config.get("default_url_params", {}), **self.url_params}
        if params:
            sep = config.get("url_param_separator", "?")
            if sep == "?" and "?" in url:
                sep = "&"
            joined = (";" if sep == ";" else "&").join(f"{k}={v}" for k, v in params.items())
            url += sep + joined
        return url

    def get_driver_class(self) -> str:
        """Returns JDBC driver class name (override > default)."""
        return self.driver_overrides.get("class") or self.DRIVERS[self.source_type]["class"]

    def get_driver_jar(self) -> str:
        """Returns JAR filename: explicit override > template rendered with effective version."""
        config = self.DRIVERS[self.source_type]
        if self.driver_overrides.get("jar"):
            return self.driver_overrides["jar"]
        version = self.driver_overrides.get("version") or config["version"]
        return config["jar_template"].format(version=version)

    def get_driver_download_url(self) -> str:
        """Returns Maven URL: explicit override > template rendered with effective version."""
        config = self.DRIVERS[self.source_type]
        if self.driver_overrides.get("maven"):
            return self.driver_overrides["maven"]
        version = self.driver_overrides.get("version") or config["version"]
        return config["maven_template"].format(version=version)

    def get_default_port(self) -> int:
        """Returns default port for the database type."""
        return self.DRIVERS[self.source_type]["default_port"]

    def download_driver(
        self, lib_dir: Path, max_retries: int = 3, retry_delay: float = 2.0
    ) -> Path:
        """
        Downloads JDBC driver JAR to lib directory if not already present.

        Args:
            lib_dir: Directory to save JAR file
            max_retries: Maximum number of download attempts (default: 3)
            retry_delay: Delay in seconds between retries (default: 2.0)

        Returns:
            Path to the downloaded/existing JAR file

        Raises:
            ValueError: If max_retries is less than 1
            Exception: If download fails after all retry attempts
        """
        if max_retries < 1:
            raise ValueError(f"max_retries must be >= 1, got {max_retries}")

        lib_dir.mkdir(parents=True, exist_ok=True)

        jar_name = self.get_driver_jar()
        jar_path = lib_dir / jar_name

        if jar_path.exists():
            logger.info(f"✓ Driver already exists: {jar_path}")
            return jar_path

        download_url = self.get_driver_download_url()
        logger.info(f"Downloading {jar_name} from Maven (max retries: {max_retries})...")

        expected_sha256 = (self.driver_overrides.get("sha256") or "").strip().lower()
        if not expected_sha256:
            # A JAR downloaded over the network and loaded into the Spark/JVM
            # classpath is remote code execution if tampered with in transit
            # or on the Maven mirror — integrity verification is required by
            # default, not opt-in. Add `driver: {sha256: <hex>}` to the
            # source config (or set `allow_unverified_driver_download: true`
            # to explicitly accept the risk, e.g. for a private mirror whose
            # JAR hash isn't known in advance).
            if not self.driver_overrides.get("allow_unverified_driver_download"):
                raise ConfigurationError(
                    f"No sha256 configured for driver '{jar_name}' — refusing to download "
                    "an unverified JAR. Add `driver: {sha256: <hex>}` to the source config, "
                    "or set `driver: {allow_unverified_driver_download: true}` to explicitly "
                    "accept the risk."
                )
            logger.warning(
                "No sha256 configured for driver '{}' — downloading unverified "
                "(allow_unverified_driver_download=true).",
                jar_name,
            )

        last_exception = None
        for attempt in range(1, max_retries + 1):
            try:
                urllib.request.urlretrieve(download_url, jar_path)
                if expected_sha256:
                    self._verify_sha256(jar_path, expected_sha256)
                logger.info(f"✓ Downloaded to: {jar_path}")
                return jar_path
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    logger.warning(
                        f"Download attempt {attempt}/{max_retries} failed: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Download failed after {max_retries} attempts: {e}")

        logger.info(f"Manual download: {download_url}")
        raise last_exception

    @staticmethod
    def _verify_sha256(jar_path: Path, expected_hex: str) -> None:
        """Compare the JAR's SHA-256 against the configured checksum; delete on mismatch."""
        import hashlib

        digest = hashlib.sha256(jar_path.read_bytes()).hexdigest()
        if digest != expected_hex:
            jar_path.unlink(missing_ok=True)
            raise ValueError(
                f"Checksum mismatch for {jar_path.name}: expected sha256 {expected_hex}, "
                f"got {digest}. The download was discarded."
            )
        logger.info(f"✓ Verified sha256 for {jar_path.name}")

    def test_connection(self, timeout_seconds: int = 10) -> bool:
        """
        Test JDBC connection using Spark.

        Args:
            timeout_seconds: Timeout in seconds for connection test (default: 10)

        Returns:
            True if connection is successful, False otherwise.
        """
        # Only Spark's own availability/session-state gates the "skip, will
        # validate later" fallback below. A blanket `except Exception: return
        # True` around the whole method previously also swallowed real
        # config/connectivity bugs (bad JDBC URL, bad driver class, an actual
        # connection failure raised somewhere it wasn't expected) and
        # reported them as a successful connection test.
        try:
            from pyspark.sql import SparkSession
        except ImportError:
            logger.warning("PySpark not available. Skipping connection test.")
            return True

        spark = SparkSession.getActiveSession()
        if spark is None:
            logger.warning(
                "No active SparkSession. Skipping connection test. "
                "Connection will be validated during pipeline execution."
            )
            return True

        jdbc_url = self.get_jdbc_url()
        driver_class = self.get_driver_class()

        properties = {
            "user": self.username,
            "password": self.password,
            "driver": driver_class,
            "fetchSize": "1",
            # JDBC-level timeout (in seconds) for the validation query.
            "queryTimeout": str(timeout_seconds),
        }

        logger.info(
            f"Testing connection to {self.source_type}://{self.host}:{self.port}/{self.database} "
            f"(timeout: {timeout_seconds}s)..."
        )

        try:
            # Try to read a single row from a simple query (database-specific).
            # The test query is already formatted as a subquery with an alias,
            # so it is passed as the `table` argument of DataFrameReader.jdbc.
            query = self._get_test_query()
            df = spark.read.jdbc(url=jdbc_url, table=query, properties=properties)
            df.limit(1).collect()

            logger.info(f"✓ Connection successful. Database: {self.source_type}, Host: {self.host}")
            return True

        except Exception as e:
            logger.error(f"✗ Connection failed: {e}")
            logger.info(f"Verify credentials and network connectivity to {self.host}:{self.port}")
            return False

    def _get_test_query(self) -> str:
        """Returns a simple SELECT query to test connection."""
        return self.DRIVERS[self.source_type]["test_query"]

    def discover_tables(self) -> list:
        """Discover available tables/views in the database.

        Returns:
            List of table names available in the database
        """
        try:
            from pyspark.sql import SparkSession

            spark = SparkSession.getActiveSession()
            if spark is None:
                logger.warning("SparkSession not available. Cannot discover tables.")
                return []

            jdbc_url = self.get_jdbc_url()
            driver_class = self.get_driver_class()

            properties = {
                "user": self.username,
                "password": self.password,
                "driver": driver_class,
            }

            # Database-specific queries to discover tables
            discovery_queries = {
                "postgresql": "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
                "mysql": "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()",
                "mariadb": "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()",
                "sqlserver": "SELECT name FROM sys.tables WHERE type = 'U'",
                "oracle": "SELECT table_name FROM user_tables",
                "snowflake": "SELECT table_name FROM information_schema.tables WHERE table_schema = 'PUBLIC'",
            }

            query = discovery_queries.get(self.source_type)
            if not query:
                logger.warning(f"Table discovery not supported for {self.source_type}")
                return []

            logger.info(f"Discovering tables in {self.source_type}...")
            # Wrap the discovery query as a subquery with an alias so it can be
            # passed as the `table` argument of DataFrameReader.jdbc.
            df = spark.read.jdbc(
                url=jdbc_url, table=f"({query}) AS discovery", properties=properties
            )
            tables = df.collect()
            table_names = [row[0] for row in tables]

            logger.info(f"Found {len(table_names)} tables: {', '.join(table_names)}")
            return sorted(table_names)

        except ImportError:
            logger.warning("PySpark not available. Cannot discover tables.")
            return []
        except Exception as e:
            logger.error(f"Failed to discover tables: {e}")
            return []
