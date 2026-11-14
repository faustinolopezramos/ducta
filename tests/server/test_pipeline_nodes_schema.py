"""`GET /projects/{id}/pipelines/{name}/nodes/schema` — every node's schema at once.

The pipeline workspace (canvas, contract list, focus panel) needs quality and
last-run data for all of a pipeline's nodes together; the per-node endpoint made
that one request per card. The quality summary also only ever described one
block (``data_quality`` *or* ``sanity_checks``) and ignored a gate declared
without ``enabled`` — which is exactly how the demo project writes
``quality_gate: {max_errors: 0}``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ducta.project_store.errors import NodeNotFoundError, PipelineNotFoundError
from ducta_server.services.node_schema_service import NodeSchemaService

PIPELINES = {
    "silver.clean": {"nodes": ["silver.clean_student", "silver.clean_education"]},
}

NODE_SPECS = {
    "silver.clean_student": {
        "module": "src.silver",
        "function": "clean_student",
        "input": ["bronze.education.student"],
        "output": ["silver.education.student_cleaned"],
        "sanity_checks": {"enabled": True, "checks": {"empty_dataset": {}}},
        "data_quality": {
            "enabled": True,
            "checks": {
                "row_count": {"min": 350},
                "range": {"column": "G3", "min": 0, "max": 20},
                "null_rate": {"columns": ["G3"], "threshold": 0.0, "enabled": False},
            },
            "quality_gate": {"max_errors": 0},
        },
    },
    "silver.clean_education": {
        "module": "src.silver",
        "function": "clean_education",
        "input": ["bronze.education.education_costs"],
        "output": ["silver.education.education_cost_cleaned"],
    },
}


class _Projects:
    def list_project_pipelines(self, project_id):
        return PIPELINES


class _Nodes:
    def __init__(self, root):
        self.root = root

    def get_node(self, name):
        if name not in NODE_SPECS:
            raise NodeNotFoundError(f"Node '{name}' not found")
        return NODE_SPECS[name], "sha"

    def get_node_python_file_by_module(self, module):
        raise NodeNotFoundError(f"Module '{module}' not found")


class _Datasets:
    def resolve_refs(self, names, side):
        return [
            SimpleNamespace(
                name=name,
                declared=True,
                format="parquet",
                path="${output_path}/${environment}/" + name.replace(".", "/"),
                write_mode="overwrite" if side == "output" else None,
                schema_=None,
                layer=name.split(".")[0] if name.split(".")[0] in ("bronze", "silver") else None,
            )
            for name in names
        ]


class _Executions:
    def __init__(self, runs=()):
        self.runs = list(runs)

    def list_executions_paginated(self, skip=0, limit=50, node_name=None, pipeline_name=None, **_):
        matches = [
            r
            for r in self.runs
            if (node_name is None or r.node_name == node_name)
            and (pipeline_name is None or r.pipeline_name == pipeline_name)
        ]
        return matches[skip : skip + limit], len(matches)


FAILED_RUN = SimpleNamespace(
    id="exec-1",
    pipeline_name="silver.clean",
    node_name=None,
    status=SimpleNamespace(value="failed"),
    started_at=datetime(2026, 9, 15, 14, 48, tzinfo=timezone.utc),
    duration_seconds=10.5,
    error_message="Phase 1: load into Pandas",
)


@pytest.fixture
def service(tmp_path):
    return NodeSchemaService(_Projects(), _Nodes(tmp_path), _Executions([FAILED_RUN]), _Datasets())


class TestBuildAll:
    def test_returns_every_node_in_declared_order_with_io_resolved(self, service):
        result = service.build_all("batch", "silver.clean")

        assert [n.node_id for n in result.nodes] == [
            "silver.clean_student",
            "silver.clean_education",
        ]
        student = result.nodes[0]
        assert student.fn == "clean_student"
        assert [i.name for i in student.inputs] == ["bronze.education.student"]
        assert student.outputs[0].path.endswith("silver/education/student_cleaned")
        assert student.outputs[0].write_mode == "overwrite"

    def test_checks_cover_both_blocks_and_skip_disabled_ones(self, service):
        quality = service.build_all("batch", "silver.clean").nodes[0].quality

        assert [(c.name, c.phase) for c in quality.checks] == [
            ("empty_dataset", "sanity"),
            ("row_count", "quality"),
            ("range", "quality"),
        ]
        assert quality.checks[1].params == {"min": 350}

    def test_a_gate_without_enabled_is_still_reported(self, service):
        quality = service.build_all("batch", "silver.clean").nodes[0].quality

        assert len(quality.gates) == 1
        gate = quality.gates[0]
        assert (gate.phase, gate.behavior, gate.params) == ("quality", None, {"max_errors": 0})

    def test_the_legacy_summary_fields_keep_their_meaning(self, service):
        quality = service.build_all("batch", "silver.clean").nodes[0].quality

        # Still the data_quality block alone, as NodeCard has always read it.
        assert quality.check_count == 2
        assert quality.is_sanity is False
        assert quality.gate_behavior is None

    def test_a_node_with_no_checks_has_no_quality(self, service):
        assert service.build_all("batch", "silver.clean").nodes[1].quality is None

    def test_reports_the_pipelines_latest_run(self, service):
        last = service.build_all("batch", "silver.clean").last_execution

        assert last is not None
        assert (last.execution_id, last.status, last.duration) == ("exec-1", "failed", 10.5)
        assert last.error_message == "Phase 1: load into Pandas"

    def test_no_runs_means_no_last_execution(self, tmp_path):
        svc = NodeSchemaService(_Projects(), _Nodes(tmp_path), _Executions(), _Datasets())
        assert svc.build_all("batch", "silver.clean").last_execution is None

    def test_unknown_pipeline_raises(self, service):
        with pytest.raises(PipelineNotFoundError):
            service.build_all("batch", "nope")


class TestRoute:
    PATH = "/projects/{project_id}/pipelines/{pipeline_name}/nodes/schema"

    def _route(self):
        from ducta_server.routes.projects import router

        return next(r for r in router.routes if getattr(r, "path", None) == self.PATH)

    def test_requires_node_read(self):
        perms = [
            cell.cell_contents
            for dep in self._route().dependencies
            for cell in (dep.dependency.__closure__ or ())
        ]
        assert "node.read" in perms

    def test_serves_all_nodes_without_being_shadowed_by_the_per_node_route(self, tmp_path):
        from ducta_server.dependencies import (
            get_current_user,
            get_execution_manager,
            get_node_service,
        )
        from ducta_server.models.auth import User
        from ducta_server.routes import projects

        app = FastAPI()
        app.include_router(projects.router, prefix="/api")
        app.dependency_overrides[projects._project_svc] = _Projects
        app.dependency_overrides[get_node_service] = lambda: _Nodes(tmp_path)
        app.dependency_overrides[get_execution_manager] = lambda: _Executions([FAILED_RUN])
        app.dependency_overrides[projects._dataset_svc] = _Datasets
        app.dependency_overrides[get_current_user] = lambda: User(
            id="t", username="t", email="t@example.com", roles=["admin"]
        )

        response = TestClient(app).get("/api/projects/batch/pipelines/silver.clean/nodes/schema")

        assert response.status_code == 200
        body = response.json()
        assert body["pipeline_name"] == "silver.clean"
        assert len(body["nodes"]) == 2
        assert body["last_execution"]["status"] == "failed"


class TestFormat2Quality:
    """Format 2 compiles blocks without `enabled`, and input contracts per dataset."""

    def test_a_block_without_enabled_is_on(self):
        q = NodeSchemaService._quality(
            {
                "data_quality": {
                    "checks": {"row_count": {"min": 1}},
                    "quality_gate": {"max_errors": 0},
                }
            }
        )
        assert q is not None and [c.name for c in q.checks] == ["row_count"]

    def test_enabled_false_still_turns_it_off(self):
        assert (
            NodeSchemaService._quality({"data_quality": {"enabled": False, "checks": {"x": {}}}})
            is None
        )

    def test_input_contracts_are_listed_as_sanity_checks(self):
        q = NodeSchemaService._quality(
            {"sanity_checks": {"inputs": {"bronze.a": {"checks": {"empty_dataset": {}}}}}}
        )
        assert q is not None and q.is_sanity and [c.name for c in q.checks] == ["empty_dataset"]


class TestNodeDurationIsTheNodes:
    """A node's last run reported the run's wall time (start-up and shutdown
    included) as the node's: 7.2 s on the card for a node that took 4.8 s."""

    def _service(self, tmp_path, run):
        class Projects(_Projects):
            def project_dir(self, project_id):
                return tmp_path

        return NodeSchemaService(Projects(), _Nodes(tmp_path), _Executions([run]), _Datasets())

    def _run(self, **kw):
        return SimpleNamespace(
            id="exec-2",
            pipeline_name="silver.clean",
            node_name="silver.clean_education",
            status=SimpleNamespace(value="success"),
            started_at=datetime(2026, 10, 20, 21, 27, tzinfo=timezone.utc),
            duration_seconds=7.197,
            error_message=None,
            env="dev",
            **kw,
        )

    def test_reads_the_nodes_own_time_from_the_runs_certificate(self, tmp_path, monkeypatch):
        import ducta.runs.certificates as rc

        monkeypatch.setattr(
            rc,
            "load_run_certificate",
            lambda project_dir, run_id, env=None: {
                "nodes": [{"name": "silver.clean_education", "duration_seconds": 4.8}]
            },
        )
        node = (
            self._service(tmp_path, self._run(certificate_run_id="cert-1"))
            .build_all("batch", "silver.clean")
            .nodes[1]
        )
        assert node.last_execution_duration == 4.8

    def test_falls_back_to_the_runs_time_without_a_certificate(self, tmp_path):
        node = (
            self._service(tmp_path, self._run(certificate_run_id=None))
            .build_all("batch", "silver.clean")
            .nodes[1]
        )
        assert node.last_execution_duration == 7.197


class TestLastRunIncludesPipelineRuns:
    """Only runs of a node alone used to count as its last run, so the list and
    the panel said "never run" for a node the pipeline ran yesterday while the
    canvas showed that run's state."""

    def _service(self, tmp_path, monkeypatch, runs, certs):
        import ducta.runs.certificates as rc

        monkeypatch.setattr(
            rc, "load_run_certificate", lambda project_dir, run_id, env=None: certs.get(run_id)
        )

        class Projects(_Projects):
            def project_dir(self, project_id):
                return tmp_path

        return NodeSchemaService(Projects(), _Nodes(tmp_path), _Executions(runs), _Datasets())

    def _run(self, id, day, cert=None, node_name=None, node_names=None, status="success"):
        return SimpleNamespace(
            id=id,
            pipeline_name="silver.clean",
            node_name=node_name,
            node_names=node_names,
            status=SimpleNamespace(value=status),
            started_at=datetime(2026, 10, day, tzinfo=timezone.utc),
            duration_seconds=9.0,
            error_message=None,
            env="dev",
            certificate_run_id=cert,
        )

    def _nodes(self, svc):
        return {n.node_id: n for n in svc.build_all("batch", "silver.clean").nodes}

    def test_a_whole_pipeline_run_is_each_nodes_last_run_with_its_own_status(
        self, tmp_path, monkeypatch
    ):
        certs = {
            "c1": {
                "nodes": [
                    {"name": "silver.clean_student", "status": "success", "duration_seconds": 2.0},
                    {
                        "name": "silver.clean_education",
                        "status": "failed",
                        "duration_seconds": 1.5,
                        "error": "boom",
                    },
                ]
            }
        }
        nodes = self._nodes(
            self._service(
                tmp_path, monkeypatch, [self._run("r1", 20, cert="c1", status="failed")], certs
            )
        )

        assert (
            nodes["silver.clean_student"].last_execution_status,
            nodes["silver.clean_student"].last_execution_duration,
        ) == ("success", 2.0)
        assert nodes["silver.clean_education"].last_execution_status == "failed"
        assert nodes["silver.clean_education"].last_execution_error_message == "boom"

    def test_a_run_that_stopped_before_the_node_is_not_its_last_run(self, tmp_path, monkeypatch):
        certs = {
            "new": {
                "nodes": [
                    {"name": "silver.clean_student", "status": "failed", "duration_seconds": 1.0}
                ]
            },
            "old": {
                "nodes": [
                    {"name": "silver.clean_education", "status": "success", "duration_seconds": 4.8}
                ]
            },
        }
        runs = [self._run("r2", 21, cert="new", status="failed"), self._run("r1", 20, cert="old")]
        node = self._nodes(self._service(tmp_path, monkeypatch, runs, certs))[
            "silver.clean_education"
        ]

        assert (node.last_execution_status, node.last_execution_duration) == ("success", 4.8)
        assert node.last_execution_time.startswith("2026-10-20")

    def test_a_run_of_some_nodes_counts_only_for_those(self, tmp_path, monkeypatch):
        runs = [self._run("r1", 20, node_names=["silver.clean_student"])]
        nodes = self._nodes(self._service(tmp_path, monkeypatch, runs, {}))

        assert nodes["silver.clean_student"].last_execution_status == "success"
        assert nodes["silver.clean_education"].last_execution_status is None

    def test_a_cli_run_counts_through_the_environments_certificates(self, tmp_path, monkeypatch):
        import ducta.runs.certificates as rc

        cli_cert = {
            "pipeline": "silver.clean",
            "status": "success",
            "started_at": "2026-10-22T10:00:00+00:00",
            "nodes": [
                {"name": "silver.clean_education", "status": "success", "duration_seconds": 4.9}
            ],
        }
        other = {"pipeline": "golden.x", "started_at": "2026-10-23T10:00:00+00:00", "nodes": []}
        monkeypatch.setattr(
            rc, "certificates", lambda project_dir, env: iter([("dev", cli_cert), ("dev", other)])
        )
        svc = self._service(
            tmp_path,
            monkeypatch,
            [self._run("r1", 20, node_names=["silver.clean_education"], status="failed")],
            {},
        )

        node = {n.node_id: n for n in svc.build_all("batch", "silver.clean", "dev").nodes}[
            "silver.clean_education"
        ]

        # The CLI run (22nd) is newer than the server's (20th).
        assert (node.last_execution_status, node.last_execution_duration) == ("success", 4.9)
        # Without an env only the server's runs are known, as before.
        assert self._nodes(svc)["silver.clean_education"].last_execution_status == "failed"


class TestResolvedPaths:
    """The panel showed `${output_path}/${environment}/silver/…`, the template."""

    def test_fills_in_the_environment_and_output_path(self, tmp_path, monkeypatch):
        import ducta_server.workspace.manager as wm

        class Projects(_Projects):
            def project_dir(self, project_id):
                return tmp_path

        class Manager:
            def __init__(self, root):
                pass

            def load_context(self, env):
                return SimpleNamespace(global_config={"output_path": str(tmp_path / "data")})

        monkeypatch.setattr(wm, "WorkspaceManager", Manager)
        svc = NodeSchemaService(Projects(), _Nodes(tmp_path), _Executions(), _Datasets())
        student = svc.build_all("batch", "silver.clean", "dev").nodes[0]

        assert student.outputs[0].path.startswith("${output_path}/${environment}/")
        assert student.outputs[0].resolved_path == "data/dev/silver/education/student_cleaned"

    def test_without_an_env_the_template_stays(self, service):
        assert service.build_all("batch", "silver.clean").nodes[0].outputs[0].resolved_path is None
