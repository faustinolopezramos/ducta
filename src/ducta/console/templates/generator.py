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

Writes a template's files into a new project folder.
"""

from pathlib import Path
from typing import List, Optional

from loguru import logger

from ducta import state
from ducta.console.core import ConfigFormat
from ducta.console.templates.base import BaseTemplate, TemplateError, TemplateType
from ducta.console.templates.factory import TemplateFactory
from ducta.console.templates.medallion_basic import MedallionBasicTemplate


class TemplateGenerator:
    """Generates complete project templates with directory structure."""

    #: The project files' formats a template can be written in.
    FORMATS = (ConfigFormat.YAML, ConfigFormat.TOML, ConfigFormat.JSON)

    #: ``single``: one catalog.<ext>, profiles inside ducta.<ext>. ``split``: one
    #: catalog/<layer>.<ext> per layer and quality/profiles.<ext>.
    LAYOUTS = ("single", "split")

    def __init__(
        self,
        output_path: Path,
        config_format: ConfigFormat = ConfigFormat.YAML,
        layout: str = "single",
    ):
        if layout not in self.LAYOUTS:
            raise TemplateError(f"Unknown layout '{layout}' (choose {' or '.join(self.LAYOUTS)})")
        self.layout = layout
        if config_format not in self.FORMATS:
            raise TemplateError(
                "Project configuration is YAML, TOML or JSON "
                f"(got '{config_format.value}'): ducta.<ext>, catalog.<ext>, pipelines/"
            )
        self.output_path = Path(output_path)
        self.config_format = config_format

    def generate_project(
        self,
        template_type: TemplateType,
        project_name: str,
        create_sample_code: bool = True,
        developer_sandboxes: Optional[List[str]] = None,
        evidence_level: str = "record",
    ) -> None:
        """Generate a project: ducta.yaml + catalog.yaml + pipelines/*.yaml, and code."""
        logger.debug("Generating {} template for project '{}'", template_type.value, project_name)

        template = TemplateFactory.create_template(template_type, project_name, self.config_format)
        template.evidence_level = evidence_level
        template.developer_sandboxes = list(developer_sandboxes or [])
        self.template = template

        self._write_config_files(template)

        if create_sample_code:
            self._generate_sample_code(template)

        self._generate_project_files(template)
        self._write_text_file(self.output_path / "README.md", template.readme())

        logger.debug("Project '{}' generated successfully at {}", project_name, self.output_path)

    def _write_config_files(self, template: BaseTemplate) -> None:
        """``ducta.*``, ``catalog.*``, ``pipelines/*.*`` and the editor schemas."""
        from ducta.setting.project.decompile import write_schemas

        ext = self.config_format.value
        schemas = state.SCHEMA_DIR
        if self.layout == "split":
            self._write_split_files(template, ext, schemas)
        else:
            self._write_text_file(
                self.output_path / f"ducta.{ext}",
                self._as_format(template.project_yaml(), f"{schemas}/project.json"),
            )
            self._write_text_file(
                self.output_path / f"catalog.{ext}",
                self._as_format(template.catalog_yaml(), f"{schemas}/catalog.json"),
            )
        pipelines_dir = self.output_path / "pipelines"
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        (pipelines_dir / "__init__.py").touch()
        for name, text in template.pipeline_yamls().items():
            self._write_text_file(
                pipelines_dir / f"{name}.{ext}",
                self._as_format(text, f"../{schemas}/pipeline.json"),
            )
        write_schemas(self.output_path)

    def _write_split_files(self, template: BaseTemplate, ext: str, schemas: str) -> None:
        """``ducta.*`` without its profiles, ``quality/profiles.*`` and ``catalog/<layer>.*``."""
        from ducta.console.template_layout import (
            UNLAYERED,
            extract_profiles,
            split_catalog,
            with_schema,
        )

        project_text, profiles_text = extract_profiles(template.project_yaml())
        project_text = project_text.replace("catalog.yaml", "catalog/")
        self._write_text_file(
            self.output_path / f"ducta.{ext}",
            self._as_format(project_text, f"{schemas}/project.json"),
        )
        if profiles_text is not None:
            self._write_text_file(
                self.output_path / "quality" / f"profiles.{ext}",
                self._as_format(
                    with_schema(profiles_text, f"../{schemas}/profiles.json"),
                    f"../{schemas}/profiles.json",
                ),
            )
        catalog_text = template.catalog_yaml()
        schema = f"../{schemas}/catalog.json"
        split = split_catalog(catalog_text)
        if split is None:  # no dataset to file by layer: keep the template's own text
            fixed = catalog_text.replace(f"$schema={schemas}/", f"$schema=../{schemas}/")
            files = {UNLAYERED: fixed}
        else:
            files = {layer: with_schema(text, schema) for layer, text in split.items()}
        for layer, body in files.items():
            self._write_text_file(
                self.output_path / "catalog" / f"{layer}.{ext}", self._as_format(body, schema)
            )

    def _as_format(self, yaml_text: str, schema: str) -> str:
        """The template's YAML text, as the generator's format.

        YAML is written as is, comments included. TOML and JSON are the same
        document converted, so the explanatory comments are not carried over
        (JSON has none; TOML's would need a second copy of every template).
        """
        if self.config_format == ConfigFormat.YAML:
            return yaml_text
        import yaml  # type: ignore

        data = yaml.safe_load(yaml_text) or {}
        if self.config_format == ConfigFormat.JSON:
            import json

            return json.dumps({"$schema": schema, **data}, indent=2, ensure_ascii=False) + "\n"
        try:
            import tomli_w  # type: ignore
        except ImportError as e:
            raise TemplateError(
                "TOML template generation requires 'tomli-w'. Install with: pip install tomli-w"
            ) from e
        return f"#:schema {schema}\n" + tomli_w.dumps(data)

    def _localize(self, text: str) -> str:
        """Point a README or docstring at ``ducta.toml`` instead of ``ducta.yaml``, and so on."""
        import re

        ext = self.config_format.value
        text = re.sub(r"\b(ducta|catalog)\.yaml\b", rf"\1.{ext}", text)
        return re.sub(r"(pipelines/[\w.]+)\.yaml\b", rf"\1.{ext}", text)

    def _generate_sample_code(self, template: BaseTemplate) -> None:
        """Write the Python module this template's nodes point at.

        Asks the template for its own code rather than hard-coding the ETL one:
        a streaming template's module is a transform registry, not a set of
        batch node functions, and they are not interchangeable.
        """
        code = template.generate_sample_code()
        if code is None:
            # The medallion template has no module of its own: it uses the ETL one.
            self._generate_etl_sample_code()
            return

        package, filename = template.SAMPLE_MODULE_PATH
        package_dir = self.output_path / package
        package_dir.mkdir(parents=True, exist_ok=True)
        init_file = package_dir / "__init__.py"
        if not init_file.exists():
            self._write_text_file(init_file, "")
        self._write_text_file(package_dir / filename, code)

    def _generate_etl_sample_code(self) -> None:
        """Generate a single, focused ETL pipeline module."""
        etl_code = '''"""
Medallion ETL: bronze -> silver -> gold

Each layer does real work, and the quality checks in ``pipelines/etl.yaml``
verify that it did. The sample data ships deliberately dirty (12 rows with a
missing amount, 8 verbatim duplicates, 10 rows with a negative amount), so:

    bronze  508 rows   raw, exactly as it arrived
    silver  478 rows   deduplicated, missing and negative amounts dropped
    gold      5 rows   one row per category

The silver checks (null_rate, duplicates, range) pass *because* `transform`
cleaned the data. Break `transform` and the quality gate blocks the run before
anything is written -- that is the point of the demo, and you can try it:
comment out the dropna() below and re-run.
"""
from typing import Any, Optional

from loguru import logger

#: Gold aggregates by this column. Change both to match your own data.
GROUP_COLUMN = "category"
VALUE_COLUMN = "amount"


def _row_count(df: Any) -> int:
    """Row count for a Spark or pandas DataFrame."""
    return df.count() if hasattr(df, "rdd") else len(df)


def extract(
    source_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Bronze: land the source exactly as it arrived.

    Deliberately does not clean anything. The bronze layer's job is to be a
    faithful, replayable copy of the source -- if you clean here, you can never
    prove what the source actually said.

    Ducta has already loaded ``source_data`` per ``catalog.yaml`` (format,
    header, inferSchema), and will write the return value per
    ``catalog.yaml``. You only write the transformation.
    """
    if source_data is None:
        raise ValueError("No data provided from source")

    logger.info("Bronze: landed {:,} raw rows", _row_count(source_data))
    return source_data


def transform(
    raw_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Silver: make the data trustworthy.

    Three operations. The first two are schema-agnostic, so they keep working
    when you point the pipeline at your own table; the third only fires on the
    column this template's sample data is actually dirty in:

      1. drop exact duplicate rows
      2. drop rows with a missing value in any column
      3. drop rows where ``VALUE_COLUMN`` is negative, if that column exists --
         a refund or entry error, not a value `dropna()` would ever catch

    The ``data_quality`` checks on this node assert the result: null_rate 0, no
    duplicate order_id, and no negative amount. They are not decoration -- they
    fail if this function stops doing its job, and the gate stops the run
    before gold is written.
    """
    if raw_data is None:
        raise ValueError("raw_data cannot be None")

    # `cleaned` is reassigned at each stage (not chained through separate
    # names) so that commenting out any *one* of the three lines below to try
    # the quality gate still leaves it bound to the previous stage's result --
    # not undefined. That is the whole point of the exercise in the README.
    before = _row_count(raw_data)

    cleaned = raw_data.dropDuplicates() if hasattr(raw_data, "dropDuplicates") else raw_data.drop_duplicates()
    after_dedup = _row_count(cleaned)

    cleaned = cleaned.dropna()
    after_dropna = _row_count(cleaned)

    if VALUE_COLUMN in list(getattr(cleaned, "columns", [])):
        # `IS NULL OR ... >= 0`, not just `>= 0`: SQL's three-valued logic
        # would otherwise silently drop null amounts here too, so commenting
        # out the dropna() line above would stop demonstrating anything -- the
        # range filter would have already removed the rows null_rate expects
        # to catch. Each cleaning step should only remove the defect it owns.
        cleaned = (
            cleaned.filter(f"{VALUE_COLUMN} IS NULL OR {VALUE_COLUMN} >= 0")
            if hasattr(cleaned, "filter")
            else cleaned[cleaned[VALUE_COLUMN].isna() | (cleaned[VALUE_COLUMN] >= 0)]
        )
    after = _row_count(cleaned)

    logger.info(
        "Silver: {:,} -> {:,} rows ({:,} duplicates, {:,} incomplete, {:,} invalid)",
        before,
        after,
        before - after_dedup,
        after_dedup - after_dropna,
        after_dropna - after,
    )
    return cleaned


def load(
    clean_data: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Any:
    """Gold: aggregate into something a consumer would actually query.

    One row per ``GROUP_COLUMN`` with the order count and the total/average
    ``VALUE_COLUMN``. This is where the medallion pattern pays off: gold is
    small, stable and shaped for reading, while silver stays row-level.
    """
    if clean_data is None:
        raise ValueError("clean_data cannot be None")

    columns = list(getattr(clean_data, "columns", []))
    if GROUP_COLUMN not in columns or VALUE_COLUMN not in columns:
        # Keeps the node working when the template is pointed at your own data
        # before you have adjusted the two constants at the top of this file.
        logger.warning(
            "Gold: no '{}'/'{}' columns in {}; passing silver through unaggregated. "
            "Set GROUP_COLUMN/VALUE_COLUMN in pipelines/etl.py to aggregate.",
            GROUP_COLUMN,
            VALUE_COLUMN,
            columns,
        )
        return clean_data

    if hasattr(clean_data, "rdd"):  # Spark
        from pyspark.sql import functions as F

        aggregated = (
            clean_data.groupBy(GROUP_COLUMN)
            .agg(
                F.count(F.lit(1)).alias("order_count"),
                F.round(F.sum(VALUE_COLUMN), 2).alias("total_amount"),
                F.round(F.avg(VALUE_COLUMN), 2).alias("avg_amount"),
            )
            .orderBy(GROUP_COLUMN)
        )
    else:  # pandas
        aggregated = (
            clean_data.groupby(GROUP_COLUMN)[VALUE_COLUMN]
            .agg(order_count="count", total_amount="sum", avg_amount="mean")
            .round(2)
            .reset_index()
            .sort_values(GROUP_COLUMN)
        )

    logger.info("Gold: aggregated into {:,} rows by '{}'", _row_count(aggregated), GROUP_COLUMN)
    return aggregated
'''

        etl_file = self.output_path / "pipelines" / "etl.py"
        self._write_text_file(etl_file, etl_code)

        # Generate custom checks example
        checks_dir = self.output_path / "pipelines" / "checks"
        checks_dir.mkdir(parents=True, exist_ok=True)
        (checks_dir / "__init__.py").touch()

        custom_checks_code = '''"""
Custom Quality Checks
=====================
Add your project-specific data quality checks here.

Steps to activate a custom check
---------------------------------
1. Define a class that inherits from ``BaseQualityCheck`` and decorate it with
   ``@register_check("your_check_name")``.
2. Implement ``_run_impl()`` and return ``self._create_result(...)``. An
   exception it raises becomes a failed result, not a crashed run.
3. Add the module to ``settings.quality.extensions`` in ``ducta.yaml``:

   .. code-block:: yaml

       settings:
         quality:
           extensions:
             - pipelines.checks.custom_checks

4. Use the check in any node's ``quality`` block (or a dataset's ``checks`` in
   ``catalog.yaml``):

   .. code-block:: yaml

       my_node:
         quality:
           checks:
             positive_values: {column: amount}

"""
from ducta.check import BaseQualityCheck, CheckSeverity, register_check


# ---------------------------------------------------------------------------
# Example 1: Single-column positivity check
# ---------------------------------------------------------------------------
@register_check("positive_values")
class PositiveValuesCheck(BaseQualityCheck):
    """Fail if any value in *column* is <= 0.

    Config keys
    -----------
    column : str
        Name of the column to check (required).
    severity : str
        "ERROR" or "WARNING" (default: "ERROR").
    """

    def __init__(self):
        super().__init__("positive_values", CheckSeverity.ERROR)

    def _run_impl(self, df, config, adapter, context_datasets=None):
        column = getattr(config, "column", None)
        if not column:
            return self._create_result(False, "'column' is required for positive_values check")

        # The adapter runs the same SQL condition on Spark and pandas.
        non_positive = adapter.filter_where(f"{column} <= 0")
        if non_positive > 0:
            return self._create_result(
                False,
                f"Column '{column}' has {non_positive} non-positive values",
                {"column": column, "non_positive_count": non_positive},
            )
        return self._create_result(True, f"All values in '{column}' are positive")


# ---------------------------------------------------------------------------
# Example 2: Referential check between two columns
# ---------------------------------------------------------------------------
# @register_check("email_domain")
# class EmailDomainCheck(BaseQualityCheck):
#     """Verify email values belong to expected domains.
#
#     Config keys
#     -----------
#     column : str
#         Email column to check.
#     allowed_domains : list[str]
#         List of allowed domain strings (e.g. ["example.com"]).
#     """
#
#     def __init__(self):
#         super().__init__("email_domain", CheckSeverity.WARNING)
#
#     def _run_impl(self, df, config, adapter, context_datasets=None):
#         column = getattr(config, "column", "email")
#         allowed = getattr(config, "allowed_domains", [])
#         ...
'''
        custom_file = checks_dir / "custom_checks.py"
        self._write_text_file(custom_file, custom_checks_code)

    def _generate_project_files(self, template: MedallionBasicTemplate) -> None:
        """Generate the supporting files (the README is written with the configuration)."""
        self._write_support_files(template)

    def _write_support_files(self, template: BaseTemplate) -> None:
        """requirements, .gitignore and seed data — identical for every template."""
        # requirements.txt - minimal but complete
        # `ducta[spark]` rather than ducta + a loose pyspark pin: the extra is
        # what the project actually declares as compatible, and pinning pyspark
        # separately invites a combination Ducta was never tested against.
        requirements = template.REQUIREMENTS
        requirements_file = self.output_path / "requirements.txt"
        self._write_text_file(requirements_file, requirements)

        # .gitignore
        gitignore = (
            """# Secrets and machine-local values: never committed. Templates are.
.env
.env.*
!.env.example
!.env.sample
!.env.template
!.env.dist

__pycache__/
*.py[cod]
*.so
.Python
env/
venv/
ENV/
build/
dist/
*.egg-info/
.eggs/

# Data: what a run writes, per environment (`paths.output` is data/)
data/dev/
data/sandbox/
data/sandbox_*/
data/prod/
data/raw/
data/processed/
!data/input.csv

# Logs
logs/
*.log

# IDE
.vscode/
.idea/
*.swp
.DS_Store

# Testing
.coverage
.pytest_cache/
htmlcov/

# Spark
metastore_db/
spark-warehouse/

# Kept by the web server for this machine: its lock and audit trail, and the reports
# of `ducta-server`'s ad-hoc "run checks" (committed schemas and comments stay tracked)
.ducta/config.lock
.ducta/audit.log
.quality/
"""
            + template.GITIGNORE_EXTRA
        )
        gitignore_file = self.output_path / ".gitignore"
        self._write_text_file(gitignore_file, gitignore)

        self._write_seed_data(template)

    def _write_seed_data(self, template: BaseTemplate) -> None:
        """Write whatever seed data this template's first run needs.

        A batch template seeds one CSV the input catalog points at. A streaming
        template seeds *files in a watched directory* — the stream has to have
        something to pick up, and it arrives as separate files rather than one.
        """
        sample_data = template.get_sample_data()
        if sample_data is not None:
            self._write_text_file(self.output_path / "data" / "input.csv", sample_data)

        for relative, text in template.seed_files().items():
            self._write_text_file(self.output_path / relative, text)

        events = getattr(template, "SAMPLE_EVENTS", None)
        if events:
            events_dir = self.output_path / "data" / "events"
            events_dir.mkdir(parents=True, exist_ok=True)
            # One file per event: `maxFilesPerTrigger: 1` then makes the demo
            # show several micro-batches instead of swallowing everything in one.
            for index, event in enumerate(events, start=1):
                self._write_text_file(events_dir / f"event_{index:03d}.json", event + "\n")

    def _write_text_file(self, file_path: Path, content: str) -> None:
        """Write text file."""
        if self.layout == "split" and file_path.suffix in (".py", ".md"):
            import re

            content = re.sub(r"\bcatalog\.yaml\b", "catalog/", content)
        if self.config_format != ConfigFormat.YAML and file_path.suffix in (".py", ".md"):
            content = self._localize(content)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
