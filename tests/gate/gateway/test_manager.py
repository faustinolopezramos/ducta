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
    def test_ambiguous_true_does_not_trip_breaker(self, mock_create, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = self._write_cfg(
            temp_dir,
            "circuit_breaker:\n      enabled: true\n      failure_threshold: 1\n",
        )
        cm = ConnectionManager(cfg)
        mock_connector = MagicMock()
        mock_connector.test_connection.return_value = True  # e.g. no active Spark session
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

    def test_no_sources_is_a_noop(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text("sources: {}\n")
        cm = ConnectionManager(cfg)
        cm.prefetch_drivers()  # must not raise

    def test_best_effort_across_sources(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text(
            "sources:\n"
            "  good1:\n    type: postgresql\n    host: h\n    port: 5432\n    database: d\n"
            "  bad:\n    type: mysql\n    host: h\n    port: 3306\n    database: d\n"
            "  good2:\n    type: sqlserver\n    host: h\n    port: 1433\n    database: d\n"
        )
        cm = ConnectionManager(cfg)

        def fake_download(self, lib_dir):
            if self.source_type == "mysql":
                raise RuntimeError("network down")
            return lib_dir / "fake.jar"

        with (
            patch("ducta.gate.gateway.connector.JDBCConnector.download_driver", fake_download),
            patch.object(ConnectionManager, "_add_jar_to_spark"),
        ):
            cm.prefetch_drivers(max_workers=3)

    def test_prepare_driver_for_source_skips_missing_type(self, temp_dir):
        from ducta.gate.gateway.manager import ConnectionManager

        cfg = temp_dir / "sources.yaml"
        cfg.write_text("sources:\n  db:\n    host: h\n")
        cm = ConnectionManager(cfg)
        with patch("ducta.gate.gateway.connector.JDBCConnector.download_driver") as mock_download:
            cm._prepare_driver_for_source(("db", {"host": "h"}))
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
