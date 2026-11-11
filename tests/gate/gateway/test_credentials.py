"""A connection's credentials: the environment, then the project's ``.env``."""

import pytest

from ducta.gate.gateway.credentials import read_dotenv, resolve_credentials


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("CRM_USER", "CRM_PASSWORD", "POSTGRESQL_USER", "POSTGRESQL_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


class TestReadDotenv:
    def test_export_prefix_quotes_and_comments(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# a comment\n"
            "export CRM_USER=alice\n"
            'CRM_PASSWORD="p@ss word"\n'
            "OTHER='x'\n"
            "not a setting\n"
        )
        assert read_dotenv(env) == {"CRM_USER": "alice", "CRM_PASSWORD": "p@ss word", "OTHER": "x"}

    def test_a_missing_file_is_empty(self, tmp_path):
        assert read_dotenv(tmp_path / ".env") == {}


class TestResolveCredentials:
    def test_the_environment_pair_beats_the_env_file(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("CRM_USER=alice\nCRM_PASSWORD=from-file\n")
        monkeypatch.setenv("CRM_USER", "bob")
        monkeypatch.setenv("CRM_PASSWORD", "from-env")
        creds = resolve_credentials("crm", tmp_path)
        assert (creds.username, creds.password, creds.prefix) == ("bob", "from-env", "CRM")
        assert creds.where == "environment"

    def test_half_in_the_environment_and_half_in_the_file_is_an_error(self, tmp_path, monkeypatch):
        """One by one, the project's .env supplied the user and the server's environment the
        password; neither side is taken silently (the file's would ignore a rotated password)."""
        (tmp_path / ".env").write_text("CRM_USER=alice\nCRM_PASSWORD=from-file\n")
        monkeypatch.setenv("CRM_PASSWORD", "from-env")
        with pytest.raises(ValueError, match="CRM_PASSWORD is set in the environment") as caught:
            resolve_credentials("crm", tmp_path)
        assert "from-env" not in str(caught.value) and "from-file" not in str(caught.value)

    @pytest.mark.parametrize("name", ["ducta_admin", "DUCTA_SMTP"])
    def test_a_name_on_the_servers_own_secrets_gets_nothing(self, tmp_path, monkeypatch, name):
        """A connection named ducta_admin sent DUCTA_ADMIN_PASSWORD to a host of its choosing."""
        prefix = name.upper()
        monkeypatch.setenv(f"{prefix}_USER", "admin")
        monkeypatch.setenv(f"{prefix}_PASSWORD", "real-admin-password")
        creds = resolve_credentials(name, tmp_path)
        assert (creds.username, creds.password) == (None, None)

    def test_the_env_file_alone(self, tmp_path):
        (tmp_path / ".env").write_text("CRM_USER=alice\nCRM_PASSWORD=pw\n")
        creds = resolve_credentials("crm", tmp_path)
        assert (creds.username, creds.password, creds.where) == ("alice", "pw", ".env")

    def test_a_type_wide_pair_is_not_a_source_credential(self, tmp_path, monkeypatch):
        monkeypatch.setenv("POSTGRESQL_USER", "someone")
        monkeypatch.setenv("POSTGRESQL_PASSWORD", "pw")
        creds = resolve_credentials("crm", tmp_path)
        assert (creds.username, creds.password) == (None, None)

    def test_nothing_set(self, tmp_path):
        creds = resolve_credentials("crm", tmp_path)
        assert (creds.username, creds.password, creds.where) == (None, None, None)

    def test_the_values_stay_out_of_repr(self, tmp_path):
        (tmp_path / ".env").write_text("CRM_USER=alice\nCRM_PASSWORD=hunter2\n")
        assert "hunter2" not in repr(resolve_credentials("crm", tmp_path))


class TestProjectRootFor:
    """Where the engine reads ``.env`` must be where ``ducta init ingestion setup`` wrote it."""

    @staticmethod
    def _project(path):
        path.mkdir(parents=True, exist_ok=True)
        (path / "ducta.yaml").write_text("version: 2\n")
        return path

    def test_the_project_holding_the_sources_file(self, tmp_path, monkeypatch):
        from ducta.gate.gateway.credentials import project_root_for

        project = self._project(tmp_path / "proj")
        (project / "config").mkdir()
        monkeypatch.chdir(tmp_path)
        assert project_root_for(project / "config") == project.resolve()

    def test_a_sources_file_outside_any_project_uses_the_current_one(self, tmp_path, monkeypatch):
        from ducta.gate.gateway.credentials import project_root_for

        project = self._project(tmp_path / "proj")
        shared = tmp_path / "shared" / "conf"
        shared.mkdir(parents=True)
        monkeypatch.chdir(project)
        assert project_root_for(shared) == project.resolve()

    def test_no_project_at_all_is_the_working_directory(self, tmp_path, monkeypatch):
        from ducta.gate.gateway.credentials import project_root_for

        shared = tmp_path / "shared"
        shared.mkdir()
        monkeypatch.chdir(tmp_path)
        assert project_root_for(shared).resolve() == tmp_path.resolve()


class TestWrittenCredentialsRoundTrip:
    @pytest.mark.parametrize("password", ['"p@ss"', " secret ", "it's", "a=b#c", "plain"])
    def test_a_password_comes_back_exactly(self, tmp_path, password):
        from ducta.setting.connections import IngestionService

        service = IngestionService(tmp_path)
        service._write_credentials("crm", "alice", password)
        values = read_dotenv(service.env_path)
        assert (values["CRM_USER"], values["CRM_PASSWORD"]) == ("alice", password)
