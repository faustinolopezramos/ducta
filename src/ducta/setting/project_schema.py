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

Project configuration, format 2 — the single source of truth for its shape.

A project is three kinds of file::

    ducta.yaml            version: 2, project, paths, settings, environments
    catalog.yaml          every dataset, once — inputs and outputs alike
    pipelines/*.yaml      one pipeline per file, with its nodes

Unknown keys are errors, not warnings: in format 1 a misspelled key was kept
"as-is" and ignored, which is how a typo silently changes behaviour. Free-form
data goes under ``metadata``.

The engine does not read these models. ``ducta.setting.project_loader``
compiles them to the five configuration documents the engine has always
consumed, so a project behaves identically in either format.
"""

from __future__ import annotations

import difflib
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJECT_FORMAT_VERSION = 2


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ── ducta.yaml ───────────────────────────────────────────────────────────────


class Paths(_Strict):
    input: str = Field(..., min_length=1, description="Base directory/URI for input data")
    output: str = Field(..., min_length=1, description="Base directory/URI for output data")


class ProjectFile(_Strict):
    """``ducta.yaml``."""

    version: Literal[2] = Field(..., description="Configuration format version")
    project: str = Field(..., min_length=1, description="Project name")
    description: Optional[str] = None
    paths: Paths
    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Engine settings: every global_config key except input_path/output_path "
            "(see `ducta config schema`). Validated against GlobalConfigSchema."
        ),
    )
    environments: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Per-environment overrides, deep-merged over the whole project "
            "(settings, paths, catalog, pipelines). Dotted keys address one value: "
            "'pipelines.etl.nodes.load.quality.gate.max_errors: 0'. Lists replace."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Free-form project metadata; not read by Ducta"
    )

    @field_validator("settings")
    @classmethod
    def _settings_are_known(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        from ducta.setting.schemas import _RUNTIME_GLOBAL_CONFIG_KEYS, GlobalConfigSchema

        reserved = {"input_path": "paths.input", "output_path": "paths.output"}
        for key in value:
            if key in reserved:
                raise ValueError(f"'{key}' is set through '{reserved[key]}', not settings")
            if key == "environments":
                raise ValueError(
                    "settings.environments is format 1; use the top-level 'environments:'"
                )
        known = set(GlobalConfigSchema.model_fields) | set(_RUNTIME_GLOBAL_CONFIG_KEYS)
        known -= set(reserved)
        _reject_unknown(value, known, "settings")
        return value


# ── catalog.yaml ─────────────────────────────────────────────────────────────


class MergeSpec(_Strict):
    keys: List[str] = Field(..., min_length=1)
    when_matched: Union[Literal["update_all", "ignore"], Dict[str, List[str]]] = "update_all"
    when_not_matched: Literal["insert_all", "ignore"] = "insert_all"
    delete_when: Optional[str] = None
    schema_evolution: bool = False


class WriteSpec(_Strict):
    """How a dataset is written, when a node produces it."""

    mode: Optional[Literal["overwrite", "append", "ignore", "error", "merge"]] = Field(
        default=None, description="Default: the writer's default (overwrite)"
    )
    merge: Optional[MergeSpec] = None
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Writer options, when they differ from the reader's 'options'",
    )
    partition: Optional[Union[str, List[str]]] = None
    overwrite_strategy: Optional[Literal["replaceWhere"]] = None
    partition_col: Optional[str] = None
    replace_predicate: Optional[str] = None
    overwrite_schema: Optional[bool] = None

    @model_validator(mode="after")
    def _merge_needs_spec(self) -> "WriteSpec":
        if self.mode == "merge" and self.merge is None:
            raise ValueError("write.mode 'merge' needs write.merge: {keys: [...]}")
        if self.merge is not None and self.mode != "merge":
            raise ValueError("write.merge is only valid with write.mode 'merge'")
        return self


class ReadSpec(_Strict):
    """Time travel for Delta sources."""

    version: Optional[int] = Field(default=None, ge=0, description="versionAsOf")
    timestamp: Optional[str] = Field(default=None, description="timestampAsOf")


class Incremental(_Strict):
    column: str = Field(..., min_length=1)


class GateSpec(_Strict):
    """A quality gate: when failing checks stop the pipeline."""

    max_errors: Optional[int] = None
    max_warnings: Optional[int] = None
    min_pass_rate: Optional[float] = None
    required_checks: Optional[List[str]] = None
    score_threshold: Optional[float] = None
    score_weights: Optional[Dict[str, float]] = None
    on_fail: Optional[Literal["skip_downstream", "stop_all", "warn_only"]] = Field(
        default=None, description="What a blocking gate does (format 1: 'behavior')"
    )
    enabled: Optional[bool] = None
    name: Optional[str] = None
    consume_from: Optional[str] = None
    output: Optional[Dict[str, Any]] = None


class ChecksBlock(_Strict):
    """Checks plus the gate that judges them."""

    checks: Dict[str, Any] = Field(default_factory=dict)
    gate: Optional[GateSpec] = None
    enabled: bool = True
    fail_fast: Optional[bool] = None
    profile: Optional[str] = None
    dataset_name: Optional[str] = Field(
        default=None, description="Which output the checks apply to (default: the node's first)"
    )
    output: Optional[Dict[str, Any]] = Field(default=None, description="Quality report output")

    @field_validator("checks")
    @classmethod
    def _shorthand(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        # `not_empty: true` is shorthand for `not_empty: {}`; `false` disables.
        out: Dict[str, Any] = {}
        for name, entry in value.items():
            if entry is True or entry is None:
                out[name] = {}
            elif entry is False:
                out[name] = {"enabled": False}
            elif isinstance(entry, dict):
                out[name] = entry
            else:
                raise ValueError(f"check '{name}': expected a mapping or true/false")
        return out


#: Format-specific dataset keys the engine reads, beyond the named fields
#: below. One list, here, rather than scattered `config.get` calls nobody
#: can enumerate — a key not in it is an error with a suggestion.
DATASET_ENGINE_KEYS = frozenset(
    {
        # Unity Catalog / metastore
        "catalog_name",
        "schema_name",
        "uc_table_mode",
        "optimize",
        "vacuum",
        "vacuum_retention_hours",
        "auto_enable_cdf",
        "partition_filter",
        "partition_columns",
        # file formats
        "file_format",
        "rowTag",
        "json_schema",
        "parse_json",
        # query / JDBC / REST sources
        "query",
        "max_records",
        "url_params",
        "url_param_separator",
        "default_url_params",
        # pandas / pickle
        "use_pandas",
        "to_dataframe",
        "allow_untrusted_pickle",
    }
)


class CatalogEntry(_Strict):
    """One dataset in ``catalog.yaml``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    format: str = Field(..., min_length=1)
    path: Optional[str] = Field(
        default=None,
        description="File/directory/URI. For an output, omit it to use the conventional "
        "<paths.output>/<env>/<schema>/<sub_folder>/<table> derived from a 3-part name.",
    )
    table: Optional[str] = Field(default=None, description="Catalog table name")
    description: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    schema_def: Optional[str] = Field(default=None, alias="schema")
    incremental: Optional[Incremental] = None
    read: Optional[ReadSpec] = None
    write: Optional[WriteSpec] = None
    checks: Optional[ChecksBlock] = Field(
        default=None,
        description="Contract: validated whenever a node reads this dataset",
    )

    @model_validator(mode="after")
    def _extras_are_engine_keys(self) -> "CatalogEntry":
        extras = dict(self.model_extra or {})
        known = set(DATASET_ENGINE_KEYS)
        _reject_unknown(extras, known, "dataset", named=set(type(self).model_fields) | {"schema"})
        return self


# ── pipelines/*.yaml ─────────────────────────────────────────────────────────


class _NodeBase(_Strict):
    description: Optional[str] = None
    outputs: List[str] = Field(default_factory=list)
    after: List[str] = Field(
        default_factory=list,
        description="Nodes to run first when no dataset connects them (data edges are inferred)",
    )
    retry: int = Field(default=0, ge=0, le=10)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    quality: Optional[ChecksBlock] = Field(
        default=None, description="Checks on this node's outputs, and their gate"
    )
    on_missing_input: Optional[Literal["skip", "fail"]] = None
    fail_fast: Optional[bool] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TransformNode(_NodeBase):
    kind: Literal["transform"] = "transform"
    run: str = Field(..., description="'package.module:function'")
    inputs: Union[Dict[str, str], List[str]] = Field(
        default_factory=list,
        description="{parameter: dataset} (preferred) or [dataset, ...] passed positionally",
    )
    input_checks: Dict[str, ChecksBlock] = Field(
        default_factory=dict,
        description="Checks on one input, for this node only (catalog 'checks' apply everywhere)",
    )
    run_in_process: bool = False
    execution_mode: Optional[str] = None
    execution_mode_max_rows: Optional[int] = None
    ml_stage: Optional[str] = None
    split: Optional[Dict[str, Any]] = None
    hyperparams: Optional[Dict[str, Any]] = None
    model_version: Optional[str] = None
    metrics: Optional[Any] = None

    @field_validator("run")
    @classmethod
    def _run_is_module_function(cls, value: str) -> str:
        module, sep, function = value.partition(":")
        if not sep or not module.strip() or not function.strip():
            raise ValueError(f"run must be 'module:function', got {value!r}")
        return value


class IngestSpec(_Strict):
    source: Optional[str] = None
    sources: Optional[str] = None
    table: Optional[str] = None
    query: Optional[str] = None
    columns: Optional[List[str]] = None
    where: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class IngestNode(_NodeBase):
    kind: Literal["ingest"]
    ingest: IngestSpec


class StreamSpec(_Strict):
    """Structured Streaming node; keys as the streaming engine reads them."""

    model_config = ConfigDict(extra="allow")

    transform: Optional[Any] = Field(
        default=None, description="Registered transform: name or {name, params}"
    )
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    checkpoint_location: Optional[str] = None
    trigger: Optional[Any] = None
    output_mode: Optional[str] = None
    watermark: Optional[Any] = None
    query_name: Optional[str] = None


class StreamNode(_NodeBase):
    kind: Literal["stream"]
    stream: StreamSpec


Node = Annotated[Union[TransformNode, IngestNode, StreamNode], Field(discriminator="kind")]


class PipelineFile(_Strict):
    """``pipelines/<name>.yaml``. The pipeline's name is the file's stem."""

    description: Optional[str] = None
    type: Literal["batch", "ml", "hybrid", "streaming"] = "batch"
    requires_dates: bool = True
    depends_on: List[str] = Field(
        default_factory=list, description="Pipelines to run before this one (chains)"
    )
    reuse_if_materialized: Optional[bool] = None
    spark_config: Optional[Dict[str, Any]] = None
    split: Optional[Dict[str, Any]] = None
    hyperparams: Optional[Dict[str, Any]] = None
    hyperparams_config: Optional[Union[str, Dict[str, Any]]] = None
    model_version: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # May be empty: the API creates a pipeline, then adds nodes to it. Running
    # an empty pipeline still fails preflight, as in format 1.
    nodes: Dict[str, Node] = Field(default_factory=dict)

    @field_validator("nodes", mode="before")
    @classmethod
    def _default_kind(cls, value: Any) -> Any:
        # `kind` defaults to transform; pydantic's discriminated unions need it
        # present, so fill it in before validation.
        if isinstance(value, dict):
            return {
                name: (
                    {"kind": "transform", **node}
                    if isinstance(node, dict) and "kind" not in node
                    else node
                )
                for name, node in value.items()
            }
        return value


# ── helpers ──────────────────────────────────────────────────────────────────


def _reject_unknown(
    values: Dict[str, Any], known: set, where: str, named: Optional[set] = None
) -> None:
    candidates = sorted(known | (named or set()))
    for key in values:
        if key in known:
            continue
        close = difflib.get_close_matches(str(key), candidates, n=1, cutoff=0.75)
        hint = f" — did you mean '{close[0]}'?" if close else ""
        raise ValueError(f"unknown {where} key '{key}'{hint}")


def json_schema() -> Dict[str, Any]:
    """JSON Schema for the three file kinds, for editor autocompletion."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Ducta project configuration (format 2)",
        "$defs": {
            "project": ProjectFile.model_json_schema(),
            "catalog": {
                "type": "object",
                "additionalProperties": CatalogEntry.model_json_schema(),
            },
            "pipeline": PipelineFile.model_json_schema(),
        },
    }
