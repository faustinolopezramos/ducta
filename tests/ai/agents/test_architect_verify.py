"""`ducta ai architect verify`: what it checks, what it runs, and where it never runs.

The project is the skill's `sales` example (bronze.sales, then silver.sales, which
depends on it). Nothing here starts a real run: `run_pipeline` and the
`ducta config validate` child process are replaced.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ducta.ai.agents import runs
from ducta.ai.agents.architect import verify as verify_module
from ducta.ai.agents.architect.verify import verify
from ducta.ai.agents.runs import RunOutcome
from ducta.ai.errors import AIConfigError

SALES = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "ducta"
    / "skills"
    / "ducta"
    / "assets"
    / "examples"
    / "sales"
)


@pytest.fixture
def sales(tmp_path, monkeypatch):
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    monkeypatch.setattr(verify_module, "_preflight", lambda root, env, names: [])
    return root


class _Runs(list):
    """The runs made, in order; each pipeline exits with ``exit_codes[name]`` (0)."""

    def __init__(self) -> None:
        super().__init__()
        self.exit_codes: dict = {}


@pytest.fixture
def runs_made(monkeypatch):
    made = _Runs()

    def fake_run(root, env, name, **kwargs):
        made.append((env, name, kwargs))
        return RunOutcome(exit_code=made.exit_codes.get(name, 0), output=f"ran {name}")

    monkeypatch.setattr(runs, "run_pipeline", fake_run)
    return made


def test_pipelines_are_checked_in_dependency_order(sales, runs_made):
    report = verify(sales, ["silver.sales", "bronze.sales"])

    assert report.pipelines == ["bronze.sales", "silver.sales"]
    assert report.errors == []
    assert runs_made == []  # checking is not running
    assert any("--run" in step for step in report.next_steps)


def test_no_names_means_every_pipeline(sales, runs_made):
    assert verify(sales, []).pipelines == ["bronze.sales", "silver.sales"]


def test_an_unknown_pipeline_is_refused(sales, runs_made):
    with pytest.raises(AIConfigError, match="No pipeline gold.sales"):
        verify(sales, ["gold.sales"])


def test_a_project_that_does_not_load_reports_why(sales, runs_made):
    (sales / "ducta.yaml").write_text("version: 2\nprojct: sales\n", encoding="utf-8")

    report = verify(sales, ["bronze.sales"], run=True)

    assert report.errors and not report.ok
    assert runs_made == []


def test_preflight_errors_block_the_run(sales, runs_made, monkeypatch):
    monkeypatch.setattr(
        verify_module, "_preflight", lambda root, env, names: ["silver.sales: no function"]
    )

    report = verify(sales, [], run=True)

    assert report.errors == ["silver.sales: no function"]
    assert runs_made == []
    assert not report.ok


@pytest.mark.parametrize("env", ["prod", "production"])
def test_it_never_runs_in_a_protected_environment(sales, runs_made, env):
    with pytest.raises(AIConfigError, match="protected"):
        verify(sales, [], env=env, run=True)
    assert runs_made == []


def test_it_runs_in_dependency_order_in_the_environment_asked(sales, runs_made):
    report = verify(sales, ["silver.sales", "bronze.sales"], run=True)

    assert [(env, name) for env, name, _ in runs_made] == [
        ("dev", "bronze.sales"),
        ("dev", "silver.sales"),
    ]
    assert report.ok
    # Each node with code gets the follow-up that proves checks on real output.
    assert any("ducta ai quality silver.sales clean_orders" in s for s in report.next_steps)


def test_the_first_failure_stops_the_rest(sales, runs_made):
    runs_made.exit_codes["bronze.sales"] = 4

    report = verify(sales, [], run=True)

    assert [name for _, name, _ in runs_made] == ["bronze.sales"]
    assert report.runs == [
        {"pipeline": "bronze.sales", "ok": False, "exit_code": 4, "output": "ran bronze.sales"}
    ]
    assert not report.ok
    assert any(s.startswith("ducta ai fix bronze.sales") for s in report.next_steps)


def test_a_pipeline_that_needs_dates_is_not_run_without_them(sales, runs_made):
    silver = sales / "pipelines" / "silver.sales.yaml"
    silver.write_text(
        silver.read_text(encoding="utf-8").replace("requires_dates: false", "requires_dates: true"),
        encoding="utf-8",
    )

    report = verify(sales, [], run=True)

    assert [name for _, name, _ in runs_made] == ["bronze.sales"]
    assert report.runs[-1] == {
        "pipeline": "silver.sales",
        "ok": False,
        "exit_code": None,
        "output": "needs --start-date/--end-date",
    }


def test_dates_reach_only_the_pipelines_that_need_them(sales, runs_made):
    silver = sales / "pipelines" / "silver.sales.yaml"
    silver.write_text(
        silver.read_text(encoding="utf-8").replace("requires_dates: false", "requires_dates: true"),
        encoding="utf-8",
    )

    verify(sales, [], run=True, start_date="2024-01-01", end_date="2024-01-02")

    dates = {name: (kw["start_date"], kw["end_date"]) for _, name, kw in runs_made}
    assert dates == {
        "bronze.sales": (None, None),
        "silver.sales": ("2024-01-01", "2024-01-02"),
    }


class TestPreflight:
    """`_preflight` reads `ducta config validate --output-format json` from a child process."""

    @staticmethod
    def _child(monkeypatch, stdout="", returncode=0, raises=None):
        def fake_run(*args, **kwargs):
            if raises:
                raise raises
            return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_only_errors_of_the_pipelines_asked_are_kept(self, monkeypatch, tmp_path):
        payload = {
            "ok": False,
            "config_error": [
                {"severity": "error", "message": "unknown key 'outptus'"},
                {"severity": "warning", "message": "a warning"},
            ],
            "pipelines": {
                "etl": {"problems": [{"severity": "error", "message": "function not found"}]},
                "other": {"problems": [{"severity": "error", "message": "not asked"}]},
                "warned": {"problems": [{"severity": "warning", "message": "only a warning"}]},
            },
        }
        # The CLI may print a banner before the JSON.
        self._child(monkeypatch, stdout="Ducta 0.3\n" + json.dumps(payload), returncode=3)

        problems = verify_module._preflight(tmp_path, "dev", ["etl", "warned"])

        assert problems == ["unknown key 'outptus'", "etl: function not found"]

    def test_output_that_is_not_json_is_an_error_only_when_it_failed(self, monkeypatch, tmp_path):
        self._child(monkeypatch, stdout="all good", returncode=0)
        assert verify_module._preflight(tmp_path, "dev", ["etl"]) == []

        self._child(monkeypatch, stdout="Traceback…", returncode=2)
        assert verify_module._preflight(tmp_path, "dev", ["etl"]) == [
            "`ducta config validate` exited 2"
        ]

    def test_a_child_that_cannot_start_is_reported(self, monkeypatch, tmp_path):
        self._child(monkeypatch, raises=subprocess.TimeoutExpired("ducta", 600))

        [problem] = verify_module._preflight(tmp_path, "dev", ["etl"])

        assert problem.startswith("`ducta config validate` did not run")
