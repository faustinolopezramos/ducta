import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_env_credentials():
    with patch.dict(
        "os.environ",
        {"POSTGRESQL_USER": "testuser", "POSTGRESQL_PASSWORD": "testpass"},
        clear=False,
    ):
        yield


class TestConnectionManagerInit:
    def test_config_not_found(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        with pytest.raises(FileNotFoundError, match="not found"):
            ConnectionManager(temp_dir / "nonexistent.yaml")

    def test_yaml_config(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  test_db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        cm = ConnectionManager(cfg)
        assert "test_db" in cm.sources

    def test_json_config(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.json"
        cfg.write_text(
            '{"sources": {"test_db": {"type": "postgresql", "host": "localhost", "port": 5432, "database": "mydb"}}}'
        )
        cm = ConnectionManager(cfg)
        assert "test_db" in cm.sources

    def test_toml_config_raises_if_no_toml(self, temp_dir):
        import importlib

        if importlib.util.find_spec("toml") is None:
            from ducta.gate.gateway.manager import ConnectionManager

            cfg = temp_dir / "sources.toml"
            cfg.write_text(
                '[sources]\n[sources.test_db]\ntype = "postgresql"\nhost = "localhost"\nport = 5432\ndatabase = "mydb"\n'
            )
            with pytest.raises(ImportError, match="toml"):
                ConnectionManager(cfg)

    def test_unsupported_format(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.ini"
        cfg.write_text("[sources]\n")
        with pytest.raises(ValueError, match="Unsupported format"):
            ConnectionManager(cfg)

    def test_get_source_info_nonexistent(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text("sources: {}\n")
        cm = ConnectionManager(cfg)
        with pytest.raises(ValueError, match="not found"):
            cm.get_source_info("db")


class TestConnectionManagerGet:
    def test_get_nonexistent(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text("sources: {}\n")
        cm = ConnectionManager(cfg)
        with pytest.raises(ValueError, match="not found"):
            cm.get("nonexistent")

    def test_list_sources(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  a:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: db1\n"
        )
        cm = ConnectionManager(cfg)
        sources = cm.list_sources()
        assert "a" in sources


class TestConnection:
    @patch("ducta.gate.gateway.manager.ConnectionManager._create_connector")
    def test_jdbc_url_property(self, mock_create, temp_dir):
        from ducta.gate.gateway.manager import Connection, ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        cm = ConnectionManager(cfg)
        mock_connector = MagicMock()
        mock_connector.get_jdbc_url.return_value = "jdbc:postgresql://localhost:5432/mydb"
        mock_create.return_value = mock_connector
        conn = cm.get("db")
        assert conn.jdbc_url == "jdbc:postgresql://localhost:5432/mydb"

    @patch("ducta.gate.gateway.manager.ConnectionManager._create_connector")
    def test_jdbc_properties(self, mock_create, temp_dir):
        from ducta.gate.gateway.manager import Connection, ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        cm = ConnectionManager(cfg)
        mock_connector = MagicMock()
        mock_connector.username = "testuser"
        mock_connector.password = "testpass"
        mock_connector.get_driver_class.return_value = "org.postgresql.Driver"
        mock_create.return_value = mock_connector
        conn = cm.get("db")
        props = conn.jdbc_properties
        assert props["user"] == "testuser"
        assert props["password"] == "testpass"
        assert props["driver"] == "org.postgresql.Driver"

    @patch("ducta.gate.gateway.manager.ConnectionManager._create_connector")
    def test_get_source_info(self, mock_create, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n    description: My DB\n"
        )
        cm = ConnectionManager(cfg)
        info = cm.get_source_info("db")
        assert info["name"] == "db"
        assert info["type"] == "postgresql"
        assert info["description"] == "My DB"


class TestCircuitBreakerIntegration:
    def _write_cfg(self, temp_dir, extra_yaml=""):
        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n"
            "    database: mydb\n" + extra_yaml
        )
        return cfg

    @patch("ducta.gate.gateway.manager.ConnectionManager._create_connector")
    def test_no_breaker_by_default(self, mock_create, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = self._write_cfg(temp_dir)
        cm = ConnectionManager(cfg)
        mock_create.return_value = MagicMock()
        conn = cm.get("db")
        assert conn._breaker is None
        assert cm.is_circuit_open("db") is False

    @patch("ducta.gate.gateway.manager.ConnectionManager._create_connector")
    def test_breaker_enabled_via_sources_yaml(self, mock_create, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = self._write_cfg(
            temp_dir,
            "circuit_breaker:\n      enabled: true\n      failure_threshold: 2\n",
        )
        cm = ConnectionManager(cfg)
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = False
        mock_create.return_value = mock_connector

        conn = cm.get("db")
        assert conn._breaker is not None
        conn.test_connection()
        conn.test_connection()
        assert cm.is_circuit_open("db") is True

    @patch("ducta.gate.gateway.manager.ConnectionManager._create_connector")
    def test_test_connection_raises_when_circuit_open(self, mock_create, temp_dir):
        from ducta.gate.gateway.exceptions import JDBCCircuitOpenError
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = self._write_cfg(
            temp_dir,
            "circuit_breaker:\n      enabled: true\n      failure_threshold: 1\n",
        )
        cm = ConnectionManager(cfg)
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = False
        mock_create.return_value = mock_connector

        conn = cm.get("db")
        conn.test_connection()  # trips the breaker
        with pytest.raises(JDBCCircuitOpenError):
            conn.test_connection()
        # The connector's real test_connection should not be called a second time.
        assert mock_connector.test_connection.call_count == 1

    @patch("ducta.gate.gateway.manager.ConnectionManager._create_connector")
    def test_untested_does_not_trip_breaker(self, mock_create, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = self._write_cfg(
            temp_dir,
            "circuit_breaker:\n      enabled: true\n      failure_threshold: 1\n",
        )
        cm = ConnectionManager(cfg)
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = None  # no active Spark session
        mock_create.return_value = mock_connector

        conn = cm.get("db")
        for _ in range(5):
            conn.test_connection()
        assert cm.is_circuit_open("db") is False


class TestPrefetchDrivers:
    def test_constructor_never_downloads(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        with patch("ducta.gate.gateway.connector.JDBCConnector.download_driver") as mock_download:
            ConnectionManager(cfg)
        mock_download.assert_not_called()


class TestConnectionMissingCredentials:
    def test_missing_env_vars(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        cm = ConnectionManager(cfg)
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Missing credentials"):
                cm.get("db")


class TestConnectionCredentialsKeyedByName:
    """Regression: _create_connector used to key credentials off
    source_type.upper() only, so two connections of the same DB engine
    would silently read each other's credentials from .env."""

    def test_prefers_connection_name_prefixed_credentials(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        cm = ConnectionManager(cfg)
        with patch.dict(
            "os.environ",
            {
                "DB_USER": "name-scoped-user",
                "DB_PASSWORD": "name-scoped-pass",
                # Deliberately different, to prove the name-scoped pair wins.
                "POSTGRESQL_USER": "type-scoped-user",
                "POSTGRESQL_PASSWORD": "type-scoped-pass",
            },
            clear=True,
        ):
            connector = cm._create_connector("db")

        assert connector.username == "name-scoped-user"
        assert connector.password == "name-scoped-pass"


class TestEnvFileOnlyYieldsCredentials:
    """The gateway used to copy every entry of a `.env` into ``os.environ``. A file holding
    ``JAVA_TOOL_OPTIONS`` or ``AUTH_ENABLED`` therefore set them for the JVM Spark starts next
    and for anything else the process runs. It now copies nothing: the gateway reads the
    connection's two credential keys out of the project's ``.env`` and hands them over."""

    HOSTILE = (
        "CRM_USER=alice\n"
        "CRM_PASSWORD=secret\n"
        "JAVA_TOOL_OPTIONS=-javaagent:/tmp/agent.jar\n"
        "AUTH_ENABLED=false\n"
        "PYTHONPATH=/tmp/evil\n"
        "OTHER_USER=bob\n"
        "OTHER_PASSWORD=bobpw\n"
        "SUDO_USER=root\n"
    )

    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        proj = tmp_path / "proj" / "sub"
        proj.mkdir(parents=True)
        (proj / ".env").write_text(self.HOSTILE)
        (proj / "sources.yaml").write_text(
            "sources:\n  crm:\n    type: postgresql\n    host: h\n    port: 5432\n    database: d\n"
        )
        monkeypatch.chdir(proj)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
        return proj

    def _connect(self, project, env=None):
        from ducta.gate.gateway.manager import ConnectionManager

        with patch.dict("os.environ", env or {}, clear=True):
            cm = ConnectionManager(project / "sources.yaml")
            with patch("ducta.gate.gateway.connector.JDBCConnector.download_driver"):
                connector = cm._create_connector("crm")
            return connector, dict(os.environ)

    def test_the_connection_gets_its_own_pair(self, project):
        connector, _ = self._connect(project)
        assert (connector.username, connector.password) == ("alice", "secret")

    def test_nothing_of_the_file_reaches_the_environment(self, project):
        _, env = self._connect(project)
        assert env == {}

    def test_another_sources_credentials_are_not_used(self, project):
        (project / ".env").write_text("OTHER_USER=bob\nOTHER_PASSWORD=bobpw\nSUDO_USER=root\n")
        with pytest.raises(ValueError, match="Missing credentials"):
            self._connect(project)

    def test_a_real_environment_variable_still_wins(self, project):
        connector, _ = self._connect(project, {"CRM_PASSWORD": "from-the-environment"})
        assert (connector.username, connector.password) == ("alice", "from-the-environment")

    def test_an_env_file_outside_the_project_is_not_read(self, project, tmp_path):
        """The parent folder's and the home folder's ``.env`` belong to something else."""
        (project / ".env").unlink()
        (project.parent / ".env").write_text("CRM_USER=parent\nCRM_PASSWORD=parentpw\n")
        (tmp_path / "home" / ".env").write_text("CRM_USER=home\nCRM_PASSWORD=homepw\n")
        with pytest.raises(ValueError, match="Missing credentials"):
            self._connect(project)
