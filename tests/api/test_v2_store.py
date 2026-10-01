"""API storage for format-2 projects (phase 5).

The API keeps speaking the engine's shapes; the store translates to format 2,
edits files in round-trip mode (comments survive), validates the whole project
before committing, and restores the files when a write is rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

git = pytest.importorskip("git")
pytest.importorskip("ruamel.yaml")

from ducta.api.exceptions import ConcurrencyError, ValidationError  # noqa: E402
from ducta.api.repositories.config_repository import ConfigRepository  # noqa: E402
from ducta.api.repositories.dataset_repository import DatasetRepository  # noqa: E402
from ducta.api.repositories.node_repository import NodeRepository  # noqa: E402
from ducta.api.repositories.project_repository import ProjectRepository  # noqa: E402
from ducta.api.repositories.v2_store import V2ProjectStore  # noqa: E402
from ducta.setting import project_migrate as pm  # noqa: E402
from tests.format1 import format1_project  # noqa: E402


@pytest.fixture
def project(tmp_path) -> Path:
    root = format1_project(tmp_path / "proj")
    pm.replace_in_place(pm.migrate(root), root)
    etl = root / "pipelines" / "etl.yaml"
    etl.write_text(
        etl.read_text().replace("nodes:\n", "# the ETL graph — keep this comment\nnodes:\n", 1)
    )
    repo = git.Repo.init(root)
    repo.git.add(A=True)
    repo.index.commit("initial")
    return root


def _store(root: Path) -> V2ProjectStore:
    store = V2ProjectStore.detect(root)
    assert store is not None
    return store


def _etl(root: Path) -> dict:
    return yaml.safe_load((root / "pipelines" / "etl.yaml").read_text())


class TestReads:
    def test_engine_shaped_views(self, project):
        store = _store(project)
        assert set(store.nodes()) == {"extract", "transform", "load"}
        assert store.nodes()["load"]["module"] == "pipelines.etl"
        assert store.pipelines()["etl"]["nodes"] == ["extract", "transform", "load"]
        assert "source_data" in store.documents()["input"]

    def test_repositories_route_format_2_through_the_store(self, project):
        assert set(NodeRepository(project).list_all()) == {"extract", "transform", "load"}
        assert "etl" in ProjectRepository(project).get_pipelines(".")
        assert ConfigRepository(project).get("global_config", "dev")["input_path"] == "data"
        assert ConfigRepository(project).validate("dev")["valid"] is True
        assert "gold.etl.final_output" in DatasetRepository(project).list_outputs()


class TestNodeWrites:
    def test_update_keeps_comments_and_commits(self, project):
        store = _store(project)
        spec = dict(store.nodes()["load"], retry=2)
        sha = store.save_node("load", spec)

        assert sha
        assert _etl(project)["nodes"]["load"]["retry"] == 2
        assert (
            "# the ETL graph — keep this comment"
            in (project / "pipelines" / "etl.yaml").read_text()
        )

    def test_reading_a_node_and_writing_it_back_changes_nothing(self, project):
        store = _store(project)
        before = (project / "pipelines" / "etl.yaml").read_text()
        store.save_node("extract", store.nodes()["extract"])
        # the catalog contract compiled into the view is not duplicated on the node
        assert (project / "pipelines" / "etl.yaml").read_text() == before

    def test_a_new_node_needs_its_pipeline(self, project):
        store = _store(project)
        spec = {"module": "pipelines.etl", "function": "load", "input": [], "output": []}
        with pytest.raises(ValidationError, match="pass `pipeline`"):
            store.save_node("extra", spec)
        store.save_node("extra", spec, pipeline="etl")
        assert "extra" in _etl(project)["nodes"]

    def test_an_invalid_node_is_rejected_and_the_file_restored(self, project):
        store = _store(project)
        before = (project / "pipelines" / "etl.yaml").read_text()
        bad = dict(store.nodes()["load"], input=["no_such_dataset"])
        with pytest.raises(ValidationError) as exc:
            store.save_node("load", bad)
        assert any("no_such_dataset" in p for p in exc.value.detail["problems"])
        assert (project / "pipelines" / "etl.yaml").read_text() == before

    def test_stale_commit_sha_is_a_conflict(self, project):
        store = _store(project)
        store.save_node("load", dict(store.nodes()["load"], retry=1))
        with pytest.raises(ConcurrencyError):
            store.save_node("load", dict(store.nodes()["load"], retry=2), expected_sha="deadbeef")

    def test_delete(self, project):
        store = _store(project)
        store.save_node("extra", {"module": "m", "function": "f"}, pipeline="etl")
        store.delete_node("extra")
        assert "extra" not in _etl(project)["nodes"]


class TestPipelineWrites:
    def test_settings_and_order(self, project):
        store = _store(project)
        spec = dict(
            store.pipelines()["etl"], description="new", nodes=["load", "transform", "extract"]
        )
        store.save_pipeline("etl", spec)
        etl = _etl(project)
        assert etl["description"] == "new"
        assert list(etl["nodes"]) == ["load", "transform", "extract"]

    def test_removing_a_node_from_the_list_is_refused(self, project):
        store = _store(project)
        spec = dict(store.pipelines()["etl"], nodes=["extract", "transform"])
        with pytest.raises(ValidationError) as exc:
            store.save_pipeline("etl", spec)
        assert "would delete" in exc.value.detail["problems"][0]

    def test_a_new_pipeline_then_its_node(self, project):
        store = _store(project)
        store.save_pipeline("report", {"description": "later", "requires_dates": False})
        store.save_node(
            "summary",
            {"module": "pipelines.etl", "function": "load", "input": ["gold.etl.final_output"]},
            pipeline="report",
        )
        assert store.pipelines()["report"]["nodes"] == ["summary"]
        with pytest.raises(ValidationError) as exc:
            store.save_pipeline("report", {"nodes": ["summary", "load"]})
        assert any("belongs to one pipeline" in p for p in exc.value.detail["problems"])

    def test_deleting_a_pipeline_others_depend_on_is_rejected_and_restored(self, project):
        store = _store(project)
        store.save_pipeline("report", {"depends_on": ["etl"], "requires_dates": False})
        with pytest.raises(ValidationError):
            store.delete_pipeline("etl")
        assert (project / "pipelines" / "etl.yaml").exists()


class TestDocumentWrites:
    def test_base_settings(self, project):
        store = _store(project)
        g = dict(store.documents()["global_config"], max_parallel_nodes=9)
        store.save_document("global_config", g, "base")
        assert (
            yaml.safe_load((project / "ducta.yaml").read_text())["settings"]["max_parallel_nodes"]
            == 9
        )

    def test_an_environment_edit_becomes_a_minimal_override(self, project):
        store = _store(project)
        g = dict(store.documents("prod")["global_config"], max_parallel_nodes=12)
        store.save_document("global_config", g, "prod")
        envs = yaml.safe_load((project / "ducta.yaml").read_text())["environments"]
        assert envs == {"prod": {"settings": {"max_parallel_nodes": 12}}}
        assert store.documents("prod")["global_config"]["max_parallel_nodes"] == 12
        assert store.documents("dev")["global_config"]["max_parallel_nodes"] == 4

    def test_catalog_edit(self, project):
        store = _store(project)
        inputs = store.documents()["input"]
        inputs["source_data"] = dict(inputs["source_data"], filepath="data/other.csv")
        store.save_document("input", inputs, "base")
        catalog = yaml.safe_load((project / "catalog.yaml").read_text())
        assert catalog["source_data"]["path"] == "data/other.csv"


def test_api_executions_load_format_2(project):
    from ducta.api.workspace.manager import WorkspaceManager

    ctx = WorkspaceManager(project).load_context("dev")
    assert set(ctx.nodes_config) == {"extract", "transform", "load"}
    assert ctx.project_format == 2


def test_the_config_route_writes_through_the_store(project, monkeypatch):
    """PUT /api/configs/{env}/{name} reaches the store (it once passed a keyword
    ``save_config`` does not take, so every config save answered 500)."""
    from fastapi.testclient import TestClient

    from ducta.api.config import get_settings
    from ducta.api.main import create_app

    monkeypatch.setenv("DUCTA_WORKSPACE", str(project))
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        current = client.get("/api/configs/base/global_config").json()
        content = dict(current["content"], max_parallel_nodes=7)
        resp = client.put(
            "/api/configs/base/global_config",
            json={"content": content, "expected_commit_sha": current.get("commit_sha")},
        )
    get_settings.cache_clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["commit_sha"]
    settings = yaml.safe_load((project / "ducta.yaml").read_text())["settings"]
    assert settings["max_parallel_nodes"] == 7
