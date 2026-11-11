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

    @staticmethod
    def this_release(fallback: str = "0.1.1") -> str:
        """The release of the Ducta that generates the project, as a ``>=`` floor.

        For templates whose code uses API that older releases lack (``persist_model``'s
        ``promote=``, ``retrain:``): a hand-written floor fell behind the code it
        generated, and ``pip install`` picked a release the project fails on. Only the
        release part (``0.4.0`` of ``0.4.0.dev1+g12ab``); *fallback* when unknown.
        """
        import re

        from ducta import __version__

        match = re.match(r"\d+(?:\.\d+)*", str(__version__))
        release = match.group(0) if match else ""
        return release if release and release.strip("0.") else fallback

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
        "    # The same dates, timestamps and date partitions on every machine (the\n"
        "    # default is the machine's own zone).\n"
        "    spark.sql.session.timeZone: UTC\n"
    )

    def _ml_ci_workflow(self, train: str, score: Optional[str] = None) -> str:
        """``.github/workflows/ml.yml``: check, test, train through the promotion gate, score.

        A pull request is only checked and tested: training promotes, and a branch
        nobody has reviewed must not put its model in production. Training and scoring
        run on a push to main or by hand. Runs in the ``staging`` environment. Point staging's ``mlops_path`` at storage
        the CI runner shares with production (a bucket, a volume), or each CI run
        starts from an empty registry and every model it trains is "the first".
        """
        from pathlib import PurePosixPath

        from ducta import state

        # The certificates of the staging runs (``paths.output: data`` in the templates).
        runs = PurePosixPath(state.under("data/staging", "runs").as_posix())
        score_step = (
            f"""      - name: Score with the model in production
        if: github.event_name != 'pull_request'
        run: ducta start -e staging -p {score}
"""
            if score
            else ""
        )
        return f"""# CI for this ML project: validate, test, train through the promotion gate{', score' if score else ''}.
# Generated by `ducta template`; adapt the triggers and the Python version to your repo.
#
# A model reaches production only through settings.mlops.promotion_policy (ducta.yaml).
# For that gate to compare against the real production model, give the `staging`
# environment an mlops_path on storage this runner shares with production.
# A pull request is only checked and tested: it never trains, so an unreviewed branch
# cannot promote its model. Training and scoring run on a push to main or by hand.
name: ml

on:
  push: {{branches: [main]}}
  pull_request:
  workflow_dispatch:

jobs:
  train:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4   # Spark runs on the JVM
        with: {{distribution: temurin, java-version: "17"}}
      - uses: actions/setup-python@v5
        with: {{python-version: "3.12"}}
      - run: pip install -r requirements.txt
      - name: Validate the project
        run: ducta check -e staging
      - name: Node tests
        run: if [ -d tests ]; then pip install pytest && pytest -q tests; fi
      - name: Train, register, promote if it beats production
        if: github.event_name != 'pull_request'
        run: ducta start -e staging -p {train}
{score_step}      - name: Keep the run certificates
        if: always()
        uses: actions/upload-artifact@v4
        with: {{name: run-certificates, path: {runs}, if-no-files-found: ignore}}
"""

    def _sandbox_note(self) -> str:
        """A comment naming the developer sandboxes, if any were requested."""
        if not self.developer_sandboxes:
            return ""
        names = ", ".join(f"sandbox_{dev}" for dev in self.developer_sandboxes)
        return (
            f"  # Developer sandboxes ({names}) need no entry here: each one uses\n"
            "  # the `sandbox` overrides, and only needs its own when it differs.\n"
        )
