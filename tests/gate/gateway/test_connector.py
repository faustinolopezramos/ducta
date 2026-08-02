import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.gate.exceptions import ConfigurationError
from ducta.gate.gateway.connector import JDBCConnector


class TestJDBCConnectorInit:
    def test_valid_source_type(self):
        c = JDBCConnector("postgresql", "localhost", 5432, "mydb", "user", "pass")
        assert c.source_type == "postgresql"

    def test_invalid_source_type(self):
        with pytest.raises(ValueError, match="Unsupported"):
            JDBCConnector("invalid", "host", 1, "db", "u", "p")

    def test_optional_url_params(self):
        c = JDBCConnector(
            "postgresql", "host", 5432, "db", "u", "p", url_params={"sslmode": "require"}
        )
        assert c.url_params["sslmode"] == "require"

    def test_none_url_params(self):
        c = JDBCConnector("postgresql", "host", 5432, "db", "u", "p", url_params=None)
        assert c.url_params == {}


class TestJDBCConnectorGetJdbcUrl:
    def test_postgresql_url(self):
        c = JDBCConnector("postgresql", "localhost", 5432, "mydb", "user", "pass")
        url = c.get_jdbc_url()
        assert url.startswith("jdbc:postgresql://localhost:5432/mydb")

    def test_mysql_url(self):
        c = JDBCConnector("mysql", "localhost", 3306, "mydb", "user", "pass")
        url = c.get_jdbc_url()
        assert url.startswith("jdbc:mysql://localhost:3306/mydb")

    def test_sqlserver_url(self):
        c = JDBCConnector("sqlserver", "server", 1433, "db", "u", "p")
        url = c.get_jdbc_url()
        assert "jdbc:sqlserver://server:1433;databaseName=db" in url

    def test_oracle_url(self):
        c = JDBCConnector("oracle", "host", 1521, "ORCL", "u", "p")
        url = c.get_jdbc_url()
        assert url == "jdbc:oracle:thin:@host:1521:ORCL"

    def test_snowflake_url(self):
        c = JDBCConnector("snowflake", "account", 443, "db", "u", "p")
        url = c.get_jdbc_url()
        assert "jdbc:snowflake://account/" in url

    def test_mariadb_url(self):
        c = JDBCConnector("mariadb", "host", 3306, "db", "u", "p")
        url = c.get_jdbc_url()
        assert url.startswith("jdbc:mariadb://host:3306/db")

    def test_url_with_params(self):
        c = JDBCConnector(
            "postgresql", "host", 5432, "db", "u", "p", url_params={"sslmode": "require"}
        )
        url = c.get_jdbc_url()
        assert "sslmode=require" in url

    def test_sqlserver_default_params(self):
        c = JDBCConnector("sqlserver", "server", 1433, "db", "u", "p")
        url = c.get_jdbc_url()
        assert "encrypt=true" in url
        assert "trustServerCertificate=true" in url


class TestJDBCConnectorDriver:
    def test_get_driver_class_postgresql(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert c.get_driver_class() == "org.postgresql.Driver"

    def test_get_driver_class_mysql(self):
        c = JDBCConnector("mysql", "h", 1, "d", "u", "p")
        assert c.get_driver_class() == "com.mysql.cj.jdbc.Driver"

    def test_driver_override_class(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p", driver={"class": "custom.Driver"})
        assert c.get_driver_class() == "custom.Driver"

    def test_get_driver_jar_default(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert "postgresql" in c.get_driver_jar()

    def test_get_driver_jar_with_version_override(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p", driver={"version": "42.7.0"})
        jar = c.get_driver_jar()
        assert "postgresql-42.7.0" in jar

    def test_get_driver_jar_explicit(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p", driver={"jar": "custom.jar"})
        assert c.get_driver_jar() == "custom.jar"

    def test_get_driver_download_url_default(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        url = c.get_driver_download_url()
        assert "repo1.maven.org" in url

    def test_get_driver_download_url_override(self):
        c = JDBCConnector(
            "postgresql", "h", 1, "d", "u", "p", driver={"maven": "http://custom.url/driver.jar"}
        )
        assert c.get_driver_download_url() == "http://custom.url/driver.jar"

    def test_get_default_port(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert c.get_default_port() == 5432

    # Golden values captured before deduplicating `jar`/`maven` into templates —
    # `get_driver_jar()`/`get_driver_download_url()` without overrides must keep
    # producing exactly these strings for every supported driver.
    _GOLDEN_JAR_AND_MAVEN = {
        "sqlserver": (
            "mssql-jdbc-9.4.1.jre11.jar",
            "https://repo1.maven.org/maven2/com/microsoft/sqlserver/mssql-jdbc/9.4.1.jre11/mssql-jdbc-9.4.1.jre11.jar",
        ),
        "oracle": (
            "ojdbc8-21.9.0.0.jar",
            "https://repo1.maven.org/maven2/com/oracle/database/jdbc/ojdbc8/21.9.0.0/ojdbc8-21.9.0.0.jar",
        ),
        "postgresql": (
            "postgresql-42.6.0.jar",
            "https://repo1.maven.org/maven2/org/postgresql/postgresql/42.6.0/postgresql-42.6.0.jar",
        ),
        "mysql": (
            "mysql-connector-java-8.0.33.jar",
            "https://repo1.maven.org/maven2/mysql/mysql-connector-java/8.0.33/mysql-connector-java-8.0.33.jar",
        ),
        "mariadb": (
            "mariadb-java-client-3.1.4.jar",
            "https://repo1.maven.org/maven2/org/mariadb/jdbc/mariadb-java-client/3.1.4/mariadb-java-client-3.1.4.jar",
        ),
        "snowflake": (
            "snowflake-jdbc-3.13.29.jar",
            "https://repo1.maven.org/maven2/net/snowflake/snowflake-jdbc/3.13.29/snowflake-jdbc-3.13.29.jar",
        ),
    }

    @pytest.mark.parametrize("source_type", list(_GOLDEN_JAR_AND_MAVEN.keys()))
    def test_default_jar_and_maven_are_unchanged(self, source_type):
        expected_jar, expected_maven = self._GOLDEN_JAR_AND_MAVEN[source_type]
        c = JDBCConnector(source_type, "h", 1, "d", "u", "p")
        assert c.get_driver_jar() == expected_jar
        assert c.get_driver_download_url() == expected_maven


class TestJDBCConnectorRegisterDriver:
    def teardown_method(self):
        JDBCConnector.DRIVERS.pop("fakedb", None)

    def test_register_driver_new_type_success(self):
        JDBCConnector.register_driver(
            "fakedb",
            {
                "class": "com.fake.Driver",
                "version": "1.0.0",
                "jar_template": "fakedb-{version}.jar",
                "maven_template": "https://example.org/fakedb-{version}.jar",
                "url": "jdbc:fakedb://{host}:{port}/{database}",
                "default_port": 9999,
                "test_query": "(SELECT 1) AS t",
            },
        )
        c = JDBCConnector("fakedb", "h", 9999, "d", "u", "p")
        assert c.get_driver_class() == "com.fake.Driver"
        assert c.get_driver_jar() == "fakedb-1.0.0.jar"
        assert c.get_default_port() == 9999

    def test_register_driver_missing_required_key_raises(self):
        with pytest.raises(ValueError, match="missing required key"):
            JDBCConnector.register_driver("fakedb", {"class": "com.fake.Driver"})
        assert "fakedb" not in JDBCConnector.DRIVERS

    def test_register_driver_is_process_wide(self):
        JDBCConnector.register_driver(
            "fakedb",
            {
                "class": "com.fake.Driver",
                "version": "1.0.0",
                "jar_template": "fakedb-{version}.jar",
                "maven_template": "https://example.org/fakedb-{version}.jar",
                "url": "jdbc:fakedb://{host}:{port}/{database}",
                "default_port": 9999,
                "test_query": "(SELECT 1) AS t",
            },
        )
        c1 = JDBCConnector("fakedb", "h1", 9999, "d1", "u", "p")
        c2 = JDBCConnector("fakedb", "h2", 9999, "d2", "u", "p")
        assert c1.get_driver_class() == c2.get_driver_class() == "com.fake.Driver"


class TestJDBCConnectorDownload:
    def test_download_already_exists(self, temp_dir):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        jar_path = temp_dir / "postgresql-42.6.0.jar"
        jar_path.write_text("fake jar content")
        result = c.download_driver(temp_dir)
        assert result == jar_path

    def test_download_max_retries_invalid(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        with pytest.raises(ValueError, match="max_retries"):
            c.download_driver(Path("/tmp"), max_retries=0)

    @patch("ducta.gate.gateway.connector.urllib.request.urlretrieve")
    def test_download_success(self, mock_retrieve, temp_dir):
        def _fake_retrieve(url, path):
            Path(path).write_text("fake jar")

        mock_retrieve.side_effect = _fake_retrieve
        c = JDBCConnector(
            "postgresql",
            "h",
            1,
            "d",
            "u",
            "p",
            driver={"allow_unverified_driver_download": True},
        )
        result = c.download_driver(temp_dir)
        assert result.exists()

    @patch("ducta.gate.gateway.connector.urllib.request.urlretrieve")
    def test_download_with_retry_on_failure(self, mock_retrieve, temp_dir):
        call_count = 0

        def _fake_retrieve(url, path):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"fail{call_count}")
            Path(path).write_text("fake jar")

        mock_retrieve.side_effect = _fake_retrieve
        c = JDBCConnector(
            "postgresql",
            "h",
            1,
            "d",
            "u",
            "p",
            driver={"allow_unverified_driver_download": True},
        )
        result = c.download_driver(temp_dir, max_retries=3, retry_delay=0.01)
        assert result.exists()
        assert call_count == 3

    @patch("ducta.gate.gateway.connector.urllib.request.urlretrieve")
    def test_download_all_retries_fail(self, mock_retrieve, temp_dir):
        mock_retrieve.side_effect = Exception("always fails")
        c = JDBCConnector(
            "postgresql",
            "h",
            1,
            "d",
            "u",
            "p",
            driver={"allow_unverified_driver_download": True},
        )
        with pytest.raises(Exception, match="always fails"):
            c.download_driver(temp_dir, max_retries=2, retry_delay=0.01)

    def test_download_without_sha256_or_opt_out_raises(self, temp_dir):
        """Regression: integrity verification is required by default — a
        missing sha256 used to only log a warning and download unverified.
        A JAR loaded into the Spark/JVM classpath is RCE if tampered with."""
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        with pytest.raises(ConfigurationError, match="refusing to download"):
            c.download_driver(temp_dir)

    def test_verify_sha256_success(self, temp_dir):
        import hashlib

        p = temp_dir / "test.jar"
        content = b"test content"
        p.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        JDBCConnector._verify_sha256(p, expected)
        assert p.exists()

    def test_verify_sha256_mismatch(self, temp_dir):
        p = temp_dir / "test.jar"
        p.write_bytes(b"content")
        with pytest.raises(ValueError, match="Checksum mismatch"):
            JDBCConnector._verify_sha256(p, "0000000")
        assert not p.exists()


class TestJDBCConnectorTestConnection:
    @patch("pyspark.sql.SparkSession")
    def test_no_active_spark(self, MockSS):
        MockSS.getActiveSession.return_value = None
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert c.test_connection() is True

    @patch("pyspark.sql.SparkSession")
    def test_connection_success(self, MockSS, spark_session):
        MockSS.getActiveSession.return_value = spark_session
        spark_session.read.jdbc.return_value = spark_session.read
        spark_session.read.limit.return_value = spark_session.read
        spark_session.read.collect.return_value = [MagicMock()]
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert c.test_connection() is True

    @patch("pyspark.sql.SparkSession")
    def test_connection_failure(self, MockSS, spark_session):
        MockSS.getActiveSession.return_value = spark_session
        spark_session.read.jdbc.side_effect = Exception("connection refused")
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert c.test_connection() is False

    def test_get_test_query(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert "SELECT 1" in c._get_test_query()

    @patch("pyspark.sql.SparkSession")
    def test_bug_in_get_jdbc_url_is_not_swallowed_as_success(self, MockSS, spark_session):
        """Regression: a blanket `except Exception: return True` around the
        whole method used to catch a real bug in get_jdbc_url()/
        get_driver_class() (or any other unexpected exception outside the
        actual connection attempt) and report it as a successful connection
        test, instead of only Spark's own availability/session-state gating
        that fallback."""
        MockSS.getActiveSession.return_value = spark_session
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        c.get_jdbc_url = MagicMock(side_effect=RuntimeError("real bug, not a connection issue"))

        with pytest.raises(RuntimeError, match="real bug"):
            c.test_connection()


class TestJDBCConnectorDiscoverTables:
    @patch("pyspark.sql.SparkSession")
    def test_no_active_spark(self, MockSS):
        MockSS.getActiveSession.return_value = None
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert c.discover_tables() == []

    def test_unsupported_type(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        c.source_type = "unsupported"
        assert c.discover_tables() == []

    @patch("pyspark.sql.SparkSession")
    def test_discovery_success(self, MockSS, spark_session):
        MockSS.getActiveSession.return_value = spark_session
        spark_session.read.jdbc.return_value = spark_session.read
        spark_session.read.collect.return_value = [("table1",), ("table2",)]
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        result = c.discover_tables()
        assert result == ["table1", "table2"]

    @patch("pyspark.sql.SparkSession")
    def test_discovery_failure(self, MockSS, spark_session):
        MockSS.getActiveSession.return_value = spark_session
        spark_session.read.jdbc.side_effect = Exception("discovery failed")
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p")
        assert c.discover_tables() == []
