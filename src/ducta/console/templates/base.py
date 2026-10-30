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

What every project template shares: its type, its error and its base class.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from ducta.console.core import ConfigFormat, DuctaError, ExitCode


class TemplateType(Enum):
    """Available template types for project generation."""

    MEDALLION_BASIC = "medallion_basic"
    STREAMING_BASIC = "streaming_basic"
    ML_BASIC = "ml_basic"
    ML_SCORING = "ml_scoring"
    HYBRID_BASIC = "hybrid_basic"


class TemplateError(DuctaError):
    """Exception for template-related errors."""

    def __init__(self, message: str):
        super().__init__(message, ExitCode.CONFIGURATION_ERROR)


class BaseTemplate:
    """What every project scaffold shares, whatever kind of pipeline it ships.

    A template *is* the text of a project's three kinds of file: ``ducta.yaml``,
    ``catalog.yaml`` and one ``pipelines/<name>.yaml`` per pipeline. They are
    written as YAML text, not built from dicts, so the generated files carry the
    comments that explain each non-obvious key, which is most of what a template
    is for. ``tests/console`` generates every template and runs it through the
    project validator, so the text cannot drift from the schema.

    A subclass supplies those three texts, its sample data, the module of Python
    its nodes point at, and a README.
    """

    #: Shown by `ducta template --list-templates`.
    TEMPLATE_NAME = "Base"
    TEMPLATE_DESCRIPTION = ""
    #: Dotted module the generated nodes import their functions from, and the
    #: file the generator writes that module to.
    SAMPLE_MODULE = "pipelines.etl"
    SAMPLE_MODULE_PATH = ("pipelines", "etl.py")
    #: The pipeline `ducta start --pipeline <name>` should run first.
    DEFAULT_PIPELINE = "etl"
    #: Descriptive only: written to the project's ``metadata``.
    TEMPLATE_TYPE = "base"
    ARCHITECTURE = "generic"
    #: What `pip install -r requirements.txt` installs.
    REQUIREMENTS = "ducta[spark]>=0.1.1\n"
    #: Appended to the generated ``.gitignore``.
    GITIGNORE_EXTRA = ""

    def __init__(self, project_name: str, config_format: ConfigFormat = ConfigFormat.YAML):
        self.project_name = project_name
        self.config_format = config_format
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        #: Written explicitly into ``settings`` so the project's evidence
        #: policy is a visible choice, not an invisible default.
        self.evidence_level = "record"
        #: ``--sandbox-developers``: each gets a ``sandbox_<name>`` environment.
        self.developer_sandboxes: List[str] = []

    # ── what a subclass supplies ─────────────────────────────────────────────

    def project_yaml(self) -> str:
        """The text of ``ducta.yaml``."""
        raise NotImplementedError

    def catalog_yaml(self) -> str:
        """The text of ``catalog.yaml``."""
        raise NotImplementedError

    def pipeline_yamls(self) -> Dict[str, str]:
        """``{pipeline name: text of pipelines/<name>.yaml}``."""
        raise NotImplementedError

    def readme(self) -> str:
        """The text of the project's ``README.md``."""
        raise NotImplementedError

    def generate_sample_code(self) -> Optional[str]:
        """The Python module backing this template's nodes, or None if it needs none."""
        return None

    def get_sample_data(self) -> Optional[str]:
        """CSV seed data written to ``data/input.csv``, or None if unused."""
        return None

    def seed_files(self) -> Dict[str, str]:
        """Further seed data: ``{path relative to the project: text}``."""
        return {}

    def quick_start(self) -> List[str]:
        """The commands the generator prints for a first run."""
        pipeline = self.DEFAULT_PIPELINE
        return [
            f"# Run the {pipeline} pipeline",
            f"ducta start -e dev -p {pipeline}",
            "",
            "# Run one node, or see every log line",
            f"ducta start -e dev -p {pipeline} -n <node>",
            f"ducta start -e dev -p {pipeline} -v",
            "",
            "# Check the project without running it (no Spark)",
            "ducta config validate -e dev",
        ]

    # ── shared by the texts ──────────────────────────────────────────────────

    def _render(self, text: str) -> str:
        """Fill the ``@@…@@`` markers; YAML's own braces make ``str.format`` unusable."""
        return (
            text.replace("@@PROJECT@@", self.project_name)
            .replace("@@EVIDENCE@@", self.evidence_level)
            .replace("@@SPARK@@", self._SPARK_NOTE)
        )

    #: PySpark 3.5 bundles an Arrow that cannot run on JDK 21: any Spark -> pandas
    #: conversion (a model's `toPandas()`, some quality checks) logs a leaked-memory
    #: error. Arrow only makes the conversion faster, so it is switched off here.
    _SPARK_NOTE = (
        "  # PySpark 3.5's bundled Arrow cannot run on JDK 21: converting Spark data to\n"
        "  # pandas logs a leaked-memory error. Remove this on JDK 8, 11 or 17 to get the\n"
        "  # faster Arrow conversion.\n"
        "  spark_config:\n"
        '    spark.sql.execution.arrow.pyspark.enabled: "false"\n'
    )

    def _sandbox_note(self) -> str:
        """A comment naming the developer sandboxes, if any were requested."""
        if not self.developer_sandboxes:
            return ""
        names = ", ".join(f"sandbox_{dev}" for dev in self.developer_sandboxes)
        return (
            f"  # Developer sandboxes ({names}) need no entry here: each one uses\n"
            "  # the `sandbox` overrides, and only needs its own when it differs.\n"
        )
