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
project in every environment, and only then commit. A write that would leave
the project invalid — or that format 2 cannot express — is rejected with the
reason, and the files are restored.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from loguru import logger

from ducta.api.exceptions import (
    ConfigFileNotFoundError,
    NodeNotFoundError,
    PipelineNotFoundError,
    ValidationError,
)
from ducta.api.utils.git_utils import commit_files, file_commit_sha, validate_occ
from ducta.setting.project_loader import (
    CATALOG_FILE,
    PIPELINES_DIR,
    PROJECT_FILE,
    Project,
    ProjectConfigError,
    _checks,
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


def _yaml() -> Any:
    from ruamel.yaml import YAML

    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=2, offset=0)
    y.width = 100
    return y


def _load_rt(path: Path) -> Any:
    from ruamel.yaml.comments import CommentedMap

    if not path.exists():
        return CommentedMap()
    data = _yaml().load(path.read_text(encoding="utf-8"))
    return data if data is not None else CommentedMap()


def _dump_rt(path: Path, data: Any) -> None:
    import io

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    _yaml().dump(data, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


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
        #: Git root for OCC and commits (the workspace; defaults to the project).
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
        """The OCC unit for nodes and pipelines: clients' commit SHAs cover this folder."""
        return self.root / PIPELINES_DIR

    def pipeline_path(self, name: str) -> Path:
        return read_project(self.root).pipeline_files.get(
            name, self.root / PIPELINES_DIR / f"{name}.yaml"
        )

    def file_for(self, doc_name: str) -> Path:
        if doc_name not in DOC_FILES:
            raise ConfigFileNotFoundError(
                f"Config '{doc_name}' does not exist", detail={"name": doc_name}
            )
        return self.root / DOC_FILES[doc_name]

    def commit_sha(self, path: Path) -> str:
        return file_commit_sha(self.repo_root, path)

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
        validate_occ(self.repo_root, self.pipelines_dir, expected_sha)

        def edit(doc: Any) -> None:
            from ruamel.yaml.comments import CommentedMap

            nodes = doc.setdefault("nodes", CommentedMap())
            if name in nodes and isinstance(nodes[name], dict):
                _sync(nodes[name], node)
            else:
                nodes[name] = node

        return self._transaction({path: edit}, f"chore: update node '{name}'")

    def delete_node(self, name: str, expected_sha: Optional[str] = None) -> str:
        owner = self.pipeline_of(name)
        if owner is None:
            raise NodeNotFoundError(f"Node '{name}' not found", detail={"name": name})
        path = self.pipeline_path(owner)
        validate_occ(self.repo_root, self.pipelines_dir, expected_sha)
        return self._transaction(
            {path: lambda doc: doc["nodes"].pop(name)}, f"chore: delete node '{name}'"
        )

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
                and entry.checks is not None
                and sent.get(ds) == _checks(entry.checks, "gate")
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
        validate_occ(self.repo_root, self.pipelines_dir, expected_sha)

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

        return self._transaction({path: edit}, f"chore: update pipeline '{name}'")

    def delete_pipeline(self, name: str, expected_sha: Optional[str] = None) -> str:
        project = self.project()
        if name not in project.pipelines:
            raise PipelineNotFoundError(f"Pipeline '{name}' not found", detail={"pipeline": name})
        path = self.pipeline_path(name)
        validate_occ(self.repo_root, self.pipelines_dir, expected_sha)
        return self._transaction({}, f"chore: delete pipeline '{name}'", deletes=[path])

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
        catalog_path = self.root / CATALOG_FILE
        edits: Dict[Path, Callable[[Any], None]] = {}
        deletes: List[Path] = []
        validate_occ(self.repo_root, self.file_for(doc_name), expected_sha)

        if base_env:

            def edit_project(doc: Any) -> None:
                for key in ("project", "paths", "settings", "metadata"):
                    if key in tree:
                        if isinstance(doc.get(key), dict) and isinstance(tree[key], dict):
                            _sync(doc[key], tree[key])
                        else:
                            doc[key] = tree[key]
                    elif key in doc and key != "project":
                        del doc[key]

            edits[project_path] = edit_project
            edits[catalog_path] = lambda doc: _sync(doc, tree["catalog"])
            existing = set(project.pipelines)
            for pname, pdoc in tree["pipelines"].items():
                edits[self.pipeline_path(pname)] = _pipeline_sync(pdoc)
            deletes = [self.pipeline_path(p) for p in existing - set(tree["pipelines"])]
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

        return self._transaction(
            edits, f"chore: update {doc_name} config for env={env}", deletes=deletes, verify=verify
        )

    # ── transaction ──────────────────────────────────────────────────────────

    def _transaction(
        self,
        edits: Dict[Path, Callable[[Any], None]],
        message: str,
        deletes: Iterable[Path] = (),
        verify: Optional[Callable[[], None]] = None,
    ) -> str:
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
                raise ValidationError(
                    "The change would leave the project invalid", detail={"problems": e.problems}
                ) from e
            raise
        logger.info("format-2 write: {}", message)
        return _commit(
            self.repo_root, [p for p in touched if p.exists()], [p for p in deletes], message
        )


def _pipeline_sync(desired: Dict[str, Any]) -> Callable[[Any], None]:
    def edit(doc: Any) -> None:
        _sync(doc, desired)

    return edit


def _commit(root: Path, changed: List[Path], deleted: List[Path], message: str) -> str:
    """Commit edits and deletions (``commit_files`` only stages additions)."""
    if deleted:
        try:
            from ducta.api.utils.git_utils import GIT_AVAILABLE, get_repo, is_git_repo
            from ducta.api.utils.platform_utils import posix_relative

            if GIT_AVAILABLE and is_git_repo(root):
                repo = get_repo(root)
                tracked = [posix_relative(p, root) for p in deleted]
                repo.index.remove(tracked, working_tree=False)
        except Exception as e:  # noqa: BLE001 — the commit below still records the rest
            logger.warning("Could not stage deletion of {}: {}", deleted, e)
    return commit_files(root, changed, message) if changed or deleted else ""


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
