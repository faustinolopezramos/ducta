"""Every project YAML example in the docs validates against the schema.

A snippet takes part when its first line names the file it belongs to —
``# ducta.yaml``, ``# catalog.yaml`` or ``# pipelines/<name>.yaml``. Docs and
code drifted apart before (a README example used a module path the importer
rejects); this keeps the examples honest.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest
import yaml

from ducta.setting.project_schema import CatalogEntry, PipelineFile, ProjectFile

ROOT = Path(__file__).resolve().parents[2]
DOCS = [
    ROOT / "README.md",
    *sorted((ROOT / "docs").glob("*.rst")),
    *sorted((ROOT / "docs" / "tutorials").glob("*.rst")),
    *sorted((ROOT / "src" / "ducta").glob("*/README.md")),
]
_HEADER = re.compile(r"^#\s*(ducta\.yaml|catalog\.yaml|pipelines/[\w.-]+\.yaml)\b")


def _markdown_blocks(text: str) -> Iterator[str]:
    for match in re.finditer(r"```yaml\n(.*?)```", text, re.S):
        yield match.group(1)


def _rst_blocks(text: str) -> Iterator[str]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != ".. code-block:: yaml":
            continue
        indent = len(line) - len(line.lstrip())
        body: List[str] = []
        for nxt in lines[i + 1 :]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            body.append(nxt)
        yield textwrap.dedent("\n".join(body)).strip("\n")


def _snippets() -> Iterator[Tuple[str, str, str]]:
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        blocks = _markdown_blocks(text) if path.suffix == ".md" else _rst_blocks(text)
        for block in blocks:
            first = block.strip().splitlines()[0] if block.strip() else ""
            match = _HEADER.match(first)
            if match:
                yield f"{path.relative_to(ROOT)}:{match.group(1)}", match.group(1), block


SNIPPETS = list(_snippets())


def test_the_docs_do_have_format_2_examples():
    kinds = {kind.split("/")[0] for _, kind, _ in SNIPPETS}
    assert {"ducta.yaml", "catalog.yaml", "pipelines"} <= kinds


@pytest.mark.parametrize("where,kind,block", SNIPPETS, ids=[s[0] for s in SNIPPETS])
def test_snippet_validates(where, kind, block):
    data = yaml.safe_load(block)
    if kind == "ducta.yaml":
        ProjectFile.model_validate(data)
    elif kind == "catalog.yaml":
        for name, entry in data.items():
            CatalogEntry.model_validate(entry)
    else:
        PipelineFile.model_validate(data)


def test_the_configuration_guide_examples_form_one_valid_project(tmp_path):
    """Each ducta.yaml in the guide, with its catalog and etl pipeline, validates
    in every environment it overrides — so an override cannot point at a node or
    dataset the other examples do not have."""
    from ducta.setting.project_loader import compile_project, validate_project

    blocks = list(_rst_blocks((ROOT / "docs" / "configuration.rst").read_text(encoding="utf-8")))
    manifests = [b for b in blocks if b.startswith("# ducta.yaml")]
    catalogs = [b for b in blocks if b.startswith("# catalog.yaml")]
    pipeline = next(b for b in blocks if b.startswith("# pipelines/etl.yaml"))
    catalog = "\n".join(c.split("\n", 1)[1] for c in catalogs[:2])

    (tmp_path / "pipelines").mkdir()
    (tmp_path / "catalog.yaml").write_text(catalog)
    (tmp_path / "pipelines" / "etl.yaml").write_text(pipeline)
    assert manifests
    for manifest in manifests:
        (tmp_path / "ducta.yaml").write_text(manifest)
        for env in (None, *yaml.safe_load(manifest).get("environments", {})):
            compile_project(validate_project(tmp_path, env))
