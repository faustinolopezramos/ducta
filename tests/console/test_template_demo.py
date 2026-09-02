"""The scaffold has to demonstrate the product, not just describe it.

`ducta template` is the first thing anyone runs, so what it generates is the
product's first impression. It used to make a poor one, in ways nothing caught:

  * `extract`/`transform`/`load` were all `return <input>`, so a *medallion*
    template produced three byte-identical layers — verified at the time by
    three matching fingerprints in the certificate.
  * The sample was five spotless rows against `row_count: {min: 1}`, so no
    check could ever fail and the quality engine looked like decoration.
  * `quality_gate` appeared nowhere in the whole generator, so the headline
    feature was demonstrated by no template at all.
  * The example custom check called `adapter.count_where(...)`, which does not
    exist — and its own `except` turned the AttributeError into a *failed*
    CheckResult, so a user would blame their data.

These tests assert the properties that make the demo worth running. They are
deliberately about behaviour ("the data is dirty enough to exercise the
checks"), not about exact copy, so wording can change freely.
"""

from __future__ import annotations

import pytest

from ducta.check.core import DFAdapter
from ducta.console.template import MedallionBasicTemplate, MLReadyTemplate


@pytest.fixture
def template():
    return MedallionBasicTemplate("demo")


def _rows(csv: str) -> list[str]:
    return csv.strip().splitlines()[1:]


class TestSampleDataGivesTheChecksSomethingToCatch:
    def test_is_large_enough_to_be_interesting(self, template):
        # Five rows cannot demonstrate deduplication, aggregation, or a
        # fingerprint that sees past a sample window.
        assert len(_rows(template.get_sample_data())) > 100

    def test_contains_missing_values(self, template):
        rows = _rows(template.get_sample_data())
        blank_amounts = [r for r in rows if r.split(",")[2] == ""]
        assert blank_amounts, "silver's null_rate check would pass vacuously"

    def test_contains_exact_duplicates(self, template):
        rows = _rows(template.get_sample_data())
        assert len(rows) > len(set(rows)), "the deduplication step would be a no-op"

    def test_has_a_column_worth_grouping_by(self, template):
        rows = _rows(template.get_sample_data())
        categories = {r.split(",")[1] for r in rows}
        assert 1 < len(categories) < len(rows), "gold's aggregation needs real groups"

    def test_is_deterministic(self, template):
        # The certificate demo is only reproducible if the same scaffold
        # produces the same bytes.
        assert template.get_sample_data() == MedallionBasicTemplate("demo").get_sample_data()


class TestChecksActuallyAssertSomething:
    def test_silver_has_a_blocking_quality_gate(self, template):
        gate = template.generate_nodes_config()["transform"]["data_quality"]["quality_gate"]
        assert gate["enabled"] is True
        assert gate["max_errors"] == 0

    def test_silver_asserts_what_transform_promises(self, template):
        checks = template.generate_nodes_config()["transform"]["data_quality"]["checks"]
        # transform drops nulls and duplicates; the checks must be the ones that
        # notice if it stops.
        assert checks["null_rate"]["threshold"] == 0.0
        assert checks["duplicates"]["columns"]
        # A floor well above 1 — `min: 1` passes for any non-empty result and so
        # asserts nothing.
        assert checks["row_count"]["min"] > 1

    def test_check_config_uses_the_keys_the_checks_actually_read(self, template):
        # `null_rate` reads `columns` (a list) and `threshold`. Writing
        # `column`/`max` parses fine and silently checks every column at the
        # default threshold instead.
        null_rate = template.generate_nodes_config()["transform"]["data_quality"]["checks"][
            "null_rate"
        ]
        assert isinstance(null_rate["columns"], list)
        assert "column" not in null_rate and "max" not in null_rate

    def test_no_check_is_enabled_with_an_empty_target(self, template):
        # `schema: {enabled: true, expected_columns: []}` is a check that runs
        # and asserts nothing — worse than one that is off, because it reads as
        # coverage.
        for node, config in template.generate_nodes_config().items():
            for phase in ("sanity_checks", "data_quality"):
                for name, check in (config.get(phase, {}).get("checks") or {}).items():
                    if not check.get("enabled", True):
                        continue
                    for key in ("expected_columns", "columns"):
                        if key in check:
                            assert check[key], f"{node}.{phase}.{name}.{key} is empty but enabled"


class TestGeneratedCodeCallsRealAPIs:
    def test_the_example_custom_check_uses_a_method_that_exists(self, tmp_path):
        # The scaffolded check is the documented extension point. When it called
        # a non-existent method, its own `except` reported the AttributeError as
        # a data-quality failure.
        from ducta.console.template import TemplateGenerator

        generator = TemplateGenerator(tmp_path)
        generator._generate_etl_sample_code()
        source = (tmp_path / "pipelines" / "checks" / "custom_checks.py").read_text()

        assert "count_where" not in source
        assert "filter_where" in source
        assert hasattr(DFAdapter, "filter_where")

    def test_activation_instructions_match_the_generated_format(self, tmp_path):
        from ducta.console.template import TemplateGenerator

        generator = TemplateGenerator(tmp_path)
        generator._generate_etl_sample_code()
        source = (tmp_path / "pipelines" / "checks" / "custom_checks.py").read_text()

        # The scaffold defaults to YAML; the instructions used to be TOML.
        assert "code-block:: yaml" in source


class TestMLReadyDoesNotInheritTheWrongAssertions:
    """`ml_ready` reuses medallion's nodes over an entirely different table."""

    def test_schema_check_matches_its_own_columns(self):
        nodes = MLReadyTemplate("mldemo").generate_nodes_config()
        expected = nodes["extract"]["sanity_checks"]["checks"]["schema"]["expected_columns"]
        header = MLReadyTemplate("mldemo").get_sample_data().splitlines()[0].split(",")
        assert set(expected) == set(header)

    def test_quality_checks_reference_columns_that_exist(self):
        template = MLReadyTemplate("mldemo")
        header = set(template.get_sample_data().splitlines()[0].split(","))
        checks = template.generate_nodes_config()["transform"]["data_quality"]["checks"]
        for name, check in checks.items():
            for column in check.get("columns", []):
                assert column in header, f"{name} checks '{column}', absent from the sample data"

    def test_row_count_floor_fits_its_own_sample(self):
        template = MLReadyTemplate("mldemo")
        rows = len(_rows(template.get_sample_data()))
        floor = template.generate_nodes_config()["transform"]["data_quality"]["checks"][
            "row_count"
        ]["min"]
        assert floor <= rows, "the inherited floor would block ml_ready's own first run"
