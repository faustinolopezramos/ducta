"""Check parameters are typed: config validation, the editor schema, and the checks agree."""

from __future__ import annotations

from pathlib import Path

import pytest

import ducta.check.checks  # noqa: F401  registers the built-ins
from ducta.check.core import QUALITY_CHECKS_REGISTRY, BaseQualityCheck
from ducta.check.params import CHECK_PARAMS, COMMON_PARAMS, problems_in, schema_for
from ducta.setting.project_loader import ProjectConfigError, validate_project
from ducta.setting.project_schema import json_schema


class TestTheTableAgreesWithTheChecks:
    def test_every_builtin_check_is_described(self):
        assert set(CHECK_PARAMS) == set(QUALITY_CHECKS_REGISTRY)

    @pytest.mark.parametrize("name", sorted(CHECK_PARAMS))
    def test_the_declared_parameters_are_the_ones_the_check_reads(self, name):
        declared = QUALITY_CHECKS_REGISTRY[name].CONFIG_PARAMS
        assert declared is not None, f"{name} should declare CONFIG_PARAMS"
        assert set(CHECK_PARAMS[name]) == set(declared)

    def test_common_parameters_are_not_repeated_per_check(self):
        for name, params in CHECK_PARAMS.items():
            assert not set(params) & set(COMMON_PARAMS), name


class TestProblemsIn:
    @pytest.mark.parametrize(
        "value, fragment",
        [
            (0.1, {"type": "number", "minimum": 0, "maximum": 1}),
            (3, {"type": "integer", "minimum": 0}),
            ("a", {"type": ["number", "string"]}),
            (["a", "b"], {"type": "array", "items": {"type": "string"}}),
            ("sql", {"type": "string", "enum": ["sql", "python"]}),
        ],
    )
    def test_valid_values_pass(self, value, fragment):
        assert problems_in(value, fragment, "x") == []

    @pytest.mark.parametrize(
        "value, fragment, text",
        [
            (1.5, {"type": "number", "maximum": 1}, "must be <= 1"),
            (-1, {"type": "integer", "minimum": 0}, "must be >= 0"),
            ("5", {"type": "integer"}, "must be integer"),
            (True, {"type": "number"}, "must be number"),
            (0, {"type": "number", "exclusiveMinimum": 0}, "must be > 0"),
            ([1], {"type": "array", "items": {"type": "string"}}, "x[0] must be string"),
            ("sqll", {"type": "string", "enum": ["sql", "python"]}, "must be one of"),
        ],
    )
    def test_wrong_values_say_what_is_expected(self, value, fragment, text):
        (message,) = problems_in(value, fragment, "x")
        assert text in message


def _project(root: Path, quality: str, catalog_checks: str = "") -> Path:
    (root / "pipelines").mkdir(parents=True)
    (root / "ducta.yaml").write_text("version: 2\nproject: p\npaths: {input: d, output: o}\n")
    (root / "catalog.yaml").write_text(
        "raw: {format: parquet, path: p" + catalog_checks + "}\nsilver.x.a: {format: parquet}\n"
    )
    (root / "pipelines" / "p.yaml").write_text(
        "nodes:\n  a:\n    run: m:f\n    inputs: [raw]\n    outputs: [silver.x.a]\n"
        f"    quality: {quality}\n"
    )
    return root


class TestConfigValidation:
    def test_valid_parameters_pass(self, tmp_path):
        quality = "{row_count: {min: 3}, null_rate: {columns: [a], threshold: 0.1}}"
        validate_project(_project(tmp_path, quality))

    def test_an_unknown_parameter_suggests_the_real_one_with_its_line(self, tmp_path):
        with pytest.raises(ProjectConfigError) as exc:
            validate_project(_project(tmp_path, "{null_rate: {colums: [a]}}"))
        text = str(exc.value)
        assert "unknown parameter 'colums' (did you mean 'columns'?)" in text
        assert "pipelines/p.yaml:" in text

    def test_a_wrong_type_is_reported_where_it_is_written(self, tmp_path):
        with pytest.raises(ProjectConfigError) as exc:
            validate_project(_project(tmp_path, "{null_rate: {threshold: 5}}"))
        assert "threshold must be <= 1" in str(exc.value)

    def test_a_string_where_a_list_goes_is_an_error(self, tmp_path):
        with pytest.raises(ProjectConfigError, match="columns must be array"):
            validate_project(_project(tmp_path, "{duplicates: {columns: order_id}}"))

    def test_inline_checks_are_validated_too(self, tmp_path):
        with pytest.raises(ProjectConfigError, match="min must be integer"):
            validate_project(_project(tmp_path, "{row_count: {min: many}, gate: {max_errors: 0}}"))

    def test_dataset_contracts_are_validated(self, tmp_path):
        root = _project(
            tmp_path, "{row_count: {min: 1}}", ", checks: {schema: {expected_colums: [a]}}"
        )
        with pytest.raises(ProjectConfigError, match="did you mean 'expected_columns'"):
            validate_project(root)

    def test_a_near_miss_of_a_builtin_check_is_a_typo(self, tmp_path):
        with pytest.raises(ProjectConfigError, match="did you mean 'null_rate'"):
            validate_project(_project(tmp_path, "{null_rte: {threshold: 0}}"))

    def test_a_custom_check_name_is_left_to_the_engine(self, tmp_path):
        validate_project(_project(tmp_path, "{positive_values: {column: amount}}"))

    def test_common_parameters_are_accepted_on_any_check(self, tmp_path):
        validate_project(_project(tmp_path, "{row_count: {min: 1, enabled: true, severity: warn}}"))

    def test_a_check_with_no_parameters_accepts_true(self, tmp_path):
        validate_project(_project(tmp_path, "{empty_dataset: true}"))


class TestThirdPartyChecks:
    def test_a_declared_schema_is_enforced_like_a_builtin(self, tmp_path):
        from ducta.check.core import CheckResult, register_check

        @register_check("positive_values_typed")
        class PositiveValues(BaseQualityCheck):
            CONFIG_PARAMS = frozenset({"column", "minimum"})
            CONFIG_SCHEMA = {
                "column": {"type": "string"},
                "minimum": {"type": "number"},
            }

            def __init__(self) -> None:
                super().__init__("positive_values_typed")

            def _run_impl(self, df, config, adapter, context_datasets=None) -> CheckResult:
                return self._create_result(True, "ok")

        try:
            assert (
                schema_for("positive_values_typed", PositiveValues) == PositiveValues.CONFIG_SCHEMA
            )
            with pytest.raises(ProjectConfigError, match="minimum must be number"):
                validate_project(
                    _project(tmp_path, "{positive_values_typed: {column: a, minimum: low}}")
                )
        finally:
            QUALITY_CHECKS_REGISTRY.pop("positive_values_typed", None)


class TestEditorSchema:
    @pytest.fixture(scope="class")
    def blocks(self):
        defs = json_schema()["$defs"]
        return {
            "catalog": defs["catalog"]["additionalProperties"]["$defs"]["ChecksBlock"],
            "pipeline": defs["pipeline"]["$defs"]["ChecksBlock"],
        }

    def test_every_check_is_offered_with_its_parameters(self, blocks):
        for block in blocks.values():
            entries = block["properties"]["checks"]["properties"]
            assert set(CHECK_PARAMS) <= set(entries)
            row_count = entries["row_count"]["anyOf"][2]
            assert set(row_count["properties"]) >= {"min", "max", "enabled"}
            assert row_count["additionalProperties"] is False

    def test_checks_listed_beside_the_gate_are_offered_too(self, blocks):
        block = blocks["pipeline"]
        assert "null_rate" in block["properties"] and "gate" in block["properties"]
        assert block["additionalProperties"] != False  # noqa: E712  custom checks allowed
