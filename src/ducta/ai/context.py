"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

What the model is told about a project, and nothing more.

Names, formats, descriptions and declared schemas of datasets; pipelines and
their nodes; source *names*; the signatures of the project's functions; one
existing pipeline file and one node function as examples of house style (with
any credential written in them masked). Never data rows, connection details,
credentials or ``.env`` — so what reaches a remote provider is the
configuration and code a reviewer would see in a pull request.
No project module is imported: code is read from its syntax tree.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]

from ducta.setting.project_loader import (
    CATALOG_DIR,
    PIPELINES_DIR,
    ProjectConfigError,
    catalog_dir_files,
    catalog_location,
    read_project,
    validate_project,
)

#: Directories never read for code, nor written to by a draft (hidden ones neither).
SKIP_DIRS = frozenset(
    {"data", "logs", "models", "lib", "node_modules", "__pycache__", "venv", "site-packages"}
)
#: Upper bound on the rendered context, in characters (~10k tokens).
MAX_CHARS = 40_000
_EXAMPLE_PIPELINE_LINES = 70
_EXAMPLE_FUNCTION_LINES = 60


@dataclass
class ProjectContext:
    root: Path
    name: str
    #: ``catalog/`` (a folder of files) or the single catalog file, project-relative.
    catalog_layout: str
    catalog: Dict[str, str] = field(default_factory=dict)
    #: Where existing datasets live (``path`` as written, or ``table:<name>``)
    #: → dataset name, so a new entry cannot point at the same data.
    locations: Dict[str, str] = field(default_factory=dict)
    pipelines: Dict[str, Any] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    example_pipeline: Optional[str] = None
    example_function: Optional[str] = None
    sections: List[str] = field(default_factory=list)
    #: Where in ``sections`` the function list goes. It is the one section that
    #: shrinks to fit, so a large project keeps its catalog and its examples.
    functions_at: Optional[int] = None
    #: The project does not validate today; the model is told so.
    config_error: Optional[str] = None

    def render(self, max_chars: int = MAX_CHARS) -> str:
        sections = list(self.sections)
        if self.functions_at is not None:
            others = sum(len(s) + 2 for i, s in enumerate(sections) if i != self.functions_at)
            sections[self.functions_at] = _fit_functions(self.functions, max_chars - others)
        text = "\n\n".join(s for s in sections if s)
        if len(text) > max_chars:
            # Cut at a line, and close a fence left open so what follows reads as prose.
            text = text[:max_chars].rsplit("\n", 1)[0]
            if text.count("```") % 2:
                text += "\n```"
            text += "\n… (context truncated)"
        return text


_FUNCTIONS_HEADER = "# Python functions in the project (module:function(params))"


def _fit_functions(functions: List[str], budget: int) -> str:
    """The function-list section in at most *budget* characters, saying what it left out."""
    lines = [_FUNCTIONS_HEADER]
    used = len(_FUNCTIONS_HEADER)
    for i, line in enumerate(functions):
        left = len(functions) - i
        # Room for this line and, unless it is the last, for the note on the rest.
        reserve = 0 if left == 1 else len(f"\n- … and {left - 1} more not listed")
        if used + 1 + len(line) + reserve > budget:
            lines.append(f"- … and {left} more not listed")
            break
        lines.append(line)
        used += 1 + len(line)
    return "\n".join(lines)


#: Credentials that commonly end up in a failed run's error text: a URL's
#: password, ``password=…``-style settings, and bearer tokens.
_SECRETS = (
    (re.compile(r"(\b[a-zA-Z][\w+.-]*://[^/\s:@]+:)[^/\s@]+@"), r"\1***@"),
    (
        re.compile(
            r"(?i)\b((?:password|passwd|pwd|secret|client[_-]?secret|token|access[_-]?token|"
            r"api[_-]?key|access[_-]?key|account[_-]?key|sas[_-]?token|sig)"
            r"[\"']?\s*[=:]\s*[\"']?)[^\s\"';,&]+"
        ),
        r"\1***",
    ),
    (re.compile(r"(?i)\b(bearer\s+)[\w.~+/=-]+"), r"\1***"),
)


def redact(text: str) -> str:
    """*text* with the credentials it obviously contains replaced by ``***``."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


#: Credentials written into code or YAML: a quoted value given to a
#: secret-sounding name, a URL's password, a bearer token, or a key whose
#: prefix gives it away. Narrower than :data:`_SECRETS`, which also catches
#: ``token = tokenize(x)`` — fine for an error message, not for code.
_CODE_SECRETS = (
    (
        "a quoted password, secret, token or key",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|client[_-]?secret|token|access[_-]?token|"
            r"api[_-]?key|access[_-]?key|account[_-]?key|sas[_-]?token)\b[\"']?\s*[=:]\s*"
            r"(?P<q>[\"'])(?P<v>[^\"'\s$]{6,})(?P=q)"
        ),
    ),
    ("a URL with a password", re.compile(r"\b[a-zA-Z][\w+.-]*://[^/\s:@]+:(?P<v>[^/\s@$]+)@")),
    ("a bearer token", re.compile(r"(?i)\bbearer\s+(?P<v>[\w.~+/-]{16,}=*)")),
    (
        "an API key",
        re.compile(
            r"\b(?P<v>(?:sk-[\w-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_\w{30,}|xox[abp]-[\w-]{10,}))"
        ),
    ),
)
#: Values that are placeholders, not secrets.
_PLACEHOLDER = re.compile(r"^(?:\*+|x+|changeme|password|secret|<[^>]*>|\{[^}]*\})$", re.I)


def _secret_spans(text: str) -> List[tuple]:
    spans = []
    for label, pattern in _CODE_SECRETS:
        for m in pattern.finditer(text):
            if not _PLACEHOLDER.match(m.group("v")):
                spans.append((m.start("v"), m.end("v"), label))
    return spans


def find_secrets(text: str) -> List[str]:
    """What kinds of credential *text* (code or YAML) seems to contain — never the values."""
    return sorted({label for _, _, label in _secret_spans(text)})


def redact_code(text: str) -> str:
    """*text* (code or YAML) with the credentials :func:`find_secrets` sees replaced by ``***``."""
    for start, end, _ in sorted(_secret_spans(text), reverse=True):
        text = text[:start] + "***" + text[end:]
    return text


def normalize_location(path: str) -> str:
    """A catalog ``path`` in one spelling: no leading ``./``, no trailing ``/``."""
    path = str(path).strip()
    while path.startswith("./"):
        path = path[2:]
    return path.rstrip("/")


def _code_files(root: Path) -> List[Path]:
    """The project's ``.py`` files, never descending into skipped folders (``data/`` can be huge)."""
    out = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        out += [Path(folder) / f for f in files if f.endswith(".py")]
    return sorted(out)


def _module_of(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _function_source(source: str, name: str, limit: int) -> Optional[str]:
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines = source.splitlines()[node.lineno - 1 : node.end_lineno]
            if len(lines) > limit:
                lines = lines[:limit] + ["    # …"]
            return "\n".join(lines)
    return None


def _imports(source: str) -> List[str]:
    return [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and not line.startswith("from __future__")
    ]


def _source_names(root: Path, settings: Dict[str, Any]) -> List[str]:
    ingestion = settings.get("ingestion") or {}
    rel = ingestion.get("sources_path") if isinstance(ingestion, dict) else None
    path = root / (rel or "sources.yaml")
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    sources = data.get("sources", data) if isinstance(data, dict) else {}
    out = []
    for name, spec in (sources or {}).items():
        kind = spec.get("type") if isinstance(spec, dict) else None
        out.append(f"{name} ({kind})" if kind else str(name))
    return out


def _node_line(name: str, node: Any) -> str:
    kind = getattr(node, "kind", "transform")
    parts = [f"  - {name} [{kind}]"]
    run = getattr(node, "run", None)
    if run:
        parts.append(f"run={run}")
    inputs = getattr(node, "inputs", None)
    if inputs:
        parts.append(f"inputs={dict(inputs) if isinstance(inputs, dict) else list(inputs)}")
    ingest = getattr(node, "ingest", None)
    if ingest is not None:
        parts.append(f"ingest={ingest.model_dump(exclude_none=True)}")
    outputs = getattr(node, "outputs", None)
    if outputs:
        parts.append(f"outputs={list(outputs)}")
    stage = getattr(node, "ml_stage", None)
    if stage:
        parts.append(f"ml_stage={stage}")
    return " ".join(parts)


def build_context(root: Path) -> ProjectContext:
    """Everything the model is told about the project at *root*."""
    root = Path(root).resolve()
    catalog_at = catalog_location(root)
    layout = (
        f"{CATALOG_DIR}/ (one file per group of datasets)"
        if catalog_dir_files(root)
        else catalog_at.relative_to(root).as_posix()
    )
    try:
        project = validate_project(root)
        config_error = None
    except ProjectConfigError as e:
        project = None
        config_error = "; ".join(e.problems[:5])

    ctx = ProjectContext(
        root=root, name=root.name, catalog_layout=layout, config_error=config_error
    )
    if project is None:
        ctx.sections.append(
            f"# Project at {root.name}\nThe project does not validate right now: {config_error}"
        )
        return ctx

    pf = project.project
    ctx.name = pf.project
    settings = dict(pf.settings or {})
    head = [f"# Project: {pf.project}"]
    if pf.description:
        head.append(pf.description.strip())
    head.append(f"Environments: {', '.join(pf.environments) or '(base only)'}")
    head.append(
        f"Engine mode: {settings.get('mode', 'local')} (node functions receive DataFrames; "
        "use the same library as the example function below)"
    )
    defaults = pf.defaults.catalog if pf.defaults else None
    formats = {g: spec["format"] for g, spec in (defaults or {}).items() if spec.get("format")}
    if formats:
        # Only the format: the rest of a default (paths, storage options) is not the model's.
        head.append("Catalog defaults by glob (a dataset matching one needs no `format`):")
        head += [f"  {glob}: format {fmt}" for glob, fmt in formats.items()]
    head.append(f"Catalog lives in: {layout}")
    ctx.sections.append("\n".join(head))

    writers: Dict[str, str] = {}
    lines = ["# Pipelines (pipelines/<name>.yaml; the name is the file stem)"]
    for pname, pipe in sorted(project.pipelines.items()):
        deps = f" depends_on={pipe.depends_on}" if pipe.depends_on else ""
        desc = f" — {pipe.description}" if pipe.description else ""
        lines.append(f"- {pname} (type={pipe.type}){deps}{desc}")
        ctx.pipelines[pname] = list(pipe.nodes)
        for nname, node in pipe.nodes.items():
            lines.append(_node_line(nname, node))
            for out in getattr(node, "outputs", None) or []:
                writers.setdefault(out, nname)
    ctx.sections.append("\n".join(lines))

    # In the catalog's own YAML shape, so a model that copies it writes valid entries.
    lines = ["# Datasets already in the catalog (reuse them; never redeclare)", "```yaml"]
    for dname, entry in sorted(project.catalog.items()):
        spec: Dict[str, Any] = {"format": entry.format}
        if entry.description:
            spec["description"] = entry.description.strip()
        if entry.schema_def:
            spec["schema"] = entry.schema_def
        flow = yaml.safe_dump(
            {dname: spec}, default_flow_style=None, width=1000, allow_unicode=True, sort_keys=False
        )
        writer = f"written by {writers[dname]}" if dname in writers else "source data"
        lines.append(f"{flow.rstrip()}  # {writer}")
        ctx.catalog[dname] = entry.format
        if entry.path:
            ctx.locations[normalize_location(entry.path)] = dname
        if entry.table:
            ctx.locations[f"table:{entry.table}"] = dname
    lines.append("```")
    ctx.sections.append("\n".join(lines))

    ctx.sources = _source_names(root, settings)
    if ctx.sources:
        ctx.sections.append(
            "# Ingestion sources (for kind: ingest nodes)\n"
            + "\n".join(f"- {s}" for s in ctx.sources)
        )

    _add_code(ctx, root, project)
    return ctx


def _add_code(ctx: ProjectContext, root: Path, project: Any) -> None:
    from ducta.api.services.code_index import top_level_functions

    used = {
        node.run: None
        for pipe in project.pipelines.values()
        for node in pipe.nodes.values()
        if getattr(node, "run", None)
    }
    lines: List[str] = []
    first_import_block: List[str] = []
    for path in _code_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        module = _module_of(root, path)
        for fn in top_level_functions(source):
            if fn.name.startswith("_"):
                continue
            lines.append(f"- {module}:{fn.name}({', '.join(fn.params)})")
            ref = f"{module}:{fn.name}"
            if ctx.example_function is None and ref in used:
                body = _function_source(source, fn.name, _EXAMPLE_FUNCTION_LINES)
                if body:
                    first_import_block = _imports(source)
                    ctx.example_function = redact_code(
                        "\n".join([*first_import_block, "", "", body])
                    )
    ctx.functions = lines
    if lines:
        ctx.functions_at = len(ctx.sections)
        ctx.sections.append("")  # filled by render(), to fit
    if ctx.example_function:
        if "pyspark" in ctx.example_function:
            ctx.sections.append(
                "# DataFrame library\nNode functions take and return PySpark DataFrames "
                "(pyspark.sql). Do not use pandas."
            )
        ctx.sections.append(
            "# Example node function from this project (house style)\n```python\n"
            + ctx.example_function
            + "\n```"
        )

    try:
        files = read_project(root).pipeline_files
    except ProjectConfigError:
        files = {}
    for pname, path in sorted(files.items()):
        if path.suffix not in (".yaml", ".yml"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "run:" not in text:
            continue
        lines = text.splitlines()
        if len(lines) > _EXAMPLE_PIPELINE_LINES:
            lines = lines[:_EXAMPLE_PIPELINE_LINES] + ["# …"]
        ctx.example_pipeline = redact_code("\n".join(lines))
        ctx.sections.append(
            f"# Example pipeline file from this project ({PIPELINES_DIR}/{path.name})\n"
            "```yaml\n" + ctx.example_pipeline + "\n```"
        )
        break
