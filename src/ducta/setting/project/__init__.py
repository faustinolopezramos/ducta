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

Ducta Format-2 Project subsystem: loaders, schemas, defaults, inspection and decompilation.
"""

from __future__ import annotations

from ducta.setting.project import context, defaults, files, inspect, loader, schema
from ducta.setting.project import decompile as decompile_module
from ducta.setting.project.context import (
    find_nearest_project,
    load_project_context,
)
from ducta.setting.project.decompile import (
    canonical,
    decompile,
    write_schemas,
)
from ducta.setting.project.defaults import (
    NODE_TEMPLATES_DIR,
    PIPELINE_TEMPLATES_DIR,
    REQUIRED,
    apply_defaults,
    node_template_names,
    pipeline_template_names,
    resolve_extends,
    resolve_node_templates,
    resolve_pipeline_uses,
)
from ducta.setting.project.files import (
    SUFFIXES,
    Where,
    find_files,
    format_of,
    index,
    load,
    parse,
    with_a_suffix,
)
from ducta.setting.project.inspect import (
    Explanation,
    Layer,
    convert_project,
    diff_trees,
    dump,
    explain,
    ml_plan,
    resolved_tree,
)
from ducta.setting.project.loader import (
    CATALOG_DIR,
    CATALOG_FILE,
    PIPELINES_DIR,
    PROFILES_STEM,
    PROJECT_FILE,
    QUALITY_DIR,
    Project,
    ProjectConfigError,
    apply_environment,
    catalog_dir_files,
    catalog_location,
    compile_project,
    environment_overrides,
    find_project_root,
    load_context_quality_extensions,
    load_project,
    load_project_v2,
    project_file,
    project_tree,
    read_project,
    resolve_path,
    validate_project,
    visible_in,
)
from ducta.setting.project.schema import (
    ALERT_EVENTS,
    BUILTIN_SCORER,
    DATASET_ENGINE_KEYS,
    PROJECT_FORMAT_VERSION,
    AIPolicy,
    AlertChannel,
    AlertRule,
    CatalogEntry,
    ChecksBlock,
    GateSpec,
    Governance,
    GovernanceWarnings,
    Incremental,
    IngestNode,
    IngestSpec,
    MergeSpec,
    ModelRef,
    Node,
    Paths,
    PipelineDefaults,
    PipelineFile,
    ProjectDefaults,
    ProjectFile,
    ReadSpec,
    SentinelPolicy,
    SentinelPropose,
    SentinelRetry,
    SentinelWait,
    StreamingSpec,
    StreamInput,
    StreamNode,
    StreamOutput,
    StreamSpec,
    StreamTransform,
    TransformNode,
    Watermark,
    WriteSpec,
    check_metadata,
    json_schema,
)

__all__ = [
    # Submodules
    "context",
    "decompile_module",
    "defaults",
    "files",
    "inspect",
    "loader",
    "schema",
    # context
    "find_nearest_project",
    "load_project_context",
    # decompile
    "canonical",
    "decompile",
    "write_schemas",
    # defaults
    "NODE_TEMPLATES_DIR",
    "PIPELINE_TEMPLATES_DIR",
    "REQUIRED",
    "apply_defaults",
    "node_template_names",
    "pipeline_template_names",
    "resolve_extends",
    "resolve_node_templates",
    "resolve_pipeline_uses",
    # files
    "SUFFIXES",
    "Where",
    "find_files",
    "format_of",
    "index",
    "load",
    "parse",
    "with_a_suffix",
    # inspect
    "Explanation",
    "Layer",
    "convert_project",
    "diff_trees",
    "dump",
    "explain",
    "ml_plan",
    "resolved_tree",
    # loader
    "CATALOG_DIR",
    "CATALOG_FILE",
    "PIPELINES_DIR",
    "PROFILES_STEM",
    "PROJECT_FILE",
    "QUALITY_DIR",
    "Project",
    "ProjectConfigError",
    "apply_environment",
    "catalog_dir_files",
    "catalog_location",
    "compile_project",
    "environment_overrides",
    "find_project_root",
    "load_context_quality_extensions",
    "load_project",
    "load_project_v2",
    "project_file",
    "project_tree",
    "read_project",
    "resolve_path",
    "validate_project",
    "visible_in",
    # schema
    "ALERT_EVENTS",
    "BUILTIN_SCORER",
    "DATASET_ENGINE_KEYS",
    "PROJECT_FORMAT_VERSION",
    "AIPolicy",
    "AlertChannel",
    "AlertRule",
    "CatalogEntry",
    "ChecksBlock",
    "GateSpec",
    "Governance",
    "GovernanceWarnings",
    "Incremental",
    "IngestNode",
    "IngestSpec",
    "MergeSpec",
    "ModelRef",
    "Node",
    "Paths",
    "PipelineDefaults",
    "PipelineFile",
    "ProjectDefaults",
    "ProjectFile",
    "ReadSpec",
    "SentinelPolicy",
    "SentinelPropose",
    "SentinelRetry",
    "SentinelWait",
    "StreamingSpec",
    "StreamInput",
    "StreamNode",
    "StreamOutput",
    "StreamSpec",
    "StreamTransform",
    "TransformNode",
    "Watermark",
    "WriteSpec",
    "check_metadata",
    "json_schema",
]
