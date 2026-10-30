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
        assert "trustServerCertificate=false" in url  # the server's certificate is checked


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
            "postgresql", "h", 1, "d", "u", "p", driver={"maven": "https://custom.url/driver.jar"}
        )
        assert c.get_driver_download_url() == "https://custom.url/driver.jar"

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

    def teardown_method(self):
        JDBCConnector.DRIVERS.pop("fakedb", None)

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

    @patch("ducta.gate.gateway.connector.JDBCConnector._fetch")
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

    @patch("ducta.gate.gateway.connector.JDBCConnector._fetch")
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

    @patch("ducta.gate.gateway.connector.JDBCConnector._fetch")
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
        # Nothing was tested: None, not the True that read as "it works".
        assert c.test_connection() is None

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


class TestConnectionTargetCannotAddUrlParameters:
    """``host`` and ``database`` are pasted into the JDBC URL. A value carrying ``?``, ``;``,
    ``&`` or ``:port/…#`` used to add driver parameters (``autoDeserialize=true``) or point the URL
    at another server, and ``ConnectionSpec`` only checked that the fields were not empty."""

    @pytest.mark.parametrize(
        "host",
        [
            "db.corp",
            "h",
            "my_db",
            "my-db-1.eu",
            "10.0.0.5",
            "server\\SQLEXPRESS",
            "[::1]",
            "[2001:db8::1]",
            "acct.eu-west-1.snowflakecomputing.com",
        ],
    )
    def test_ordinary_hosts_are_accepted(self, host):
        assert JDBCConnector("postgresql", host, 5432, "d", "u", "p").host == host

    @pytest.mark.parametrize(
        "host",
        [
            "evil.example:3306/x?autoDeserialize=true#",
            "h?x=1",
            "h;x=1",
            "h&x=1",
            "h/x",
            "h@x",
            "a b",
            "-h",
            "h-",
            "",
            None,
        ],
    )
    def test_a_host_that_is_not_just_a_host_is_refused(self, host):
        with pytest.raises(ValueError, match="Invalid host"):
            JDBCConnector("mysql", host, 3306, "d", "u", "p")

    @pytest.mark.parametrize(
        "database",
        ["shop", "ANALYTICS_DB", "my-db", "db.sch", "orcl$1"],
    )
    def test_ordinary_database_names_are_accepted(self, database):
        assert JDBCConnector("mysql", "h", 3306, database, "u", "p").database == database

    @pytest.mark.parametrize(
        "database",
        [
            "shop?allowLoadLocalInfile=true&autoDeserialize=true",
            "d;trustServerCertificate=true;encrypt=false",
            "a&b",
            "a=b",
            "d/x",
            "a b",
            "",
            "x" * 129,
        ],
    )
    def test_a_database_that_adds_parameters_is_refused(self, database):
        with pytest.raises(ValueError, match="Invalid database"):
            JDBCConnector("mysql", "h", 3306, database, "u", "p")

    def test_the_generated_url_has_only_the_expected_parameters(self):
        # on this machine: nothing but what was configured
        url = JDBCConnector("mysql", "localhost", 3306, "shop", "u", "p").get_jdbc_url()
        assert url == "jdbc:mysql://localhost:3306/shop"
        url = JDBCConnector(
            "mysql", "localhost", 3306, "shop", "u", "p", url_params={"connectTimeout": "5"}
        ).get_jdbc_url()
        assert url == "jdbc:mysql://localhost:3306/shop?connectTimeout=5"
        # elsewhere: the TLS check, plus what was configured
        url = JDBCConnector(
            "mysql", "db.corp", 3306, "shop", "u", "p", url_params={"connectTimeout": "5"}
        ).get_jdbc_url()
        assert url == "jdbc:mysql://db.corp:3306/shop?sslMode=VERIFY_IDENTITY&connectTimeout=5"

    @pytest.mark.parametrize("port", [5432, "5432"])
    def test_a_port_may_be_written_as_a_number_or_digits(self, port):
        assert JDBCConnector("postgresql", "h", port, "d", "u", "p").port == 5432

    @pytest.mark.parametrize("port", [0, 70000, True, "x", None, 1.5, "5432; x"])
    def test_anything_else_is_not_a_port(self, port):
        with pytest.raises(ValueError, match="Invalid port"):
            JDBCConnector("postgresql", "h", port, "d", "u", "p")


class TestUrlParamsStayParameters:
    @pytest.mark.parametrize(
        "params",
        [
            {"sslmode": "require"},
            {"ssl_ca": "/etc/ca.pem"},
            {"token": "abc=="},
            {"applicationName": "ducta etl"},
        ],
    )
    def test_ordinary_parameters_are_accepted(self, params):
        JDBCConnector("postgresql", "h", 5432, "d", "u", "p", url_params=params)

    @pytest.mark.parametrize(
        "params",
        [
            {"k": "v;encrypt=false"},
            {"k": "v&autoDeserialize=true"},
            {"k": "v#frag"},
            {"k": "v\nx"},
            {"bad name": "1"},
            {"1bad": "1"},
        ],
    )
    def test_a_parameter_that_would_start_another_is_refused(self, params):
        with pytest.raises(ValueError, match="JDBC URL parameter"):
            JDBCConnector("postgresql", "h", 5432, "d", "u", "p", url_params=params)


class TestSqlServerChecksTheServerCertificate:
    """The default was ``trustServerCertificate=true``: encrypted, but to whoever answered."""

    def test_the_default_verifies_the_certificate(self):
        url = JDBCConnector("sqlserver", "server", 1433, "db", "u", "p").get_jdbc_url()
        assert "encrypt=true" in url and "trustServerCertificate=false" in url

    def test_a_source_can_still_opt_out_and_is_warned(self):
        with patch("ducta.gate.gateway.connector.logger") as log:
            c = JDBCConnector(
                "sqlserver",
                "dev-box",
                1433,
                "db",
                "u",
                "p",
                url_params={"trustServerCertificate": "true"},
            )
        assert "trustServerCertificate=true" in c.get_jdbc_url()
        warning = log.warning.call_args[0][0]
        assert "certificate is not fully checked" in warning

    def test_the_default_raises_no_warning(self):
        with patch("ducta.gate.gateway.connector.logger") as log:
            JDBCConnector("sqlserver", "server", 1433, "db", "u", "p")
        log.warning.assert_not_called()


class TestSqlServerTlsHint:
    """trustServerCertificate is false by default: a self-signed server fails its TLS
    handshake, and the driver's message does not name the setting."""

    PKIX = (
        "The driver could not establish a secure connection to SQL Server by using SSL "
        "encryption. Error: PKIX path building failed: unable to find valid certification path"
    )

    def test_an_untrusted_certificate_names_the_setting(self):
        c = JDBCConnector("sqlserver", "db", 1433, "shop", "u", "p")
        hint = c.tls_hint(RuntimeError(self.PKIX))
        assert hint and "trustServerCertificate" in hint and "db:1433" in hint

    def test_no_hint_once_the_certificate_is_trusted(self):
        c = JDBCConnector(
            "sqlserver", "db", 1433, "shop", "u", "p", url_params={"trustServerCertificate": "true"}
        )
        assert c.tls_hint(RuntimeError(self.PKIX)) is None

    def test_no_hint_for_other_errors_or_engines(self):
        sqlserver = JDBCConnector("sqlserver", "db", 1433, "shop", "u", "p")
        oracle = JDBCConnector("oracle", "db", 1521, "ORCL", "u", "p")
        assert sqlserver.tls_hint(RuntimeError("Login failed for user 'u'")) is None
        assert oracle.tls_hint(RuntimeError(self.PKIX)) is None


class TestTrailingNewlineIsNotAValidName:
    """``$`` matches before a final newline: a host or database written with one must not pass."""

    @pytest.mark.parametrize("host", ["db.corp\n", "db\n", "[::1]\n"])
    def test_host(self, host):
        with pytest.raises(ValueError, match="Invalid host"):
            JDBCConnector("mysql", host, 3306, "shop", "u", "p")

    def test_database_and_parameter_name(self):
        with pytest.raises(ValueError, match="Invalid database"):
            JDBCConnector("mysql", "h", 3306, "shop\n", "u", "p")
        with pytest.raises(ValueError, match="parameter name"):
            JDBCConnector("mysql", "h", 3306, "shop", "u", "p", url_params={"a\n": "1"})


class TestTlsDefaultsForRemoteServers:
    @pytest.mark.parametrize(
        "source_type, port, expected",
        [
            ("postgresql", 5432, "sslmode=verify-full"),
            ("mysql", 3306, "sslMode=VERIFY_IDENTITY"),
            ("mariadb", 3306, "sslMode=verify-full"),
        ],
    )
    def test_a_remote_server_is_reached_with_its_certificate_checked(
        self, source_type, port, expected
    ):
        url = JDBCConnector(source_type, "db.corp", port, "shop", "u", "p").get_jdbc_url()
        assert expected in url

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "LocalHost"])
    def test_this_machine_keeps_the_driver_default(self, host):
        url = JDBCConnector("postgresql", host, 5432, "shop", "u", "p").get_jdbc_url()
        assert "sslmode" not in url

    def test_a_source_that_sets_its_own_tls_mode_replaces_the_default(self):
        c = JDBCConnector(
            "postgresql", "db.corp", 5432, "shop", "u", "p", url_params={"sslmode": "require"}
        )
        assert c.get_jdbc_url().count("sslmode") == 1 and "sslmode=require" in c.get_jdbc_url()

    def test_relaxing_it_on_a_remote_server_is_warned(self):
        with patch("ducta.gate.gateway.connector.logger") as log:
            JDBCConnector(
                "postgresql", "db.corp", 5432, "shop", "u", "p", url_params={"sslmode": "disable"}
            )
        assert "sslmode=disable" in str(log.warning.call_args)

    @pytest.mark.parametrize(
        "source_type, params, named",
        [
            ("mysql", {"useSSL": "false"}, "useSSL=false"),
            ("mysql", {"useSSL": "true"}, "useSSL=true"),
            ("postgresql", {"ssl": "false"}, "ssl=false"),
            ("mariadb", {"useSsl": "false"}, "useSsl=false"),
            ("sqlserver", {"encrypt": "false"}, "encrypt=false"),
        ],
    )
    def test_another_switch_that_drops_the_check_is_warned(self, source_type, params, named):
        # Any TLS key suppresses the remote verify default; only sslMode was looked at.
        with patch("ducta.gate.gateway.connector.logger") as log:
            c = JDBCConnector(source_type, "db.corp", 3306, "shop", "u", "p", url_params=params)
        assert named in str(log.warning.call_args)
        assert c.tls_hint(RuntimeError("PKIX path building failed")) is None

    def test_the_mode_parameter_overrides_the_legacy_switch(self):
        with patch("ducta.gate.gateway.connector.logger") as log:
            JDBCConnector(
                "mysql",
                "db.corp",
                3306,
                "shop",
                "u",
                "p",
                url_params={"useSSL": "true", "sslMode": "VERIFY_IDENTITY"},
            )
        log.warning.assert_not_called()

    def test_a_failed_handshake_gets_a_hint_naming_the_setting(self):
        c = JDBCConnector("postgresql", "db.corp", 5432, "shop", "u", "p")
        hint = c.tls_hint(RuntimeError("The server does not support SSL."))
        assert hint and "sslmode" in hint and "db.corp:5432" in hint
        relaxed = JDBCConnector(
            "postgresql", "db.corp", 5432, "shop", "u", "p", url_params={"sslmode": "require"}
        )
        assert relaxed.tls_hint(RuntimeError("The server does not support SSL.")) is None


class TestDriverFileIsInsideTheDriversFolder:
    @pytest.mark.parametrize(
        "jar", ["../../evil.jar", "/etc/x.jar", "sub/x.jar", "x.txt", "x.jar\n"]
    )
    def test_a_jar_override_cannot_leave_the_folder(self, jar):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p", driver={"jar": jar})
        with pytest.raises(ConfigurationError, match="Invalid driver jar name"):
            c.get_driver_jar()

    def test_a_version_cannot_carry_a_path(self):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p", driver={"version": "../../x"})
        with pytest.raises(ConfigurationError, match="Invalid driver version"):
            c.get_driver_jar()

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "http://repo/x.jar", "ftp://repo/x.jar"])
    def test_only_https_downloads(self, url):
        c = JDBCConnector("postgresql", "h", 1, "d", "u", "p", driver={"maven": url})
        with pytest.raises(ConfigurationError, match="only https"):
            c.get_driver_download_url()


class TestDriverDownloadIsVerifiedAndAtomic:
    GOOD = b"the real jar"

    @staticmethod
    def _connector(sha=None):
        import hashlib

        driver = {"sha256": hashlib.sha256(TestDriverDownloadIsVerifiedAndAtomic.GOOD).hexdigest()}
        return JDBCConnector(
            "postgresql", "h", 1, "d", "u", "p", driver=driver if sha is None else sha
        )

    def test_a_tampered_jar_already_in_the_folder_is_replaced(self, tmp_path):
        c = self._connector()
        (tmp_path / "postgresql-42.6.0.jar").write_bytes(b"planted")
        with patch.object(
            JDBCConnector, "_fetch", lambda self, url, dest: dest.write_bytes(self.GOOD)
        ):
            c.GOOD = self.GOOD
            jar = c.download_driver(tmp_path, retry_delay=0)
        assert jar.read_bytes() == self.GOOD

    def test_a_good_jar_in_the_folder_is_kept_without_downloading(self, tmp_path):
        c = self._connector()
        (tmp_path / "postgresql-42.6.0.jar").write_bytes(self.GOOD)
        with patch.object(JDBCConnector, "_fetch") as fetch:
            c.download_driver(tmp_path)
        fetch.assert_not_called()

    def test_a_download_that_fails_the_checksum_never_takes_the_final_name(self, tmp_path):
        c = self._connector()
        with patch.object(
            JDBCConnector, "_fetch", lambda self, url, dest: dest.write_bytes(b"tampered")
        ):
            with pytest.raises(ValueError, match="Checksum mismatch"):
                c.download_driver(tmp_path, max_retries=2, retry_delay=0)
        assert list(tmp_path.iterdir()) == []  # neither the jar nor a partial file

    def test_a_cut_download_leaves_nothing_behind(self, tmp_path):
        c = JDBCConnector(
            "postgresql", "h", 1, "d", "u", "p", driver={"allow_unverified_driver_download": True}
        )

        def cut(self, url, dest):
            dest.write_bytes(b"half")
            raise ConnectionError("reset")

        with patch.object(JDBCConnector, "_fetch", cut):
            with pytest.raises(ConnectionError):
                c.download_driver(tmp_path, max_retries=2, retry_delay=0)
        assert list(tmp_path.iterdir()) == []
