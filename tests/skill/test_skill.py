"""The Ducta agent skill (``src/ducta/skills/ducta``) stays valid and true.

An AI assistant follows the skill literally, so a command or flag it names that
no longer exists sends the assistant — and the user — down a dead end. These
tests hold the skill to the open Agent Skills format and to the real CLI.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import pytest
import yaml

from ducta.console.commands import skill_cmds
from ducta.console.commands.skill_cmds import SkillCommands
from ducta.console.parser import UnifiedArgumentParser

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "src" / "ducta" / "skills" / "ducta"
DOCS = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
#: Frontmatter fields the Agent Skills specification defines.
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def _frontmatter() -> Tuple[Dict, str]:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert m, "SKILL.md must start with YAML frontmatter between --- lines"
    return yaml.safe_load(m.group(1)), m.group(2)


# ── the format ───────────────────────────────────────────────────────────────


def test_frontmatter_follows_the_agent_skills_spec():
    meta, body = _frontmatter()
    assert set(meta) <= SPEC_FIELDS, set(meta) - SPEC_FIELDS
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
    assert meta["name"] == SKILL.name
    assert 0 < len(meta["description"]) <= 1024
    assert 0 < len(meta.get("compatibility", "x")) <= 500
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in meta["metadata"].items())
    # Experimental and read differently by each agent: left out on purpose.
    assert "allowed-tools" not in meta


def test_skill_md_stays_small():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 500
    assert len(text) / 4 < 5000  # ~tokens


def test_skills_ref_validates_it_when_installed():
    tool = shutil.which("skills-ref")
    if not tool:
        pytest.skip("skills-ref is not installed")
    done = subprocess.run([tool, "validate", str(SKILL)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_text_names_no_single_agents_tools():
    """Portable wording: no tool names of one assistant."""
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        for word in ("Bash tool", "Read tool", "Edit tool", "TodoWrite", "subagent"):
            assert word not in text, f"{path.name} mentions {word!r}"


# ── links ────────────────────────────────────────────────────────────────────


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def _anchors(path: Path) -> set:
    return {
        _slug(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    }


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_every_relative_link_resolves(path):
    text = path.read_text(encoding="utf-8")
    for target, anchor in re.findall(r"\]\(([^)#\s]*)(#[^)\s]*)?\)", text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        dest = (path.parent / target).resolve() if target else path
        assert dest.is_file(), f"{path.name}: link to missing {target}"
        if path.name == "SKILL.md" and target:
            # One level deep from SKILL.md, as the spec recommends.
            assert len(Path(target).parts) <= 2, target
        if anchor and dest.suffix == ".md":
            assert anchor[1:] in _anchors(dest), f"{path.name}: no heading for {target}{anchor}"


# ── commands and flags exist ─────────────────────────────────────────────────


def _subparsers(parser: argparse.ArgumentParser) -> Dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _options(parser: argparse.ArgumentParser) -> set:
    return {o for a in parser._actions for o in a.option_strings}


def _commands(text: str) -> Iterator[str]:
    """``ducta …`` invocations in code blocks and inline code."""
    for block in re.findall(r"```(?:bash|sh|shell|console)?\n(.*?)```", text, re.DOTALL):
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            line = line.split("#", 1)[0].strip()
            m = re.search(r"(?:^|[;&|(]\s*|\$\s*)(ducta\s.*)$", line) or re.match(
                r"(ducta\s.*)", line
            )
            if m:
                yield m.group(1)
    for span in re.findall(r"`(ducta [^`]+)`", text):
        yield span


def _check(command: str) -> List[str]:
    try:
        tokens = shlex.split(command)[1:]  # quotes keep "$(date -d …)" one value
    except ValueError:
        tokens = command.split()[1:]
    tokens = [t.split("=", 1)[0] if t.startswith("--") else t for t in tokens]
    parser = UnifiedArgumentParser.create()
    chain = [parser]
    path = ["ducta"]
    problems: List[str] = []
    for token in tokens:
        subs = _subparsers(chain[-1])
        if not token.startswith("-") and token in subs and len(path) == len(chain):
            chain.append(subs[token])
            path.append(token)
            continue
        if token.startswith("-") and not re.fullmatch(r"-\d.*", token):
            flag = token.split("=", 1)[0]
            if not any(flag in _options(p) for p in chain):
                problems.append(f"`{command}`: {' '.join(path)} has no option {flag}")
        elif (
            len(path) == len(chain)
            and subs
            and not token.startswith(("<", "-"))
            and token.islower()
        ):
            # A lower-case word where a subcommand is expected: one that does not exist.
            if re.fullmatch(r"[a-z][a-z-]*", token):
                problems.append(f"`{command}`: {' '.join(path)} has no subcommand {token!r}")
        if not token.startswith("-"):
            path.append(token)  # anything else is a positional value: stop descending
    return problems


@pytest.mark.parametrize("path", [p for p in DOCS if p.name != "cli.md"], ids=lambda p: p.name)
def test_every_command_and_flag_exists(path):
    text = path.read_text(encoding="utf-8")
    problems = [p for command in _commands(text) for p in _check(command)]
    assert not problems, "\n".join(problems)


def test_the_checker_catches_a_wrong_flag_and_a_wrong_subcommand():
    assert _check("ducta config validate --env dev --output-format json") == []
    assert _check("ducta config validat --env dev")
    assert _check("ducta start --pipeline etl --date 2026-01-01")


def test_cli_reference_is_up_to_date():
    spec = importlib.util.spec_from_file_location(
        "gen_skill_cli_reference", REPO / "scripts" / "gen_skill_cli_reference.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = (SKILL / "references" / "cli.md").read_text(encoding="utf-8")
    assert current == module.render(), "run: python scripts/gen_skill_cli_reference.py"


# ── the example project and the version ──────────────────────────────────────


def test_the_example_project_validates_in_every_environment():
    from ducta.setting.project_loader import validate_project

    root = SKILL / "assets" / "examples" / "sales"
    project = validate_project(root)
    for env in project.project.environments:
        validate_project(root, env)


def test_the_example_projects_code_matches_its_nodes():
    pytest.importorskip("fastapi")
    from ducta.api.repositories.v2_store import V2ProjectStore
    from ducta.api.services.draft_validation import code_problems

    store = V2ProjectStore.detect(SKILL / "assets" / "examples" / "sales")
    assert [p.message for p in code_problems(store)] == []


def test_the_skill_describes_this_ducta_version():
    import tomllib

    version = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["poetry"]["version"]
    meta, _ = _frontmatter()
    assert version.startswith(meta["metadata"]["ducta-version"] + ".")


def test_check_env_runs_on_the_standard_library_alone():
    script = SKILL / "scripts" / "check_env.py"
    example = SKILL / "assets" / "examples" / "sales"
    done = subprocess.run(
        [sys.executable, "-I", str(script), "--project", str(example)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert {"python", "ducta", "extras", "java", "project_root", "warnings", "ok"} <= set(report)
    assert report["project_root"] == str(example.resolve())
    assert report["ducta"]["skill_expects"] == _frontmatter()[0]["metadata"]["ducta-version"]


# ── ducta skill install / export ─────────────────────────────────────────────


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ducta.yaml").write_text("version: 2\nproject: p\npaths: {input: d, output: d}\n")
    monkeypatch.chdir(root)
    return root


def _run(*argv: str) -> int:
    args = UnifiedArgumentParser.create().parse_args(["skill", *argv])
    return SkillCommands.handle(args)


def test_install_defaults_to_the_shared_folder_and_claudes(project):
    assert _run("install") == 0
    for folder in (".agents/skills/ducta", ".claude/skills/ducta"):
        assert (project / folder / "SKILL.md").is_file()
        assert (project / folder / "references" / "cli.md").is_file()
        assert not list((project / folder).rglob("__pycache__"))
    # Again: nothing to do.
    assert _run("install") == 0


@pytest.mark.parametrize(
    "target, folder",
    [("copilot", ".github/skills"), ("gemini", ".gemini/skills"), ("codex", ".agents/skills")],
)
def test_install_for_one_assistant(project, target, folder):
    assert _run("install", "--target", target) == 0
    assert (project / folder / "ducta" / "SKILL.md").is_file()


def test_install_globally_goes_to_the_home_folder(project):
    assert _run("install", "--global", "--target", "claude") == 0
    assert (Path.home() / ".claude" / "skills" / "ducta" / "SKILL.md").is_file()
    assert not (project / ".claude").exists()


def test_another_version_needs_force_and_a_foreign_folder_is_never_replaced(project):
    assert _run("install", "--target", "agents") == 0
    installed = project / ".agents" / "skills" / "ducta" / "SKILL.md"
    installed.write_text(
        installed.read_text().replace('skill-version: "1.0.0"', 'skill-version: "0.9"')
    )
    assert _run("install", "--target", "agents") != 0
    assert _run("install", "--target", "agents", "--force") == 0
    assert 'skill-version: "1.0.0"' in installed.read_text()

    other = project / ".claude" / "skills" / "ducta"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("---\nname: somebody-else\n---\n")
    assert _run("install", "--target", "claude", "--force") != 0
    assert "somebody-else" in (other / "SKILL.md").read_text()


def test_agents_md_block_is_added_once_and_the_rest_kept(project):
    (project / "AGENTS.md").write_text("# House rules\n\nUse tabs.\n")
    assert _run("install", "--target", "agents", "--agents-md") == 0
    assert _run("install", "--target", "agents", "--agents-md") == 0
    text = (project / "AGENTS.md").read_text()
    assert text.startswith("# House rules") and "Use tabs." in text
    assert text.count("<!-- ducta-skill:start -->") == 1
    assert ".agents/skills/ducta/SKILL.md" in text


def test_install_from_a_subfolder_goes_next_to_ducta_yaml(project, monkeypatch):
    (project / "pipelines").mkdir()
    monkeypatch.chdir(project / "pipelines")
    assert _run("install", "--target", "claude") == 0
    assert (project / ".claude" / "skills" / "ducta" / "SKILL.md").is_file()
    assert not (project / "pipelines" / ".claude").exists()


def test_install_outside_a_project_warns(tmp_path, monkeypatch, capsys):
    from loguru import logger

    lines: list = []
    sink = logger.add(lines.append, level="WARNING")
    logger.enable("ducta")  # the library is silent until the CLI turns it on
    try:
        monkeypatch.chdir(tmp_path)
        assert _run("install", "--target", "claude") == 0
    finally:
        logger.disable("ducta")
        logger.remove(sink)
    assert any("No ducta.yaml" in str(m) for m in lines)
    assert "Commit these folders" not in capsys.readouterr().out


def test_install_into_a_file_is_refused_in_words(project):
    (project / "afile").write_text("")
    assert _run("install", "--path", str(project / "afile")) != 0


def test_agents_md_points_to_the_shared_copy(project, capsys):
    assert _run("install", "--target", "gemini", "--target", "agents", "--agents-md") == 0
    assert ".agents/skills/ducta/SKILL.md" in (project / "AGENTS.md").read_text()
    assert "Restart your assistant" in capsys.readouterr().out


def test_export_zips_the_skill_folder(tmp_path):
    out = skill_cmds.export_zip(tmp_path / "ducta-skill.zip")
    names = zipfile.ZipFile(out).namelist()
    assert "ducta/SKILL.md" in names
    assert any(n.startswith("ducta/references/") for n in names)
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


def test_the_eval_cases_are_well_formed():
    cases = yaml.safe_load((Path(__file__).parent / "evals" / "cases.yaml").read_text())["cases"]
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) >= 20
    for case in cases:
        assert {"id", "area", "start", "prompt", "expect", "never"} <= set(case), case["id"]
