"""Role-based access: each role reaches what it should, and nothing more.

Covers the gaps a review found: the deep preflight was open to read-only roles,
a Git URL could be passed as a source by any authenticated user, the viewer role
could not list projects, and model promotion/deletion shared the generic
`execution.write`. The last test guards every write route at once, so a new one
added without a permission fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from ducta.api.dependencies import GIT_SOURCE_PERMISSION, check_git_source, get_current_user
from ducta.api.main import create_app
from ducta.api.models.auth import ROLE_PERMISSIONS, User

GIT_URL = "https://github.com/example/project.git"


def _user(role: str) -> User:
    return User(id=role, username=role, email=f"{role}@example.com", roles=[role])


@pytest.fixture
def app():
    return create_app()


def _client(app, role: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    return TestClient(app)


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    from ducta.console.template import TemplateGenerator, TemplateType

    monkeypatch.chdir(tmp_path)  # the server's source confinement base
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(TemplateType.MEDALLION_BASIC, "proj")
    return root


# ── the role table ───────────────────────────────────────────────────────────


class TestRoles:
    def test_the_viewer_can_read_projects(self):
        assert "project.read" in ROLE_PERMISSIONS["viewer"]

    def test_the_viewer_cannot_run_or_bring_code(self):
        viewer = _user("viewer")
        for perm in ("pipeline.execute", GIT_SOURCE_PERMISSION, "model.promote", "model.delete"):
            assert not viewer.has_permission(perm), perm

    def test_a_developer_can_manage_models(self):
        developer = _user("developer")
        assert developer.has_permission("model.promote")
        assert developer.has_permission("model.delete")


# ── the preflight and projects ───────────────────────────────────────────────


class TestProjectRoutes:
    def test_a_viewer_lists_projects(self, app, project):
        r = _client(app, "viewer").get("/api/projects", params={"source": str(project)})
        assert r.status_code == 200

    def test_the_deep_preflight_needs_the_run_permission(self, app, project):
        url = "/api/projects/proj/pipelines/etl/preflight"
        r = _client(app, "viewer").post(url, params={"source": str(project)})
        assert r.status_code == 403
        assert "pipeline.execute" in r.text

    def test_a_developer_may_run_the_preflight(self, app, project):
        url = "/api/projects/proj/pipelines/etl/preflight"
        r = _client(app, "developer").post(url, params={"source": str(project)})
        assert r.status_code == 200, r.text


# ── Git sources ──────────────────────────────────────────────────────────────


class TestGitSources:
    def test_a_viewer_cannot_use_a_git_url_as_source(self, app):
        r = _client(app, "viewer").get("/api/projects", params={"source": GIT_URL})
        assert r.status_code == 403
        assert GIT_SOURCE_PERMISSION in r.text

    def test_the_header_form_is_checked_too(self, app):
        r = _client(app, "viewer").get("/api/projects", headers={"X-Source-Path": GIT_URL})
        assert r.status_code == 403

    def test_selecting_a_git_source_needs_the_permission(self, app):
        r = _client(app, "viewer").post("/api/workspace/select", json={"path_or_url": GIT_URL})
        assert r.status_code == 403

    def test_the_check_lets_a_developer_and_a_local_path_through(self):
        check_git_source(GIT_URL, _user("developer"))  # no exception
        check_git_source("/some/local/dir", _user("viewer"))  # not a Git URL

    def test_the_operator_default_workspace_is_not_checked(self, app, project, monkeypatch):
        # DUCTA_WORKSPACE is set by whoever started the server, not by the caller.
        monkeypatch.setenv("DUCTA_WORKSPACE", str(project))
        assert _client(app, "viewer").get("/api/projects").status_code == 200


# ── ingestion ────────────────────────────────────────────────────────────────


def test_testing_an_unsaved_connection_needs_the_write_permission(app, project):
    body = {
        "name": "x",
        "type": "postgresql",
        "host": "db.example.com",
        "port": 5432,
        "database": "d",
        "username": "u",
        "password": "p",
    }
    r = _client(app, "viewer").post(
        "/api/ingestion/connections/test", params={"source": str(project)}, json=body
    )
    assert r.status_code == 403
    assert "ingestion.write" in r.text


# ── models ───────────────────────────────────────────────────────────────────


class TestModelRoutes:
    @pytest.mark.parametrize(
        "method, url, body",
        [
            ("post", "/api/mlops/models/m/promote", {"version": 1, "stage": "production"}),
            ("delete", "/api/mlops/models/m/versions/1", None),
            ("post", "/api/mlops/gc", {"dry_run": True}),
        ],
    )
    def test_model_changes_are_denied_to_a_viewer(self, app, project, method, url, body):
        client = _client(app, "viewer")
        kwargs = {"params": {"source": str(project)}}
        if body is not None:
            kwargs["json"] = body
        r = getattr(client, method)(url, **kwargs)
        assert r.status_code == 403
        assert "model." in r.text


# ── every write route at once ────────────────────────────────────────────────

#: Routes reachable without a permission on purpose.
_OPEN = {"/api/auth/login", "/api/auth/logout", "/api/auth/refresh", "/api/certificates/verify"}

#: POST routes that only read, with why. Anything else that is not a GET must need
#: a permission the viewer lacks.
_READ_ONLY_POSTS = {
    "/api/nodes/{name}/code/ast": "ast.parse of the node's source; nothing is imported",
    "/api/configs/validate": "validate_project: schema and references, no imports",
    "/api/projects/{project_id}/validate": "validate_project on a scratch copy + ast of the "
    "node functions; nothing is written or imported",
    "/api/quality/validate-config": "checks the quality config with load_extensions=False",
    "/api/projects/{project_id}/certificates/{run_id}/verify": "recomputes a certificate's hash",
    "/api/ingestion/connections/{name}/test": "re-tests a saved connection an editor configured",
    "/api/projects/{project_id}/quality/failing-rows": "reads a dataset's rows, like the "
    "preview a viewer already has; writes nothing",
}


def _routes(app):
    """Flatten the app's routes, including routers FastAPI wraps when included."""

    def walk(routes, prefix=""):
        for r in routes:
            if type(r).__name__ == "_IncludedRouter":
                yield from walk(r.original_router.routes, prefix + (r.include_context.prefix or ""))
            elif isinstance(r, APIRoute):
                yield prefix + r.path, r

    return list(walk(app.routes))


def _deps(dependant, acc):
    for d in dependant.dependencies:
        acc.append(d.call)
        _deps(d, acc)
    return acc


def test_every_write_route_requires_a_permission_the_viewer_lacks(app):
    viewer = _user("viewer")
    unguarded = []
    for path, route in _routes(app):
        writes = set(route.methods or ()) - {"GET", "HEAD", "OPTIONS"}
        if not writes or path in _OPEN or path in _READ_ONLY_POSTS or not path.startswith("/api/"):
            continue
        checks = [
            c for c in _deps(route.dependant, []) if "_check" in getattr(c, "__qualname__", "")
        ]
        perms = {cell.cell_contents for c in checks for cell in (c.__closure__ or ())}
        if not perms or all(viewer.has_permission(p) for p in perms if isinstance(p, str)):
            unguarded.append(f"{','.join(sorted(writes))} {path} {sorted(map(str, perms))}")
    assert not unguarded, "write routes a viewer can reach:\n" + "\n".join(unguarded)


# ── what the UI is told ──────────────────────────────────────────────────────


class TestMe:
    def test_me_returns_the_roles_permissions(self, app):
        body = _client(app, "viewer").get("/api/auth/me").json()
        assert body["roles"] == ["viewer"]
        assert "project.read" in body["permissions"]
        assert "pipeline.execute" not in body["permissions"]

    def test_an_admin_gets_the_wildcard(self, app):
        assert _client(app, "admin").get("/api/auth/me").json()["permissions"] == ["*"]
