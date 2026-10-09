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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ducta.api.models.dataset import (
    DatasetEndpoint,
    DatasetListResponse,
    DatasetRef,
    DatasetResponse,
    medallion_layer,
)
from ducta.api.repositories.dataset_repository import DatasetRepository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from ducta.api.services.node_service import NodeService
    from ducta.api.services.project import ProjectService


def io_names(value: Any) -> List[str]:
    """Normalize a node spec's ``input``/``output``/``dependencies`` to names."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(k) for k in value.keys()]
    if isinstance(value, (list, tuple)):
        names: List[str] = []
        for entry in value:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("id")
                if name:
                    names.append(str(name))
        return names
    return []


def node_io(spec: Dict[str, Any], side: str) -> List[str]:
    """Return a node spec's dataset names for *side* (``"input"``/``"output"``)."""
    plural = f"{side}s"
    value = spec.get(plural)
    if not value:
        value = spec.get(side)
    if side == "input":
        # Inputs as {param: dataset} — alone, or as a list item, which is how
        # the node repository returns a format-2 node's: the datasets are the
        # values, the keys are the function's parameter names.
        if isinstance(value, dict):
            return [str(v) for v in value.values() if isinstance(v, str)]
        if (
            isinstance(value, list)
            and value
            and all(isinstance(e, dict) and not (e.get("name") or e.get("id")) for e in value)
        ):
            return [str(v) for e in value for v in e.values() if isinstance(v, str)]
    return io_names(value)


class DatasetService:
    """Resolves dataset references and assembles the project dataset registry."""

    def __init__(
        self,
        root: "Path",
        project_svc: "ProjectService",
        node_svc: "NodeService",
    ) -> None:
        self._repo = DatasetRepository(root)
        self._project_svc = project_svc
        self._node_svc = node_svc

    # ── Reference resolution ──────────────────────────────────────────────────

    def resolve_ref(
        self,
        name: str,
        side: str,
        *,
        inputs: Optional[Dict[str, Any]] = None,
        outputs: Optional[Dict[str, Any]] = None,
    ) -> DatasetRef:
        """Resolve a single dataset reference into a :class:`DatasetRef`.

        Pass already-loaded *inputs*/*outputs* registries (see
        ``list_for_project``) to avoid re-reading them from disk for every name.
        """
        if inputs is not None and outputs is not None:
            entry = self._repo.resolve_from(name, side, inputs, outputs)
        else:
            entry = self._repo.resolve(name, side)
        if entry is None:
            return DatasetRef(name=name, declared=False, layer=medallion_layer(name))

        fmt = entry.get("format")
        return DatasetRef(
            name=name,
            declared=True,
            format=str(fmt) if fmt else None,
            path=self._entry_path(entry),
            write_mode=self._str_or_none(entry.get("write_mode")),
            schema=self._str_or_none(entry.get("schema") or entry.get("schema_def")),
            layer=medallion_layer(name),
            options=entry.get("options") if isinstance(entry.get("options"), dict) else None,
        )

    def resolve_refs(self, names: List[str], side: str) -> List[DatasetRef]:
        """Resolve every reference in *names*, preserving declaration order."""
        inputs = self._repo.list_inputs()
        outputs = self._repo.list_outputs()
        return [self.resolve_ref(name, side, inputs=inputs, outputs=outputs) for name in names]

    # ── Project registry ──────────────────────────────────────────────────────

    def list_for_project(self, project_id: str) -> DatasetListResponse:
        """Return every dataset a project's pipelines reference or declare."""
        pipelines = self._project_svc.list_project_pipelines(project_id)
        node_specs: Dict[str, Any] = self._node_svc.list_nodes()

        # node name → the first pipeline of this project that declares it
        node_pipeline: Dict[str, str] = {}
        for pipeline_name, spec in pipelines.items():
            if not isinstance(spec, dict):
                continue
            for node_name in io_names(spec.get("nodes")):
                node_pipeline.setdefault(node_name, pipeline_name)

        producers: Dict[str, List[DatasetEndpoint]] = {}
        consumers: Dict[str, List[DatasetEndpoint]] = {}
        referenced: List[str] = []
        seen: set[str] = set()

        def note(name: str) -> None:
            if name not in seen:
                seen.add(name)
                referenced.append(name)

        for node_name, pipeline_name in node_pipeline.items():
            spec = node_specs.get(node_name) or {}
            endpoint = DatasetEndpoint(node=node_name, pipeline=pipeline_name)
            for out in node_io(spec, "output"):
                producers.setdefault(out, []).append(endpoint)
                note(out)
            for inp in node_io(spec, "input"):
                consumers.setdefault(inp, []).append(endpoint)
                note(inp)

        inputs = self._repo.list_inputs()
        outputs = self._repo.list_outputs()
        catalog = self._catalog(project_id)

        datasets: List[DatasetResponse] = []
        for name in sorted(referenced):
            declared_in = [
                side for side, reg in (("input", inputs), ("output", outputs)) if name in reg
            ]
            side = "output" if name in outputs else "input"
            ref = self.resolve_ref(name, side, inputs=inputs, outputs=outputs)
            datasets.append(
                DatasetResponse(
                    name=name,
                    layer=ref.layer,
                    format=ref.format,
                    path=ref.path,
                    write_mode=ref.write_mode,
                    schema=ref.schema_,
                    options=ref.options,
                    declared_in=declared_in,
                    producers=producers.get(name, []),
                    consumers=consumers.get(name, []),
                    description=getattr(catalog.get(name), "description", None),
                    metadata=dict(getattr(catalog.get(name), "metadata", None) or {}),
                )
            )

        return DatasetListResponse(project_id=project_id, datasets=datasets, count=len(datasets))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _catalog(self, project_id: str) -> Dict[str, Any]:
        """The project's catalog entries — description and metadata are not in the engine registry."""
        try:
            return dict(self._project_svc.store(project_id).project().catalog)
        except Exception:  # noqa: BLE001 — a dataset list without metadata beats none
            return {}

    @staticmethod
    def _entry_path(entry: Dict[str, Any]) -> Optional[str]:
        """Read a registry entry's path under any of the keys in use."""
        for key in ("filepath", "path", "file_path"):
            value = entry.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _str_or_none(value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        return str(value)
