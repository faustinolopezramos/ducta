"""Validating a node's quality configuration without running it.

`QualityService.validate_node_config` reads the node from its project as an
environment sees it — the same compiled configuration a run uses — so a
profile defined only in one environment is resolved there. The CLI
(`ducta quality validate-config`) and the API route
(tests/api/test_quality_validate_config.py) are thin wrappers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.check.service import QualityService
from ducta.setting.project_loader import ProjectConfigError

PROJECT = """\
version: 2
project: demo
paths: {input: data, output: data}
settings:
  quality:
    profiles:
      strict:
        checks:
          empty_dataset: {enabled: true}
environments:
  prod:
    settings.quality.profiles.release:
      checks:
        empty_dataset: {enabled: true}
"""

CATALOG = """\
orders: {format: csv, path: data/orders.csv}
silver.sales.orders: {format: parquet}
"""

PIPELINE = """\
requires_dates: false
nodes:
  clean:
    run: pipelines.etl:clean
    inputs: {raw: orders}
    outputs: [silver.sales.orders]
    input_checks:
      orders:
        checks:
          row_count: {min: 1}
    quality:
      profile: {profile}
      checks:
        null_rate: {columns: [order_id], threshold: 0}
        {extra}
  bare:
    run: pipelines.etl:bare
    inputs: [silver.sales.orders]
"""


def _project(root: Path, profile: str = "strict", extra: str = "") -> Path:
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text(PROJECT)
    (root / "catalog.yaml").write_text(CATALOG)
    (root / "pipelines" / "etl.yaml").write_text(
        PIPELINE.replace("{profile}", profile).replace("{extra}", extra)
    )
    return root


class TestService:
    def test_a_well_configured_node_is_valid(self, tmp_path):
        result = QualityService.validate_node_config("clean", _project(tmp_path))
        assert result == {"valid": True, "errors": [], "warnings": []}

    def test_an_unknown_check_is_an_error(self, tmp_path):
        root = _project(tmp_path, extra="no_such_check: {}")
        result = QualityService.validate_node_config("clean", root)
        assert not result["valid"]
        assert "Unknown check 'no_such_check'" in result["errors"][0]

    def test_a_profile_resolves_in_the_environment_that_defines_it(self, tmp_path):
        root = _project(tmp_path, profile="release")
        assert QualityService.validate_node_config("clean", root, env="prod")["valid"]
        base = QualityService.validate_node_config("clean", root)
        assert not base["valid"]
        assert "Profile 'release'" in base["errors"][0]

    def test_an_unknown_check_in_an_input_contract_is_an_error(self, tmp_path):
        root = _project(tmp_path)
        (root / "catalog.yaml").write_text(
            CATALOG.replace(
                "silver.sales.orders: {format: parquet}",
                "silver.sales.orders: {format: parquet, quality: {checks: {nope: {}}}}",
            )
        )
        result = QualityService.validate_node_config("bare", root)
        assert "Unknown check 'nope'" in result["errors"][0]
        assert "input 'silver.sales.orders'" in result["errors"][0]

    def test_a_node_without_checks_gets_a_warning(self, tmp_path):
        result = QualityService.validate_node_config("bare", _project(tmp_path))
        assert result["valid"] and "has no quality checks" in result["warnings"][0]

    def test_an_unknown_node_is_invalid(self, tmp_path):
        result = QualityService.validate_node_config("ghost", _project(tmp_path))
        assert result["errors"] == ["Node 'ghost' is not in the project"]

    def test_an_invalid_project_raises_its_problems(self, tmp_path):
        root = _project(tmp_path)
        (root / "catalog.yaml").write_text("orders: {format: csv, pth: x}\n")
        with pytest.raises(ProjectConfigError):
            QualityService.validate_node_config("clean", root)


class TestCli:
    def _run(self, *args: str) -> int:
        from ducta.console.cli import UnifiedCLI

        return UnifiedCLI().run(["quality", "validate-config", *args])

    def test_valid_node_exits_zero(self, tmp_path):
        root = _project(tmp_path)
        assert self._run("--node", "clean", "--base-path", str(root)) == 0

    def test_invalid_node_exits_non_zero(self, tmp_path):
        root = _project(tmp_path, extra="no_such_check: {}")
        assert self._run("--node", "clean", "--base-path", str(root)) != 0


EXTENSION = """\
from ducta.check import BaseQualityCheck, register_check


@register_check("{name}")
class Custom(BaseQualityCheck):
    def __init__(self):
        super().__init__("{name}")

    def _run_impl(self, df, config, adapter, context_datasets=None):
        return self._create_result(True, "ok")
"""


@pytest.fixture
def project_with_extension(tmp_path):
    """A node using a custom check from the project's quality.extensions."""
    import sys
    import uuid

    from ducta.check import QUALITY_CHECKS_REGISTRY

    tag = uuid.uuid4().hex[:8]
    module, check = f"ext_checks_{tag}", f"custom_{tag}"
    root = _project(tmp_path, extra=f"{check}: {{}}")
    (root / f"{module}.py").write_text(EXTENSION.replace("{name}", check))
    manifest = (root / "ducta.yaml").read_text()
    (root / "ducta.yaml").write_text(
        manifest.replace("  quality:\n", f"  quality:\n    extensions: [{module}]\n", 1)
    )
    yield root, check
    QUALITY_CHECKS_REGISTRY.pop(check, None)
    sys.modules.pop(module, None)


class TestExtensions:
    def test_custom_checks_are_imported_and_known(self, project_with_extension):
        root, _check = project_with_extension
        assert QualityService.validate_node_config("clean", root)["valid"]

    def test_without_importing_them_a_custom_check_is_only_a_warning(self, project_with_extension):
        root, check = project_with_extension
        result = QualityService.validate_node_config("clean", root, load_extensions=False)
        assert result["valid"]
        assert f"Check '{check}'" in result["warnings"][0]
