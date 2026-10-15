"""A generated project keeps its secrets out of git.

The docs tell users to put credentials in `.env`; the template's `.gitignore`
ignored `env/` (a virtualenv) but not `.env`, so the first `git add .` committed them.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from ducta.console.template import TemplateGenerator, TemplateType

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _ignored(root, name: str) -> bool:
    (root / name).write_text("X=1\n")
    result = subprocess.run(["git", "check-ignore", "-q", name], cwd=root)
    return result.returncode == 0


@pytest.mark.parametrize("template", list(TemplateType))
def test_dotenv_is_ignored_and_its_templates_are_not(tmp_path, template):
    root = tmp_path / "proj"
    TemplateGenerator(root).generate_project(template, "proj")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    assert _ignored(root, ".env")
    assert _ignored(root, ".env.local")
    assert not _ignored(root, ".env.example")
