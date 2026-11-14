"""Where a project's run certificates are searched — one rule for the CLI and the web UI.

``ducta certify`` resolved a relative ``run_certificate_dir`` against the project
root, the API server against the directory it runs the project from, which is
``<project>/<env>`` when the relative paths only exist there. Each missed the
other's runs; ``ducta.core.certificate.candidate_runs_dirs`` searches both.
"""

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from ducta.core.certificate import candidate_runs_dirs

RUNS = Path("data") / "dev" / ".ducta" / "runs"


class TestCandidateRunsDirs:
    def test_a_relative_dir_is_found_under_the_project_root(self, tmp_path):
        (tmp_path / RUNS).mkdir(parents=True)

        assert candidate_runs_dirs(tmp_path, ["dev"], lambda env: RUNS) == [
            ("dev", tmp_path / RUNS)
        ]

    def test_a_relative_dir_is_found_under_the_environment_folder(self, tmp_path):
        (tmp_path / "dev" / RUNS).mkdir(parents=True)

        assert candidate_runs_dirs(tmp_path, ["dev"], lambda env: RUNS) == [
            ("dev", tmp_path / "dev" / RUNS)
        ]

    def test_both_bases_are_searched_root_first(self, tmp_path):
        (tmp_path / RUNS).mkdir(parents=True)
        (tmp_path / "dev" / RUNS).mkdir(parents=True)

        found = candidate_runs_dirs(tmp_path, ["dev"], lambda env: RUNS)

        assert found == [("dev", tmp_path / RUNS), ("dev", tmp_path / "dev" / RUNS)]

    def test_an_absolute_dir_is_used_as_is(self, tmp_path):
        absolute = tmp_path / "elsewhere"
        absolute.mkdir()

        assert candidate_runs_dirs(tmp_path / "project", ["dev"], lambda env: absolute) == [
            ("dev", absolute)
        ]

    def test_unresolvable_and_missing_environments_are_skipped(self, tmp_path):
        (tmp_path / RUNS).mkdir(parents=True)

        def runs_dir_for(env):
            return {"dev": RUNS, "prod": Path("nowhere")}.get(env)

        assert candidate_runs_dirs(tmp_path, ["base", "dev", "prod"], runs_dir_for) == [
            ("dev", tmp_path / RUNS)
        ]

    def test_a_directory_shared_by_two_environments_is_listed_once(self, tmp_path):
        shared = tmp_path / "runs"
        shared.mkdir()

        assert candidate_runs_dirs(tmp_path, ["dev", "prod"], lambda env: shared) == [
            ("dev", shared)
        ]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


@pytest.fixture()
def env_folder_project(tmp_path: Path) -> Path:
    """A project whose `./data` exists only under `dev/`: the API server runs it from `dev/`."""
    project = tmp_path / "sales"
    _write(
        project / "ducta.yaml",
        """
        version: 2
        project: sales
        paths: {input: data, output: data}
        settings: {mode: local}
        """,
    )
    _write(project / "catalog.yaml", "{}\n")
    (project / "pipelines").mkdir()
    run_dir = project / "dev" / RUNS / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "certificate.json").write_text(json.dumps({"run_id": "run1"}), encoding="utf-8")
    return project


class TestCliAndWebUiSeeTheSameRuns:
    def test_the_api_finds_the_certificate_of_a_run_it_made_from_the_env_folder(
        self, env_folder_project
    ):
        from ducta.runs.certificates import candidate_runs_dirs as api_candidates

        found = api_candidates(env_folder_project, "dev")

        assert ("dev", env_folder_project / "dev" / RUNS) in found

    def test_ducta_certify_finds_the_same_certificate(self, env_folder_project, monkeypatch):
        from ducta.console.commands.certify_cmds import _candidate_runs_dirs

        monkeypatch.chdir(env_folder_project)  # _candidate_runs_dirs chdirs to the root
        args = SimpleNamespace(dir=None, env="dev", base_path=str(env_folder_project))

        found = _candidate_runs_dirs(args)

        assert ("dev", env_folder_project.resolve() / "dev" / RUNS) in [
            (env, d.resolve()) for env, d in found
        ]
