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

import os
import re
import shutil
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

from ducta.gate.exceptions import ConfigurationError

#: Spark JDBC read options a node may not set. Ducta takes the server and driver from the
#: source (``url``, ``driver``) and the statement from ``table``/``query`` after sanitizing it,
#: so an option that names them would replace what was checked; ``sessionInitStatement`` and
#: ``prepareQuery`` run SQL of their own. (``user`` and ``password`` stay settable: they change
#: who the node signs in as on the source's own server, not where it connects or what it runs.)
#: Spark reads option names without regard to case, so the comparison is case-insensitive too.
RESERVED_READ_OPTIONS = frozenset(
    {"url", "driver", "dbtable", "query", "sessioninitstatement", "preparequery"}
)


def reserved_read_options(options: Any) -> List[str]:
    """The names in ``options`` that a node may not set (as written), sorted."""
    if not isinstance(options, dict):
        return []
    return sorted(str(k) for k in options if str(k).lower() in RESERVED_READ_OPTIONS)


#: (The three patterns below are matched with ``fullmatch``: ``$`` also accepts a trailing newline.)
#:
#: A host name or address, as it goes between ``//`` and ``:port`` in a JDBC URL. Letters,
#: digits, ``.``, ``-``, ``_`` and a backslash for a SQL Server instance (``host\SQLEXPRESS``); or a
#: bracketed IPv6 address. Anything else (``:``, ``/``, ``?``, ``;``, ``&``, ``=``, ``#``, ``@``,
#: spaces) would let the value add parameters to the URL or point it at another server.
_HOST_RE = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9._\\-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\])")

#: A database, SID or service name: letters, digits, ``_``, ``$``, ``.``, ``-``.
_DATABASE_RE = re.compile(r"[A-Za-z0-9_$.\-]+")

#: A JDBC URL parameter name.
_PARAM_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.]*")

#: A driver version (it goes into a file name and a URL) and the name of the JAR file.
_DRIVER_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]*")
_JAR_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]*\.jar")

#: Characters that end one URL parameter and start another (or the fragment).
_PARAM_VALUE_FORBIDDEN = re.compile(r"[;&#\x00-\x1f\x7f]")


def check_jdbc_host(host: Any) -> None:
    """Raise ``ValueError`` unless ``host`` is a plain host name or address."""
    if not isinstance(host, str) or len(host) > 255 or not _HOST_RE.fullmatch(host):
        raise ValueError(
            f"Invalid host {host!r}: give a host name or IP address only. The port, the "
            "database and any JDBC parameter have their own settings (`port`, `database`, "
            "`url_params`)."
        )


def check_jdbc_database(database: Any) -> None:
    """Raise ``ValueError`` unless ``database`` is a plain database / SID / service name."""
    if not isinstance(database, str) or len(database) > 128 or not _DATABASE_RE.fullmatch(database):
        raise ValueError(
            f"Invalid database {database!r}: use letters, digits, '_', '$', '.' and '-' only. "
            "A '?', ';', '&' or '=' would add parameters to the connection URL; put those in "
            "`url_params`."
        )


def check_jdbc_port(port: Any) -> int:
    """The port as an ``int``, or ``ValueError`` if it is not one in 1..65535."""
    if isinstance(port, bool) or not (
        isinstance(port, int) or (isinstance(port, str) and port.strip().isdigit())
    ):
        raise ValueError(f"Invalid port: {port!r}")
    number = int(port)
    if not 0 < number <= 65535:
        raise ValueError(f"Invalid port: {port!r}")
    return number


def check_jdbc_url_params(params: Dict[str, str]) -> None:
    """Raise ``ValueError`` if a parameter's name or value could break out of its place in the URL."""
    for name, value in params.items():
        if not _PARAM_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid JDBC URL parameter name {name!r}")
        if _PARAM_VALUE_FORBIDDEN.search(value):
            raise ValueError(
                f"Invalid value for JDBC URL parameter {name!r}: it cannot contain ';', '&', '#' "
                "or control characters, which would start another parameter."
            )


class JDBCConnector:
    """Manages JDBC configuration and driver download for database ingestion."""

    DRIVERS: Dict[str, Dict[str, Any]] = {
        "sqlserver": {
            "class": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
            "version": "9.4.1.jre11",
            "jar_template": "mssql-jdbc-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/com/microsoft/sqlserver/mssql-jdbc/{version}/mssql-jdbc-{version}.jar",
            "url": "jdbc:sqlserver://{host}:{port};databaseName={database}",
            # Encrypted, and the server's certificate is checked. A server with a self-signed
            # one needs `url_params: {trustServerCertificate: "true"}` on its source.
            "default_url_params": {"encrypt": "true", "trustServerCertificate": "false"},
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
            # For a server that is not on this machine: TLS, with the certificate and the
            # host name checked. Setting any of `remote_tls_keys` in `url_params` replaces it.
            "remote_url_params": {"sslmode": "verify-full"},
            "remote_tls_keys": ("sslmode", "ssl"),
            "default_port": 5432,
            "test_query": "(SELECT 1 AS test_col) AS test_table",
        },
        "mysql": {
            "class": "com.mysql.cj.jdbc.Driver",
            "version": "8.0.33",
            "jar_template": "mysql-connector-java-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/mysql/mysql-connector-java/{version}/mysql-connector-java-{version}.jar",
            "url": "jdbc:mysql://{host}:{port}/{database}",
            "remote_url_params": {"sslMode": "VERIFY_IDENTITY"},
            "remote_tls_keys": ("sslmode", "usessl"),
            "default_port": 3306,
            "test_query": "(SELECT 1 AS test_col) AS test_table",
        },
        "mariadb": {
            "class": "org.mariadb.jdbc.Driver",
            "version": "3.1.4",
            "jar_template": "mariadb-java-client-{version}.jar",
            "maven_template": "https://repo1.maven.org/maven2/org/mariadb/jdbc/mariadb-java-client/{version}/mariadb-java-client-{version}.jar",
            "url": "jdbc:mariadb://{host}:{port}/{database}",
            "remote_url_params": {"sslMode": "verify-full"},
            "remote_tls_keys": ("sslmode", "usessl", "ssl"),
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

        check_jdbc_host(host)
        check_jdbc_database(database)
        port = check_jdbc_port(port)

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
        check_jdbc_url_params(self.url_params)

        self._warn_if_unverified()

    #: Hosts that are this machine: a server there is not reached over a network, so the
    #: remote TLS defaults do not apply (a local Docker database rarely has a certificate).
    _LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

    def is_remote(self) -> bool:
        """Whether the server is anywhere but this machine."""
        return self.host.lower() not in self._LOOPBACK_HOSTS

    def effective_url_params(self) -> Dict[str, str]:
        """The URL parameters in force: the type's defaults, the remote TLS ones, then the source's."""
        config = self.DRIVERS[self.source_type]
        params: Dict[str, str] = dict(config.get("default_url_params", {}))
        own_tls = {str(k).lower() for k in self.url_params}
        if self.is_remote() and not own_tls & set(config.get("remote_tls_keys", ())):
            params.update(config.get("remote_url_params", {}))
        params.update(self.url_params)
        return params

    #: ``(parameter, values that leave the server's identity unchecked)`` per type.
    _UNVERIFIED = {
        "sqlserver": ("trustServerCertificate", {"true"}),
        "postgresql": ("sslmode", {"disable", "allow", "prefer", "require"}),
        "mysql": ("sslMode", {"disabled", "preferred", "required", "disable", "require"}),
        "mariadb": ("sslMode", {"disable", "trust", "verify-ca"}),
    }

    #: Other TLS switches that drop the check, or TLS itself: ``(parameter, weak values,
    #: parameter that overrides it when set)``. Any of them also suppresses the remote
    #: defaults (``remote_tls_keys``), so they need a look of their own.
    _TLS_OFF = {
        "sqlserver": ("encrypt", {"false"}, None),
        "postgresql": ("ssl", {"false"}, "sslmode"),
        # Connector/J: useSSL=true without sslMode is REQUIRED, which does not verify.
        "mysql": ("useSSL", {"false", "true"}, "sslMode"),
        "mariadb": ("useSsl", {"false"}, "sslMode"),
    }

    def _unverified_setting(self) -> Optional[str]:
        """``name=value`` when the connection does not check the server's certificate, else None."""
        rule = self._UNVERIFIED.get(self.source_type)
        if rule is None:
            return None
        params = {str(k).lower(): str(v) for k, v in self.effective_url_params().items()}
        name, weak = rule
        value = params.get(name.lower())
        if value is not None and value.lower() in weak:
            return f"{name}={value}"
        off = self._TLS_OFF.get(self.source_type)
        if off is not None:
            name, weak, overridden_by = off
            value = params.get(name.lower())
            if (
                value is not None
                and value.lower() in weak
                and not (overridden_by and overridden_by.lower() in params)
            ):
                return f"{name}={value}"
        return None

    def _warn_if_unverified(self) -> None:
        setting = self._unverified_setting()
        if setting and (self.is_remote() or self.source_type == "sqlserver"):
            logger.warning(
                "Source {}://{}: {} — the server's certificate is not fully checked, so the "
                "connection may be encrypted but not authenticated.",
                self.source_type,
                self.host,
                setting,
            )

    #: Driver messages for a server certificate the client does not trust.
    _UNTRUSTED_CERTIFICATE_MARKERS = (
        "pkix path building failed",
        "unable to find valid certification path",
        "certificate_unknown",
        "self-signed certificate",
        "self signed certificate",
        "does not support ssl",
        "ssl is not enabled",
        "ssl not available",
    )

    def tls_hint(self, error: BaseException) -> Optional[str]:
        """What to change when ``error`` is a server refusing, or failing, the TLS check.

        Servers are reached with their certificate checked by default (SQL Server always;
        PostgreSQL, MySQL and MariaDB when the host is not this machine). A dev or Docker
        server with a self-signed certificate, or none, then fails its handshake with a
        driver message that does not name the setting.
        """
        rule = self._UNVERIFIED.get(self.source_type)
        if rule is None or self._unverified_setting() is not None:
            return None
        message = str(error).lower()
        if not any(marker in message for marker in self._UNTRUSTED_CERTIFICATE_MARKERS):
            return None
        name, weak = rule
        relaxed = {
            "sqlserver": "true",
            "postgresql": "require",
            "mysql": "REQUIRED",
            "mariadb": "trust",
        }[self.source_type]
        return (
            f"The {self.source_type} server at {self.host}:{self.port} failed the TLS check "
            "(certificate not trusted, or SSL not offered). Install its CA in the Java "
            "truststore or, for a dev server, add "
            f'`url_params: {{{name}: "{relaxed}"}}` to the source in sources.yaml '
            "(that encrypts without verifying who answers)."
        )

    _REQUIRED_DRIVER_CONFIG_KEYS = frozenset(
        {"class", "version", "jar_template", "maven_template", "url", "default_port", "test_query"}
    )

    @classmethod
    def register_driver(cls, name: str, config: Dict[str, Any]) -> None:
        """Register a brand-new source_type, process-wide."""
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

        params = self.effective_url_params()
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

    def _driver_version(self) -> str:
        version = str(
            self.driver_overrides.get("version") or self.DRIVERS[self.source_type]["version"]
        )
        if not _DRIVER_VERSION_RE.fullmatch(version):
            raise ConfigurationError(
                f"Invalid driver version {version!r}: use letters, digits, '.', '_' and '-' only."
            )
        return version

    def get_driver_jar(self) -> str:
        """Returns JAR filename: explicit override > template rendered with effective version.

        It is a file name inside the drivers folder, never a path out of it.
        """
        config = self.DRIVERS[self.source_type]
        if self.driver_overrides.get("jar"):
            name = str(self.driver_overrides["jar"])
        else:
            name = config["jar_template"].format(version=self._driver_version())
        if not _JAR_NAME_RE.fullmatch(name):
            raise ConfigurationError(
                f"Invalid driver jar name {name!r}: give a file name ending in .jar, "
                "without a folder."
            )
        return name

    def get_driver_download_url(self) -> str:
        """Returns Maven URL: explicit override > template rendered with effective version."""
        config = self.DRIVERS[self.source_type]
        if self.driver_overrides.get("maven"):
            url = str(self.driver_overrides["maven"])
        else:
            url = config["maven_template"].format(version=self._driver_version())
        if not url.lower().startswith("https://"):
            raise ConfigurationError(
                f"Invalid driver download URL {url!r}: only https:// is accepted "
                "(not file://, ftp:// or plain http://)."
            )
        return url

    def get_default_port(self) -> int:
        """Returns default port for the database type."""
        return self.DRIVERS[self.source_type]["default_port"]

    #: Seconds a driver download may wait on the network before it counts as failed.
    DOWNLOAD_TIMEOUT_SECONDS = 60

    def download_driver(
        self, lib_dir: Path, max_retries: int = 3, retry_delay: float = 2.0
    ) -> Path:
        """
        Downloads JDBC driver JAR to lib directory if not already present.

        Every JAR in ``lib_dir`` ends up on Spark's classpath, so one that is there is
        checked against the configured ``sha256`` too (a mismatch is discarded and fetched
        again). A download goes to a temporary file and takes its final name only once
        complete and verified: a cut or tampered download is never left to be trusted.
        """
        if max_retries < 1:
            raise ValueError(f"max_retries must be >= 1, got {max_retries}")

        lib_dir.mkdir(parents=True, exist_ok=True)

        jar_name = self.get_driver_jar()
        jar_path = lib_dir / jar_name
        expected_sha256 = (self.driver_overrides.get("sha256") or "").strip().lower()

        if jar_path.exists():
            if not expected_sha256:
                logger.info(f"✓ Driver already exists: {jar_path}")
                return jar_path
            try:
                self._verify_sha256(jar_path, expected_sha256)
                return jar_path
            except ValueError as error:
                logger.warning("{} Fetching it again.", error)

        download_url = self.get_driver_download_url()
        logger.info(f"Downloading {jar_name} from Maven (max retries: {max_retries})...")

        if not expected_sha256:
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
            partial = jar_path.with_name(f".{jar_name}.{os.getpid()}.part")
            try:
                self._fetch(download_url, partial)
                if expected_sha256:
                    self._verify_sha256(partial, expected_sha256)
                os.replace(partial, jar_path)
                logger.info(f"✓ Downloaded to: {jar_path}")
                return jar_path
            except Exception as e:
                last_exception = e
                partial.unlink(missing_ok=True)
                if attempt < max_retries:
                    logger.warning(
                        f"Download attempt {attempt}/{max_retries} failed: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Download failed after {max_retries} attempts: {e}")

        logger.info(f"Manual download: {download_url}")
        raise last_exception  # type: ignore[misc]

    def _fetch(self, url: str, destination: Path) -> None:
        """Copy ``url`` (https) to ``destination``, giving up after the download timeout."""
        with urllib.request.urlopen(url, timeout=self.DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310 — https only, see get_driver_download_url
            with open(destination, "wb") as handle:
                shutil.copyfileobj(response, handle)

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

    def test_connection(self, timeout_seconds: int = 10) -> Optional[bool]:
        """Test the JDBC connection using Spark.

        ``True``: it answered. ``False``: it did not. ``None``: nothing was
        tested, because there is no Spark to test with. This used to return
        ``True`` for that last case, so every caller reported "connection
        successful" for a connection nobody had contacted.
        """

        try:
            from pyspark.sql import SparkSession
        except ImportError:
            logger.warning("PySpark not available. Skipping connection test.")
            return None

        spark = SparkSession.getActiveSession()
        if spark is None:
            logger.warning(
                "No active SparkSession. Skipping connection test. "
                "Connection will be validated during pipeline execution."
            )
            return None

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
            hint = self.tls_hint(e)
            if hint:
                logger.error(hint)
            else:
                logger.info(
                    f"Verify credentials and network connectivity to {self.host}:{self.port}"
                )
            return False

    def _get_test_query(self) -> str:
        """Returns a simple SELECT query to test connection."""
        return self.DRIVERS[self.source_type]["test_query"]
