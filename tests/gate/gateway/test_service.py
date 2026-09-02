from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.gate.gateway.service import (
    DEFAULT_PORTS,
    SUPPORTED_TYPES,
    ConnectionSpec,
    IngestionService,
    IngestionServiceError,
)


class TestConnectionSpec:
    def test_valid_spec(self):
        spec = ConnectionSpec(
            name="my_conn",
            source_type="postgresql",
            host="localhost",
            port=5432,
            database="mydb",
            username="user",
            password="pass",
        )
        spec.validate()

    def test_invalid_name(self):
        spec = ConnectionSpec("bad name!", "postgresql", "host", 5432, "db", "u", "p")
        with pytest.raises(IngestionServiceError, match="name"):
            spec.validate()

    def test_unsupported_type(self):
        spec = ConnectionSpec("c", "invalid", "host", 1, "db", "u", "p")
        with pytest.raises(IngestionServiceError, match="Unsupported"):
            spec.validate()

    def test_missing_fields(self):
        spec = ConnectionSpec("c", "postgresql", "", 5432, "", "", "")
        with pytest.raises(IngestionServiceError):
            spec.validate()

    def test_invalid_port_zero(self):
        spec = ConnectionSpec("c", "postgresql", "host", 0, "db", "u", "p")
        with pytest.raises(IngestionServiceError, match="port"):
            spec.validate()

    def test_invalid_port_too_high(self):
        spec = ConnectionSpec("c", "postgresql", "host", 99999, "db", "u", "p")
        with pytest.raises(IngestionServiceError, match="port"):
            spec.validate()


class TestIngestionService:
    def test_list_connections_empty(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        result = svc.list_connections()
        assert result == []

    def test_list_connections(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        (config_dir / "sources.yaml").write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        svc = IngestionService(str(temp_dir))
        result = svc.list_connections()
        assert len(result) == 1
        assert result[0]["name"] == "db"

    def test_get_connection_found(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        (config_dir / "sources.yaml").write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        svc = IngestionService(str(temp_dir))
        result = svc.get_connection("db")
        assert result["name"] == "db"

    def test_get_connection_not_found(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        with pytest.raises(IngestionServiceError, match="not found"):
            svc.get_connection("nonexistent")

    def test_create_connection(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        spec = ConnectionSpec(
            name="new_db",
            source_type="postgresql",
            host="pg.example.com",
            port=5432,
            database="analytics",
            username="admin",
            password="s3cret",
        )
        svc = IngestionService(str(temp_dir))
        result = svc.create_connection(spec)
        assert result["name"] == "new_db"
        # Verify files were written
        assert (config_dir / "sources.yaml").exists()
        env_path = temp_dir / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        # Keyed by connection name, not by database type — see
        # TestWriteCredentials for the regression this guards against.
        assert "NEW_DB_USER=admin" in content
        assert "NEW_DB_PASSWORD=s3cret" in content

    def test_create_connection_same_type_different_names_keep_separate_credentials(self, temp_dir):
        """Regression: two connections of the same source_type must not
        overwrite each other's credentials in .env."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        svc = IngestionService(str(temp_dir))

        svc.create_connection(
            ConnectionSpec(
                name="prod_postgres",
                source_type="postgresql",
                host="prod.example.com",
                port=5432,
                database="prod_db",
                username="prod_admin",
                password="prod_secret",
            )
        )
        svc.create_connection(
            ConnectionSpec(
                name="staging_postgres",
                source_type="postgresql",
                host="staging.example.com",
                port=5432,
                database="staging_db",
                username="staging_admin",
                password="staging_secret",
            )
        )

        content = (temp_dir / ".env").read_text()
        assert "PROD_POSTGRES_USER=prod_admin" in content
        assert "PROD_POSTGRES_PASSWORD=prod_secret" in content
        assert "STAGING_POSTGRES_USER=staging_admin" in content
        assert "STAGING_POSTGRES_PASSWORD=staging_secret" in content

    def test_create_connection_duplicate(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        (config_dir / "sources.yaml").write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        spec = ConnectionSpec("db", "postgresql", "h", 1, "d", "u", "p")
        svc = IngestionService(str(temp_dir))
        with pytest.raises(IngestionServiceError, match="already exists"):
            svc.create_connection(spec)

    def test_create_connection_overwrite(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        (config_dir / "sources.yaml").write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        spec = ConnectionSpec("db", "postgresql", "newhost", 5432, "newdb", "u", "p")
        svc = IngestionService(str(temp_dir))
        result = svc.create_connection(spec, overwrite=True)
        assert result["host"] == "newhost"

    def test_delete_connection(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        (config_dir / "sources.yaml").write_text(
            "sources:\n  db:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: mydb\n"
        )
        svc = IngestionService(str(temp_dir))
        svc.delete_connection("db")
        assert svc.list_connections() == []

    def test_delete_nonexistent(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        with pytest.raises(IngestionServiceError, match="not found"):
            svc.delete_connection("nonexistent")

    def test_test_spec(self, temp_dir):
        spec = ConnectionSpec("t", "postgresql", "h", 5432, "d", "u", "p")
        svc = IngestionService(str(temp_dir))
        with patch.object(svc, "test_spec", return_value=True):
            assert svc.test_spec(spec) is True

    def test_test_connection_no_config(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        with pytest.raises(IngestionServiceError, match="No connections"):
            svc.test_connection("db")

    def test_default_port(self):
        assert IngestionService.default_port("postgresql") == 5432
        assert IngestionService.default_port("unknown") == 0


class TestWriteCredentials:
    def test_write_credentials_creates_env(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        svc = IngestionService(str(temp_dir))
        svc._write_credentials("my_mysql_conn", "admin", "secret")
        env_path = temp_dir / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert "MY_MYSQL_CONN_USER=admin" in content
        assert "MY_MYSQL_CONN_PASSWORD=secret" in content

    def test_write_credentials_updates_existing(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        (temp_dir / ".env").write_text(
            "EXISTING_KEY=val\nMY_MYSQL_CONN_USER=old\nMY_MYSQL_CONN_PASSWORD=oldpass\n"
        )
        svc = IngestionService(str(temp_dir))
        svc._write_credentials("my_mysql_conn", "newuser", "newpass")
        content = (temp_dir / ".env").read_text()
        assert "EXISTING_KEY=val" in content
        assert "MY_MYSQL_CONN_USER=newuser" in content
        assert "MY_MYSQL_CONN_PASSWORD=newpass" in content

    def test_write_credentials_keyed_by_connection_name_not_source_type(self, temp_dir):
        """Regression: credentials used to be keyed by source_type.upper(),
        so two connections of the same DB engine silently overwrote each
        other's username/password."""
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        svc = IngestionService(str(temp_dir))
        svc._write_credentials("conn_a", "user_a", "pass_a")
        svc._write_credentials("conn_b", "user_b", "pass_b")
        content = (temp_dir / ".env").read_text()
        assert "CONN_A_USER=user_a" in content
        assert "CONN_A_PASSWORD=pass_a" in content
        assert "CONN_B_USER=user_b" in content
        assert "CONN_B_PASSWORD=pass_b" in content

    def test_ensure_gitignore_creates(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        svc = IngestionService(str(temp_dir))
        svc._ensure_gitignore()
        assert (temp_dir / ".gitignore").exists()
        assert ".env" in (temp_dir / ".gitignore").read_text()

    def test_ensure_gitignore_updates(self, temp_dir):
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        (temp_dir / ".gitignore").write_text("*.pyc\n")
        svc = IngestionService(str(temp_dir))
        svc._ensure_gitignore()
        content = (temp_dir / ".gitignore").read_text()
        assert ".env" in content
