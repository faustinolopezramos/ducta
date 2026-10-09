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

API storage for format-2 projects.

The API contract does not change with the file format: clients read and write
nodes, pipelines and configuration documents in the engine's shape (``module``
/``function``/``input``/``output``…). For a format-2 project this store
compiles those views from ``ducta.yaml``/``catalog.yaml``/``pipelines/`` and
translates writes back with ``ducta.setting.project_decompile``.

Every write is a transaction: edit the files (round-trip YAML, so comments and
key order in files people also edit by hand survive), re-validate the whole
project in every environment, and keep it only then. A write that would leave
the project invalid — or that format 2 cannot express — is rejected with the
reason, and the files are restored. Nothing is committed: committing is the
user's own, separate step.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from loguru import logger

from ducta.api.exceptions import (
    ConfigFileNotFoundError,
    NodeNotFoundError,
    PipelineNotFoundError,
    ValidationError,
)
from ducta.api.utils.git_utils import content_version, validate_version
from ducta.setting.project_loader import (
    CATALOG_DIR,
    CATALOG_FILE,
    PIPELINES_DIR,
    PROJECT_FILE,
    Project,
    ProjectConfigError,
    _checks,
    catalog_dir_files,
    catalog_location,
    compile_project,
    find_project_root,
    read_project,
    validate_project,
)

_PIPELINE_KEYS = (
    "description",
    "type",
    "requires_dates",
    "depends_on",
    "reuse_if_materialized",
    "spark_config",
    "split",
    "hyperparams",
    "hyperparams_config",
    "model_version",
)
#: Engine document name (API `configs` routes) → format-2 file it lives in.
DOC_FILES = {
    "global_config": PROJECT_FILE,
    "input": CATALOG_FILE,
    "output": CATALOG_FILE,
    "nodes": PIPELINES_DIR,
    "pipelines": PIPELINES_DIR,
}
_DOC_KEYS = {
    "global_config": "global_config",
    "input": "input_config",
    "output": "output_config",
    "nodes": "nodes_config",
    "pipelines": "pipelines_config",
}


# ── round-trip YAML ──────────────────────────────────────────────────────────


def _yaml(mapping: int = 2, sequence: int = 2, offset: int = 0) -> Any:
    from ruamel.yaml import YAML

    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=mapping, sequence=sequence, offset=offset)
    y.width = 100
    return y


def _style_of(text: str) -> Dict[str, int]:
    """The file's own indentation — kept on write, so editing one key does not
    re-indent every list in a file written with ``- `` further in.

    Measured where a block opens (a line ending in ``:``): how far its first
    child key sits in (the mapping indent), and how far a ``- `` sits in from
    its key (the sequence offset). The most common of each wins.
    """
    from collections import Counter

    maps: Counter = Counter()
    seqs: Counter = Counter()
    prev_indent: Optional[int] = None
    prev_opens = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if prev_opens and prev_indent is not None and indent > prev_indent:
            if stripped.startswith("- "):
                seqs[indent - prev_indent] += 1
            else:
                maps[indent - prev_indent] += 1
        body = stripped.split(" #", 1)[0].rstrip()
        prev_indent, prev_opens = indent, body.endswith(":")
    mapping = maps.most_common(1)[0][0] if maps else 2
    offset = seqs.most_common(1)[0][0] if seqs else 0
    return {"mapping": mapping, "sequence": offset + 2, "offset": offset}


def _load_rt(path: Path) -> Any:
    from ruamel.yaml.comments import CommentedMap

    if not path.exists():
        return CommentedMap()
    data = _yaml().load(path.read_text(encoding="utf-8"))
    return data if data is not None else CommentedMap()


def _restore_blank_lines(original: str, written: str) -> str:
    """Put back the blank lines ruamel drops (after a nested block sequence): a
    line kept from the original gets the blank lines it had before it. Lines
    are matched by text and by which occurrence of that text they are."""
    from collections import Counter

    def blanks_before(lines: List[str]) -> Dict[Tuple[str, int], int]:
        out: Dict[Tuple[str, int], int] = {}
        seen: Counter = Counter()
        run = 0
        for line in lines:
            if not line.strip():
                run += 1
                continue
            seen[line] += 1
            out[(line, seen[line])] = run
            run = 0
        return out

    wanted = blanks_before(original.splitlines())
    result: List[str] = []
    seen: Counter = Counter()
    run = 0
    for line in written.splitlines():
        if not line.strip():
            run += 1
            result.append(line)
            continue
        seen[line] += 1
        missing = wanted.get((line, seen[line]), 0) - run
        result.extend([""] * max(missing, 0))
        result.append(line)
        run = 0
    return "\n".join(result) + ("\n" if written.endswith("\n") else "")


def _dump_rt(path: Path, data: Any) -> None:
    import io

    original = path.read_text(encoding="utf-8") if path.exists() else None
    style = _style_of(original) if original is not None else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    _yaml(**style).dump(data, buf)
    text = buf.getvalue()
    if original is not None:
        text = _restore_blank_lines(original, text)
    path.write_text(text, encoding="utf-8")


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _sync(target: Any, desired: Dict[str, Any]) -> None:
    """Make mapping ``target`` equal ``desired``, keeping untouched subtrees as they are.

    Unchanged entries keep their comments and position; changed scalars and
    lists are replaced; nested mappings are synced recursively; new keys are
    appended.
    """
    for key in [k for k in target if k not in desired]:
        del target[key]
    for key, value in desired.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _sync(target[key], value)
        elif key not in target or _plain(target[key]) != value:
            target[key] = copy.deepcopy(value)


def _split_profiles(
    tree: Dict[str, Any], project_doc: Any, has_profiles_file: bool
) -> "tuple[Dict[str, Any], Dict[str, Any]]":
    """Divide the quality profiles between ``ducta.yaml`` and ``quality/profiles.*``.

    A profile stays where it was written; a new one goes to the profiles file when the
    project has one. Returns the tree to sync into ``ducta.yaml`` and the profiles of
    the profiles file.
    """
    if not has_profiles_file:
        return tree, {}
    quality = ((tree.get("settings") or {}).get("quality")) or {}
    desired = dict(quality.get("profiles") or {})
    settings_doc = project_doc.get("settings") if isinstance(project_doc, dict) else None
    quality_doc = (settings_doc or {}).get("quality") if isinstance(settings_doc, dict) else None
    owned = (
        set((quality_doc or {}).get("profiles") or {}) if isinstance(quality_doc, dict) else set()
    )
    for_project = {n: v for n, v in desired.items() if n in owned}
    for_file = {n: v for n, v in desired.items() if n not in owned}
    stripped = copy.deepcopy(tree)
    if "profiles" in quality:
        q = stripped["settings"]["quality"]
        if for_project:
            q["profiles"] = for_project
        else:
            del q["profiles"]
        if not q:
            del stripped["settings"]["quality"]
    return stripped, for_file


def _reorder(mapping: Any, order: List[str]) -> None:
    """Reorder a CommentedMap's keys to ``order`` (others keep their relative order)."""
    items = [(k, mapping[k]) for k in order if k in mapping]
    rest = [(k, mapping[k]) for k in mapping if k not in order]
    for key in list(mapping):
        del mapping[key]
    for key, value in items + rest:
        mapping[key] = value


# ── the store ────────────────────────────────────────────────────────────────


class V2ProjectStore:
    """Nodes, pipelines and configuration documents of one format-2 project."""

    def __init__(self, project_root: Path, repo_root: Optional[Path] = None) -> None:
        self.root = Path(project_root)
        #: The workspace root, which OCC conflict paths are reported relative to.
        self.repo_root = Path(repo_root or project_root)

    @classmethod
    def detect(cls, root: Path) -> Optional["V2ProjectStore"]:
        project_root = find_project_root(Path(root))
        return cls(project_root, Path(root)) if project_root is not None else None

    # ── reads ────────────────────────────────────────────────────────────────

    def project(self, env: Optional[str] = None) -> Project:
        try:
            return validate_project(self.root, env)
        except ProjectConfigError as e:
            raise ValidationError(
                "The project configuration is invalid", detail={"problems": e.problems}
            ) from e

    def documents(self, env: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """The five engine documents for ``env``, keyed as the API names them."""
        docs = compile_project(self.project(None if env in (None, "base") else env))
        return {api: docs[key] for api, key in _DOC_KEYS.items()}

    def nodes(self) -> Dict[str, Any]:
        return self.documents()["nodes"]

    def pipelines(self) -> Dict[str, Any]:
        return self.documents()["pipelines"]

    def pipeline_of(self, node: str, project: Optional[Project] = None) -> Optional[str]:
        project = project or self.project()
        return next((p for p, pipe in project.pipelines.items() if node in pipe.nodes), None)

    @property
    def pipelines_dir(self) -> Path:
        """The OCC unit for nodes and pipelines: clients' version tokens cover this folder."""
        return self.root / PIPELINES_DIR

    def pipeline_path(self, name: str) -> Path:
        default = self.root / PIPELINES_DIR / f"{name}.yaml"
        try:
            return read_project(self.root).pipeline_files.get(name, default)
        except ProjectConfigError:
            # A file that does not parse still has a place on disk.
            return default

    def file_for(self, doc_name: str) -> Path:
        if doc_name not in DOC_FILES:
            raise ConfigFileNotFoundError(
                f"Config '{doc_name}' does not exist", detail={"name": doc_name}
            )
        if DOC_FILES[doc_name] == CATALOG_FILE:
            return catalog_location(self.root)
        return self.root / DOC_FILES[doc_name]

    def commit_sha(self, path: Path) -> str:
        """The version token clients send back as ``expected_sha``.

        Named for what it used to be — the last commit that touched *path*.
        Saving no longer commits, so it is now :func:`content_version`: it
        changes whenever the content does, committed or not.
        """
        return content_version(path)

    # ── node writes ──────────────────────────────────────────────────────────

    def save_node(
        self,
        name: str,
        spec: Dict[str, Any],
        expected_sha: Optional[str] = None,
        pipeline: Optional[str] = None,
    ) -> str:
        project = self.project()
        owner = self.pipeline_of(name, project)
        if owner is None:
            if not pipeline:
                raise ValidationError(
                    f"In a format-2 project a node lives in a pipeline: pass `pipeline` "
                    f"to create node '{name}'",
                    detail={"node": name},
                )
            if pipeline not in project.pipelines:
                raise PipelineNotFoundError(
                    f"Pipeline '{pipeline}' not found", detail={"pipeline": pipeline}
                )
            owner = pipeline
        elif pipeline and pipeline != owner:
            raise ValidationError(
                f"Node '{name}' belongs to pipeline '{owner}', not '{pipeline}'",
                detail={"node": name, "pipeline": owner},
            )
        node = self._to_v2_node(name, spec, project)
        path = self.pipeline_path(owner)
        validate_version(self.repo_root, self.pipelines_dir, expected_sha)

        def edit(doc: Any) -> None:
            from ruamel.yaml.comments import CommentedMap

            nodes = doc.setdefault("nodes", CommentedMap())
            if name in nodes and isinstance(nodes[name], dict):
                _sync(nodes[name], node)
            else:
                nodes[name] = node

        self._transaction({path: edit}, f"chore: update node '{name}'")
        return self.commit_sha(self.pipelines_dir)

    def delete_node(self, name: str, expected_sha: Optional[str] = None) -> str:
        owner = self.pipeline_of(name)
        if owner is None:
            raise NodeNotFoundError(f"Node '{name}' not found", detail={"name": name})
        path = self.pipeline_path(owner)
        validate_version(self.repo_root, self.pipelines_dir, expected_sha)
        self._transaction(
            {path: lambda doc: doc["nodes"].pop(name)}, f"chore: delete node '{name}'"
        )
        return self.commit_sha(self.pipelines_dir)

    def _to_v2_node(self, name: str, spec: Dict[str, Any], project: Project) -> Dict[str, Any]:
        from ducta.setting.project_decompile import _decompile_node, _producers

        nodes = copy.deepcopy(compile_project(project)["nodes_config"])
        nodes[name] = spec
        problems: List[str] = []
        node = _decompile_node(name, dict(spec), _producers(nodes), problems)
        if problems:
            raise ValidationError(
                f"Node '{name}' cannot be stored in format 2", detail={"problems": problems}
            )
        # A client that read the node back gets the catalog contracts of its
        # inputs compiled into sanity_checks.inputs; storing them again as
        # node-level input_checks would duplicate the contract, not change it.
        sent = ((spec.get("sanity_checks") or {}).get("inputs")) or {}
        for ds in list(node.get("input_checks", {})):
            entry = project.catalog.get(ds)
            if (
                entry is not None
                and entry.quality is not None
                and sent.get(ds) == _checks(entry.quality, "gate")
            ):
                node["input_checks"].pop(ds)
        if not node.get("input_checks"):
            node.pop("input_checks", None)
        return node

    # ── pipeline writes ──────────────────────────────────────────────────────

    def save_pipeline(
        self, name: str, spec: Dict[str, Any], expected_sha: Optional[str] = None
    ) -> str:
        project = self.project()
        listed = [
            str(m)
            for m in (
                n if isinstance(n, str) else (n or {}).get("name") for n in spec.get("nodes") or []
            )
            if m
        ]
        current = project.pipelines.get(name)
        current_nodes = list(current.nodes) if current else []
        problems = []
        for node in listed:
            owner = self.pipeline_of(node, project)
            if owner is None:
                problems.append(
                    f"node '{node}' does not exist — create it in this pipeline first "
                    f"(PUT /nodes/{node}?pipeline={name})"
                )
            elif owner != name:
                problems.append(
                    f"node '{node}' belongs to pipeline '{owner}'; in format 2 a node "
                    "belongs to one pipeline"
                )
        removed = [n for n in current_nodes if n not in listed]
        if removed:
            problems.append(
                f"removing {removed} from the pipeline would delete their definitions in "
                "format 2 — delete the node(s) explicitly (DELETE /nodes/{name})"
            )
        unknown = sorted(set(spec) - set(_PIPELINE_KEYS) - {"nodes", "name", "inputs", "outputs"})
        if unknown:
            problems.append(f"{unknown} are not pipeline settings")
        if problems:
            raise ValidationError(
                f"Pipeline '{name}' cannot be saved", detail={"problems": problems}
            )

        desired = {k: copy.deepcopy(spec[k]) for k in _PIPELINE_KEYS if spec.get(k) is not None}
        path = self.pipeline_path(name)
        validate_version(self.repo_root, self.pipelines_dir, expected_sha)

        def edit(doc: Any) -> None:
            from ruamel.yaml.comments import CommentedMap

            nodes = doc.get("nodes") if isinstance(doc.get("nodes"), dict) else CommentedMap()
            for key in [k for k in doc if k != "nodes" and k not in desired]:
                del doc[key]
            for key, value in desired.items():
                if key not in doc or _plain(doc[key]) != value:
                    doc[key] = value
            if "nodes" in doc:
                del doc["nodes"]
            _reorder(nodes, listed)
            doc["nodes"] = nodes  # nodes last, after the pipeline settings

        self._transaction({path: edit}, f"chore: update pipeline '{name}'")
        return self.commit_sha(self.pipelines_dir)

    def delete_pipeline(self, name: str, expected_sha: Optional[str] = None) -> str:
        project = self.project()
        if name not in project.pipelines:
            raise PipelineNotFoundError(f"Pipeline '{name}' not found", detail={"pipeline": name})
        path = self.pipeline_path(name)
        validate_version(self.repo_root, self.pipelines_dir, expected_sha)
        self._transaction({}, f"chore: delete pipeline '{name}'", deletes=[path])
        return self.commit_sha(self.pipelines_dir)

    # ── canvas edits ─────────────────────────────────────────────────────────

    def apply_pipeline_ops(
        self,
        name: str,
        ops: List[Dict[str, Any]],
        expected_sha: Optional[str] = None,
        new_datasets: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> "tuple[str, List[Dict[str, Any]]]":
        """Apply the canvas's operations to one pipeline file, plus any datasets
        they create, in one validated transaction. Returns the new version and
        the inverse operations (undo order)."""
        from ducta.api.repositories.pipeline_ops import OpError, apply_ops

        project = self.project()
        if name not in project.pipelines:
            raise PipelineNotFoundError(f"Pipeline '{name}' not found", detail={"pipeline": name})
        validate_version(self.repo_root, self.pipelines_dir, expected_sha)
        path = self.pipeline_path(name)
        inverses: List[Dict[str, Any]] = []

        def edit(doc: Any) -> None:
            try:
                inverses.extend(apply_ops(doc, ops))
            except OpError as e:
                raise ValidationError(str(e), detail={"ops": ops}) from e

        edits: Dict[Path, Callable[[Any], None]] = {path: edit}
        for target, entries in self._new_dataset_files(
            {k: v for k, v in (new_datasets or {}).items() if k not in project.catalog}
        ).items():
            edits[target] = _add_entries(entries)
        self._transaction(edits, f"canvas: {len(ops)} edit(s) to pipeline '{name}'")
        return self.commit_sha(self.pipelines_dir), inverses

    # ── node templates ───────────────────────────────────────────────────────

    #: What stays on the instance when a node becomes a template: its wiring.
    _INSTANCE_KEYS = ("inputs", "outputs", "depends_on")

    def extract_node_template(
        self,
        pipeline: str,
        node: str,
        template: str,
        params: Iterable[str] = (),
        expected_sha: Optional[str] = None,
    ) -> Path:
        """Move a node's configuration to ``templates/nodes/<template>.yaml`` and
        make the node ``use`` it (ADR 0001 §3). The node's wiring stays on the
        instance; each key in *params* becomes a parameter, its current value the
        instance's ``with``. Both files change in one validated transaction."""
        import re

        from ruamel.yaml.comments import CommentedMap

        from ducta.setting.project_defaults import NODE_TEMPLATES_DIR

        if not re.fullmatch(r"[A-Za-z_][\w-]*", template or ""):
            raise ValidationError(
                "A template name is letters, digits, '_' and '-'", detail={"template": template}
            )
        project = self.project()
        if pipeline not in project.pipelines:
            raise PipelineNotFoundError(
                f"Pipeline '{pipeline}' not found", detail={"pipeline": pipeline}
            )
        validate_version(self.repo_root, self.pipelines_dir, expected_sha)
        target = self.root / NODE_TEMPLATES_DIR / f"{template}.yaml"
        if target.exists() or target.with_suffix(".yml").exists():
            raise ValidationError(
                f"There is already a template '{template}'", detail={"template": template}
            )
        path = self.pipeline_path(pipeline)
        params = list(params)
        body: Dict[str, Any] = {}

        def rewrite(doc: Any) -> None:
            nodes = doc.get("nodes") if isinstance(doc, dict) else None
            if not isinstance(nodes, dict) or node not in nodes:
                raise ValidationError(f"Node '{node}' is not written in {path.name}")
            spec = nodes[node]
            if not isinstance(spec, dict) or "use" in spec:
                raise ValidationError(f"Node '{node}' already uses a template")
            missing = [k for k in params if k not in spec or k in self._INSTANCE_KEYS]
            if missing:
                raise ValidationError(
                    f"Not a key of the node's configuration: {', '.join(missing)}",
                    detail={"params": missing},
                )
            for key, value in spec.items():
                if key not in self._INSTANCE_KEYS:
                    body[key] = f"${{params.{key}}}" if key in params else value
            instance = CommentedMap()
            instance["use"] = template
            if params:
                instance["with"] = CommentedMap((k, spec[k]) for k in params)
            for key in self._INSTANCE_KEYS:
                if key in spec:
                    instance[key] = spec[key]
            nodes[node] = instance

        def write_template(doc: Any) -> None:
            if body.get("description"):
                doc["description"] = body["description"]
            if params:
                doc["params"] = CommentedMap((k, CommentedMap(type="any")) for k in params)
            doc["node"] = CommentedMap(body)

        made_dir = not target.parent.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Ordered: the node is read before the template is written.
            self._transaction(
                {path: rewrite, target: write_template},
                f"extract node '{node}' of '{pipeline}' to template '{template}'",
            )
        except Exception:
            if made_dir and not any(target.parent.iterdir()):
                target.parent.rmdir()
            raise
        return target

    def extract_subpipeline(
        self,
        pipeline: str,
        nodes: Iterable[str],
        template: str,
        expected_sha: Optional[str] = None,
    ) -> Path:
        """Move *nodes* of *pipeline* into ``templates/pipelines/<template>.yaml``
        and put one ``use: pipeline:<template>`` node in their place.

        The nodes keep their names and datasets (the catalog does not move), so
        the expanded pipeline is the same one — history and certificates still
        match. Make it reusable afterwards by turning names into ``${params.x}``.
        """
        import re

        from ruamel.yaml.comments import CommentedMap

        from ducta.setting.project_defaults import PIPELINE_TEMPLATES_DIR

        if not re.fullmatch(r"[A-Za-z_][\w-]*", template or ""):
            raise ValidationError(
                "A subpipeline name is letters, digits, '_' and '-'", detail={"template": template}
            )
        nodes = list(dict.fromkeys(nodes))
        if len(nodes) < 1:
            raise ValidationError("Pick the nodes to extract")
        project = self.project()
        if pipeline not in project.pipelines:
            raise PipelineNotFoundError(
                f"Pipeline '{pipeline}' not found", detail={"pipeline": pipeline}
            )
        validate_version(self.repo_root, self.pipelines_dir, expected_sha)
        target = self.root / PIPELINE_TEMPLATES_DIR / f"{template}.yaml"
        if target.exists() or target.with_suffix(".yml").exists():
            raise ValidationError(
                f"There is already a subpipeline '{template}'", detail={"template": template}
            )
        path = self.pipeline_path(pipeline)
        moved: Dict[str, Any] = {}

        def rewrite(doc: Any) -> None:
            written = doc.get("nodes") if isinstance(doc, dict) else None
            if not isinstance(written, dict):
                raise ValidationError(f"{path.name} has no nodes")
            missing = [n for n in nodes if n not in written]
            if missing:
                raise ValidationError(
                    f"Not written in {path.name}: {', '.join(missing)}", detail={"nodes": missing}
                )
            if template in written and template not in nodes:
                raise ValidationError(f"The pipeline already has a node named '{template}'")
            rebuilt = CommentedMap()
            for name, spec in written.items():
                if name in nodes:
                    moved[name] = spec
                    if template not in rebuilt:
                        rebuilt[template] = CommentedMap(use=f"pipeline:{template}")
                else:
                    rebuilt[name] = spec
            doc["nodes"] = rebuilt

        def write_template(doc: Any) -> None:
            doc["description"] = f"Extracted from {pipeline}: {', '.join(nodes)}"
            doc["nodes"] = CommentedMap(moved)

        made_dir = not target.parent.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._transaction(
                {path: rewrite, target: write_template},
                f"extract {len(nodes)} node(s) of '{pipeline}' to subpipeline '{template}'",
            )
        except Exception:
            if made_dir and not any(target.parent.iterdir()):
                target.parent.rmdir()
            raise
        return target

    # ── a file as text (the editor's YAML) ───────────────────────────────────

    def write_text(self, path: Path, content: str, expected_version: Optional[str] = None) -> str:
        """Replace one project file's text and keep it unless it makes the project
        worse; returns the file's new version.

        A valid project must stay valid in every environment. A project that is
        already broken accepts any write that does not add problems — so it can
        be fixed one file, one error, at a time. The YAML lens edits the file
        people also edit by hand, comments and all: it is written as given.
        """
        path = Path(path)
        if self.root.resolve() not in path.resolve().parents:
            raise ValidationError("The file is outside the project", detail={"path": str(path)})
        validate_version(self.repo_root, path, expected_version)
        before = self._config_problems()
        original = path.read_text(encoding="utf-8") if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        try:
            after = self._config_problems()
        except Exception:
            self._restore(path, original)
            raise
        if after and len(after) > len(before):
            self._restore(path, original)
            from ducta.setting.problems import parse_problems

            raise ValidationError(
                "The change would leave the project invalid",
                detail={"problems": after, "items": [p.to_dict() for p in parse_problems(after)]},
            )
        logger.info("format-2 write: {}", path.name)
        return content_version(path)

    def _config_problems(self) -> List[str]:
        """Every loader problem, in every environment ([] when the project is valid)."""
        try:
            project = validate_project(self.root)
            for env in project.project.environments:
                validate_project(self.root, env)
        except ProjectConfigError as e:
            return list(e.problems)
        return []

    @staticmethod
    def _restore(path: Path, original: Optional[str]) -> None:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(original, encoding="utf-8")

    # ── whole-document writes (API `configs` routes) ─────────────────────────

    def save_document(
        self,
        doc_name: str,
        data: Dict[str, Any],
        env: str = "base",
        expected_sha: Optional[str] = None,
    ) -> str:
        """Replace one engine document for ``env`` and store it as project files.

        The result is verified: the project, compiled for
        ``env``, must be equivalent to the documents the client sent, or
        nothing is kept.
        """
        from ducta.setting.project_decompile import _SAME, _diff, canonical, decompile

        if doc_name not in _DOC_KEYS:
            raise ConfigFileNotFoundError(
                f"Config '{doc_name}' does not exist", detail={"name": doc_name}
            )
        base_env = env in (None, "base")
        intended = {
            v: copy.deepcopy(d) for v, d in zip(_DOC_KEYS.values(), self.documents(env).values())
        }
        intended[_DOC_KEYS[doc_name]] = copy.deepcopy(data)
        project = self.project()
        problems: List[str] = []
        notes: List[str] = []
        tree = decompile(intended, project.project.project, problems, notes)
        if problems:
            raise ValidationError(
                f"'{doc_name}' cannot be stored in format 2",
                detail={"problems": sorted(set(problems))},
            )
        project_path = self.root / PROJECT_FILE
        edits: Dict[Path, Callable[[Any], None]] = {}
        deletes: List[Path] = []
        validate_version(self.repo_root, self.file_for(doc_name), expected_sha)

        if base_env:
            located = read_project(self.root)
            project_tree, file_profiles = _split_profiles(
                tree, _load_rt(project_path), located.profiles_file is not None
            )

            def edit_project(doc: Any) -> None:
                for key in ("project", "paths", "settings", "metadata"):
                    if key in project_tree:
                        if isinstance(doc.get(key), dict) and isinstance(project_tree[key], dict):
                            _sync(doc[key], project_tree[key])
                        else:
                            doc[key] = project_tree[key]
                    elif key in doc and key != "project":
                        del doc[key]

            if located.profiles_file is not None:
                edits[located.profiles_file] = lambda doc: _sync(doc, file_profiles)
            edits[project_path] = edit_project
            catalog_edits, catalog_deletes = self._catalog_edits(tree["catalog"])
            edits.update(catalog_edits)
            existing = set(project.pipelines)
            for pname, pdoc in tree["pipelines"].items():
                edits[self.pipeline_path(pname)] = _pipeline_sync(pdoc)
            deletes = [self.pipeline_path(p) for p in existing - set(tree["pipelines"])]
            deletes += catalog_deletes
        else:
            base_docs = compile_project(project)
            base_tree = decompile(base_docs, project.project.project, [], [])
            diff_problems: List[str] = []
            sections = ("settings", "paths", "catalog", "pipelines")
            override = _diff(
                {k: base_tree[k] for k in sections if k in base_tree},
                {k: tree[k] for k in sections if k in tree},
                diff_problems,
                "",
            )
            if diff_problems:
                raise ValidationError(
                    f"The '{env}' {doc_name} cannot be expressed as an override",
                    detail={"problems": diff_problems},
                )

            def edit_env(doc: Any) -> None:
                from ruamel.yaml.comments import CommentedMap

                envs = doc.setdefault("environments", CommentedMap())
                if override is _SAME:
                    envs.pop(env, None)
                elif isinstance(envs.get(env), dict):
                    _sync(envs[env], override)
                else:
                    envs[env] = override
                if not envs:
                    del doc["environments"]

            edits[project_path] = edit_env

        def verify() -> None:
            after = compile_project(validate_project(self.root, None if base_env else env))
            from ducta.setting.project_decompile import _first_difference

            diff = _first_difference(canonical(intended), canonical(after))
            if diff:
                raise ValidationError(
                    f"'{doc_name}' would not be stored faithfully in format 2",
                    detail={"problems": [diff]},
                )

        self._transaction(
            edits, f"chore: update {doc_name} config for env={env}", deletes=deletes, verify=verify
        )
        return self.commit_sha(self.file_for(doc_name))

    def _new_dataset_files(
        self, new: Dict[str, Dict[str, Any]]
    ) -> Dict[Path, Dict[str, Dict[str, Any]]]:
        """Where each new dataset is declared: the single catalog file, or with a
        ``catalog/`` folder ``catalog/<layer>.yaml`` — the same rule as
        :meth:`_catalog_edits`. Existing entries are not touched."""
        out: Dict[Path, Dict[str, Dict[str, Any]]] = {}
        single = None if catalog_dir_files(self.root) else catalog_location(self.root)
        for name, entry in new.items():
            layer = name.split(".", 1)[0] if "." in name else "sources"
            target = single or self.root / CATALOG_DIR / f"{layer}.yaml"
            out.setdefault(target, {})[name] = dict(entry or {})
        return out

    def _catalog_edits(
        self, desired: Dict[str, Any]
    ) -> "tuple[Dict[Path, Callable[[Any], None]], List[Path]]":
        """How to write ``desired`` back to the catalog, file by file.

        A single ``catalog.*`` is synced as a whole. With a ``catalog/`` folder each
        dataset stays in the file that declares it; a new one goes to
        ``catalog/<layer>.yaml`` (the first part of its name, ``sources`` when it has
        none); a file left without datasets is deleted.
        """
        located = read_project(self.root)
        if not catalog_dir_files(self.root):
            single = catalog_location(self.root)
            return {single: _pipeline_sync(desired)}, []
        target: Dict[str, Path] = {}
        for name in desired:
            layer = name.split(".", 1)[0] if "." in name else "sources"
            target[name] = located.catalog_files.get(
                name, self.root / CATALOG_DIR / f"{layer}.yaml"
            )
        files = set(target.values()) | set(located.catalog_files.values())
        edits: Dict[Path, Callable[[Any], None]] = {}
        deletes: List[Path] = []
        for path in sorted(files):
            subset = {n: desired[n] for n in desired if target[n] == path}
            if subset:
                edits[path] = _pipeline_sync(subset)
            else:
                deletes.append(path)
        return edits, deletes

    # ── transaction ──────────────────────────────────────────────────────────

    def _transaction(
        self,
        edits: Dict[Path, Callable[[Any], None]],
        message: str,
        deletes: Iterable[Path] = (),
        verify: Optional[Callable[[], None]] = None,
    ) -> None:
        deletes = list(deletes)
        touched = [*edits, *deletes]
        originals = {p: (p.read_text(encoding="utf-8") if p.exists() else None) for p in touched}
        try:
            for path, edit in edits.items():
                doc = _load_rt(path)
                edit(doc)
                _dump_rt(path, doc)
            for path in deletes:
                if path.exists():
                    path.unlink()
            project = validate_project(self.root)
            for env in project.project.environments:
                validate_project(self.root, env)
            if verify is not None:
                verify()
        except Exception as e:
            for path, text in originals.items():
                if text is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(text, encoding="utf-8")
            if isinstance(e, ProjectConfigError):
                from ducta.setting.problems import parse_problems

                raise ValidationError(
                    "The change would leave the project invalid",
                    detail={
                        "problems": e.problems,
                        "items": [p.to_dict() for p in parse_problems(e.problems)],
                    },
                ) from e
            raise
        # Written and validated; committing is the user's call (the Changes
        # panel, or git itself). `message` describes the change in the log.
        logger.info("format-2 write: {}", message)


def _add_entries(entries: Dict[str, Dict[str, Any]]) -> Callable[[Any], None]:
    """Add top-level entries to a catalog document, leaving the rest as written."""

    def edit(doc: Any) -> None:
        from ruamel.yaml.comments import CommentedMap

        for name, entry in entries.items():
            doc[name] = CommentedMap(entry)

    return edit


def _pipeline_sync(desired: Dict[str, Any]) -> Callable[[Any], None]:
    def edit(doc: Any) -> None:
        _sync(doc, desired)

    return edit


def workspace_stores(root: Path) -> List[V2ProjectStore]:
    """The projects of a workspace: the workspace itself, and/or ``projects/*``."""
    root = Path(root)
    stores: List[V2ProjectStore] = []
    own = find_project_root(root)
    if own is not None:
        stores.append(V2ProjectStore(own, root))
    projects = root / "projects"
    if projects.is_dir():
        for directory in sorted(p for p in projects.iterdir() if p.is_dir()):
            found = find_project_root(directory)
            if found is not None:
                stores.append(V2ProjectStore(found, root))
    return stores
