"""The engine and the CLI work without the web server or anything it depends on.

The web server (API + UI) is a separate distribution, ``ducta-server``, that
depends on ``ducta``. A CLI-only install has none of its dependencies, so
nothing the CLI, the AI layer or the agents run may need them.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from ducta.console import ui
from ducta.console.core import ExitCode

SRC = Path(__file__).resolve().parents[1] / "src"

#: What only the web server needs. Importing any of them fails in the child.
SERVER_ONLY = (
    "fastapi", "starlette", "uvicorn", "sqlalchemy", "alembic", "aiosqlite",
    "asyncpg", "psycopg2", "jwt", "bcrypt", "msgpack", "redis", "git",
)  # fmt: skip


def _run_without_the_server(code: str) -> subprocess.CompletedProcess:
    blocker = textwrap.dedent(
        f"""
        import sys
        for name in {SERVER_ONLY!r}:
            sys.modules[name] = None  # `import name` now raises ImportError
        sys.modules["ducta_server"] = None
        """
    )
    return subprocess.run(
        [sys.executable, "-c", blocker + textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        timeout=120,
    )


def test_the_shared_services_and_the_ai_layer_import_without_the_server():
    result = _run_without_the_server(
        """
        import importlib, pkgutil
        import ducta.project_store, ducta.runs
        for package in (ducta.project_store, ducta.runs):
            for m in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
                importlib.import_module(m.name)
        for name in (
            "ducta.ai.explain", "ducta.ai.review", "ducta.ai.proposals", "ducta.ai.loop",
            "ducta.ai.agents.sentinel.engine", "ducta.ai.agents.sentinel.triage",
            "ducta.ai.agents.sentinel.actions", "ducta.ai.agents.architect.verify",
            "ducta.console.commands.agent_cmds", "ducta.console.commands.ai_cmds",
            "ducta.console.cli",
        ):
            importlib.import_module(name)
        print("ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_a_project_is_read_and_its_runs_found_without_the_server(tmp_path):
    from ducta.console.cli import UnifiedCLI

    root = tmp_path / "shop"
    assert UnifiedCLI().run(["init", "project", "--name", "shop", "--path", str(root)]) == 0
    result = _run_without_the_server(
        f"""
        from pathlib import Path
        from ducta.project_store.store import V2ProjectStore
        from ducta.runs.certificates import certificates
        from ducta.runs.context import load_project_context

        root = Path({str(root)!r})
        store = V2ProjectStore.detect(root)
        assert store is not None and store.project().pipelines
        assert load_project_context(root, "dev") is not None
        assert list(certificates(root, None)) == []
        print("ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_ducta_ui_without_the_server_says_what_to_install(monkeypatch):
    monkeypatch.setattr(ui, "LAUNCHER_MODULE", "ducta_server_not_installed.launcher")
    messages = []
    monkeypatch.setattr(ui.logger, "error", lambda msg, *a: messages.append(msg.format(*a)))
    assert ui.launch_ui(open_browser=False) == ExitCode.DEPENDENCY_ERROR.value
    assert "pip install ducta-server" in messages[0]


# ---------------------------------------------------------------------------
# The two distributions ship together: one version, one set of server deps
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]


def _poetry(path: Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))["tool"]["poetry"]


def test_both_packages_and_the_web_app_have_one_version():
    import json

    engine = _poetry(REPO / "pyproject.toml")["version"]
    server = _poetry(REPO / "server" / "pyproject.toml")["version"]
    web_app = json.loads((REPO / "server" / "ui" / "package.json").read_text())["version"]
    assert engine == server == web_app


def test_the_server_requires_its_own_version_of_ducta_or_a_later_patch():
    """Not `X.Y.*`: a server that calls something a patch release added to the engine
    must not be installed with an older patch of it."""
    engine = _poetry(REPO / "pyproject.toml")["version"]
    major, minor, _ = engine.split(".", 2)
    assert _poetry(REPO / "server" / "pyproject.toml")["dependencies"]["ducta"] == (
        f">={engine},<{major}.{int(minor) + 1}.0"
    )


def test_the_dev_group_installs_what_the_server_depends_on():
    """`poetry install --with server` must give the tests what `pip install ducta-server` gives users."""
    server = dict(_poetry(REPO / "server" / "pyproject.toml")["dependencies"])
    server.pop("python")
    server.pop("ducta")
    group = _poetry(REPO / "pyproject.toml")["group"]["server"]["dependencies"]
    assert group == server


def test_ducta_has_no_server_extra_and_no_server_dependency():
    root = _poetry(REPO / "pyproject.toml")
    assert not {"api", "database"} & set(root["extras"])
    assert not {"fastapi", "uvicorn", "sqlalchemy"} & set(root["dependencies"])


def test_the_server_ships_the_same_license():
    # poetry packages server/LICENSE with ducta-server; it is a copy of the repo's.
    assert (REPO / "server" / "LICENSE").read_bytes() == (REPO / "LICENSE").read_bytes()


def test_the_three_server_commands_share_their_options():
    import argparse

    from ducta.console.parser import UnifiedArgumentParser, add_server_options

    def options(parser: argparse.ArgumentParser) -> set:
        return {a.dest for a in parser._actions if a.option_strings} - {"help"}

    reference = argparse.ArgumentParser()
    add_server_options(reference)
    root = UnifiedArgumentParser.create()
    for argv in (["ui"], ["server", "start"]):
        ns = root.parse_args(argv)
        assert {d for d in options(reference)} <= set(vars(ns))
    for d in options(reference):
        assert getattr(root.parse_args(["ui"]), d) == reference.get_default(d)


def test_a_broken_server_package_does_not_break_the_cli(monkeypatch):
    import importlib.util

    def boom(name):
        raise RuntimeError("a broken ducta_server/__init__.py")

    monkeypatch.setattr(importlib.util, "find_spec", boom)
    assert ui.server_installed() is False


def test_no_image_runs_an_environment_built_under_another_path():
    """pip writes the interpreter's absolute path into every command it installs: an
    environment copied from `/envs/a` to `/envs/b` has a `ducta` that cannot start."""
    import re

    copies = re.findall(
        r"^COPY --from=\S+ (/opt/\S+/envs/\S+) (/opt/\S+/envs/\S+)$",
        (REPO / "Dockerfile").read_text(),
        re.M,
    )
    assert copies, "the images copy their Python environments"
    assert all(src == dst for src, dst in copies), copies
