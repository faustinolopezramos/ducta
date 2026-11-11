import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.setting.connections import (
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
        assert "NEW_DB_USER='admin'" in content
        assert "NEW_DB_PASSWORD='s3cret'" in content

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
        assert "PROD_POSTGRES_USER='prod_admin'" in content
        assert "PROD_POSTGRES_PASSWORD='prod_secret'" in content
        assert "STAGING_POSTGRES_USER='staging_admin'" in content
        assert "STAGING_POSTGRES_PASSWORD='staging_secret'" in content

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

    @pytest.mark.parametrize("name", ["ducta_admin", "ducta_smtp"])
    def test_a_name_on_the_servers_own_secrets_is_refused(self, temp_dir, name):
        """Its credentials would be DUCTA_ADMIN_PASSWORD — the server's admin login."""
        (temp_dir / "config").mkdir()
        spec = ConnectionSpec(name, "postgresql", "attacker.example", 5432, "d", "u", "p")
        with pytest.raises(IngestionServiceError, match="the Ducta server's own"):
            IngestionService(str(temp_dir)).create_connection(spec)
        assert not (temp_dir / ".env").exists()

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
        assert "MY_MYSQL_CONN_USER='admin'" in content
        assert "MY_MYSQL_CONN_PASSWORD='secret'" in content

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
        assert "MY_MYSQL_CONN_USER='newuser'" in content
        assert "MY_MYSQL_CONN_PASSWORD='newpass'" in content

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
        assert "CONN_A_USER='user_a'" in content
        assert "CONN_A_PASSWORD='pass_a'" in content
        assert "CONN_B_USER='user_b'" in content
        assert "CONN_B_PASSWORD='pass_b'" in content

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


class TestCredentialsCannotInjectEnvironmentLines:
    """The `.env` is written one ``KEY=value`` per line and read back as settings by the
    gateway and by the API server. A line break in a credential used to start a new line:
    ``JAVA_TOOL_OPTIONS=…`` and ``AUTH_ENABLED=false`` ended up in the file."""

    EVIL = "pw\nJAVA_TOOL_OPTIONS=-javaagent:/tmp/agent.jar\nAUTH_ENABLED=false"

    @pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b", "a\x1bb", "a\x7fb"])
    @pytest.mark.parametrize("field", ["username", "password"])
    def test_a_control_character_is_refused_at_validation(self, field, bad):
        values = {"username": "user", "password": "secret", field: bad}
        spec = ConnectionSpec("c", "postgresql", "h", 5432, "d", **values)
        with pytest.raises(IngestionServiceError, match=f"'{field}' cannot contain"):
            spec.validate()

    def test_creating_the_connection_writes_nothing_when_the_password_is_hostile(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        spec = ConnectionSpec("crm", "postgresql", "h", 5432, "d", "user", self.EVIL)
        with pytest.raises(IngestionServiceError):
            svc.create_connection(spec)
        assert not (temp_dir / ".env").exists()
        assert svc.list_connections() == []

    def test_the_writer_refuses_it_too_when_called_directly(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        with pytest.raises(IngestionServiceError, match="cannot contain"):
            svc._write_credentials("crm", "user", self.EVIL)
        assert not (temp_dir / ".env").exists()

    def test_ordinary_symbols_in_a_password_are_kept_whole(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        password = 'p@ss=w0rd #1 "quoted" $HOME `x`'
        svc._write_credentials("crm", "user", password)
        assert (temp_dir / ".env").read_text().splitlines() == [
            "CRM_USER='user'",
            f"CRM_PASSWORD='{password}'",
        ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
class TestEnvFileIsPrivate:
    def test_a_new_env_is_readable_by_its_owner_only(self, temp_dir):
        IngestionService(str(temp_dir))._write_credentials("crm", "user", "secret")
        assert stat.S_IMODE((temp_dir / ".env").stat().st_mode) == 0o600

    def test_an_existing_open_env_is_tightened_when_credentials_are_written(self, temp_dir):
        env = temp_dir / ".env"
        env.write_text("OTHER=1\n")
        env.chmod(0o644)
        IngestionService(str(temp_dir))._write_credentials("crm", "user", "secret")
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
        assert "OTHER=1" in env.read_text()


class TestSpecRefusesUrlInjection:
    """The connection form (API and CLI) is where a user types host and database."""

    @pytest.mark.parametrize(
        "host, database",
        [
            ("db.corp", "shop?allowLoadLocalInfile=true&autoDeserialize=true"),
            ("evil.example:3306/x?autoDeserialize=true#", "shop"),
            ("h", "d;trustServerCertificate=true;encrypt=false"),
        ],
    )
    def test_host_and_database_must_be_plain_names(self, host, database):
        spec = ConnectionSpec("c", "mysql", host, 3306, database, "u", "p")
        with pytest.raises(IngestionServiceError, match="Invalid (host|database)"):
            spec.validate()

    def test_nothing_is_saved_for_a_refused_spec(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        spec = ConnectionSpec("c", "mysql", "h", 3306, "shop?autoDeserialize=true", "u", "p")
        with pytest.raises(IngestionServiceError):
            svc.create_connection(spec)
        assert svc.list_connections() == []
        assert not (temp_dir / ".env").exists()

    def test_an_unsaved_connection_is_not_tested_with_a_hostile_target(self, temp_dir):
        spec = ConnectionSpec(
            "c", "mysql", "evil:3306/x?autoDeserialize=true#", 3306, "d", "u", "p"
        )
        with patch("ducta.setting.connections.JDBCConnector") as connector:
            with pytest.raises(IngestionServiceError):
                IngestionService(str(temp_dir)).test_spec(spec)
        connector.assert_not_called()

    def test_ordinary_values_validate(self):
        ConnectionSpec(
            "c", "sqlserver", "server\\SQLEXPRESS", 1433, "Sales_DB", "u", "p"
        ).validate()


class TestGitignoreCoversTheEnvFile:
    def test_env_is_added_to_an_existing_gitignore(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        (temp_dir / ".gitignore").write_text("*.pyc")
        svc._ensure_gitignore()
        lines = (temp_dir / ".gitignore").read_text().split()
        assert {"*.pyc", ".env"} <= set(lines)

    def test_nothing_is_added_twice(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        svc._ensure_gitignore()
        first = (temp_dir / ".gitignore").read_text()
        svc._ensure_gitignore()
        assert (temp_dir / ".gitignore").read_text() == first


class TestConnectionsHardening:
    def _spec(self, name):
        return ConnectionSpec(name, "postgresql", "localhost", 5432, "db", "user", "pw")

    def test_names_differing_only_in_case_are_refused(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        svc.create_connection(self._spec("Prod"))
        with pytest.raises(IngestionServiceError, match="clashes with 'Prod'"):
            svc.create_connection(self._spec("prod"))
        # the first connection kept its own login
        assert "PROD_USER='user'" in (temp_dir / ".env").read_text()

    def test_overwriting_replaces_exported_and_indented_entries(self, temp_dir):
        (temp_dir / ".env").write_text("export DB_USER=old\n  DB_PASSWORD=old\nOTHER=1\n")
        IngestionService(str(temp_dir)).create_connection(self._spec("db"))
        lines = (temp_dir / ".env").read_text().splitlines()
        assert [ln for ln in lines if "DB_" in ln] == ["DB_USER='user'", "DB_PASSWORD='pw'"]
        assert "OTHER=1" in lines

    @pytest.mark.parametrize("path", ["../outside.yaml", "/tmp/elsewhere/sources.yaml"])
    def test_sources_path_cannot_leave_the_project(self, temp_dir, path):
        (temp_dir / "ducta.yaml").write_text(
            f"version: 2\nproject: p\nsettings:\n  ingestion: {{sources_path: {path}}}\n"
        )
        svc = IngestionService(str(temp_dir))
        with pytest.raises(IngestionServiceError, match="outside the project"):
            svc.list_connections()
        with pytest.raises(IngestionServiceError, match="outside the project"):
            svc.create_connection(self._spec("db"))

    def test_an_empty_sources_key_is_an_empty_list(self, temp_dir):
        (temp_dir / "config").mkdir()
        (temp_dir / "config" / "sources.yaml").write_text("sources:\n")
        svc = IngestionService(str(temp_dir))
        assert svc.list_connections() == []
        svc.create_connection(self._spec("db"))
        assert [c["name"] for c in svc.list_connections()] == ["db"]


class TestEnvFileHandling:
    def _spec(self, name):
        return ConnectionSpec(name, "postgresql", "localhost", 5432, "db", "user", "pw")

    def test_the_env_is_replaced_whole_with_owner_only_mode_and_no_temp_left(self, temp_dir):
        env = temp_dir / ".env"
        env.write_text("OTHER=1\n")
        os.chmod(env, 0o644)
        IngestionService(str(temp_dir)).create_connection(self._spec("db"))
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
        assert "OTHER=1" in env.read_text()
        assert [p.name for p in temp_dir.iterdir() if p.name.endswith(".tmp")] == []

    def test_a_failed_write_keeps_the_old_env_and_leaves_no_temp(self, temp_dir):
        env = temp_dir / ".env"
        env.write_text("OTHER=1\n")
        svc = IngestionService(str(temp_dir))
        with patch("ducta.setting.connections.os.replace", side_effect=OSError("disk")):
            with pytest.raises(OSError):
                svc.create_connection(self._spec("db"))
        assert env.read_text() == "OTHER=1\n"
        assert [p.name for p in temp_dir.iterdir() if p.name.endswith(".tmp")] == []

    def test_deleting_a_connection_removes_its_login_and_only_its_login(self, temp_dir):
        svc = IngestionService(str(temp_dir))
        svc.create_connection(self._spec("db"))
        svc.create_connection(self._spec("other"))
        svc.delete_connection("db")
        text = (temp_dir / ".env").read_text()
        assert "DB_USER" not in text and "DB_PASSWORD" not in text
        assert "OTHER_USER='user'" in text
