"""Say it once: inline checks, `defaults`, and pipeline templates (`extends` / `params`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.setting.project_loader import ProjectConfigError, compile_project, validate_project

_CATALOG = """\
raw: {format: parquet, path: data/raw}
silver.x.a: {format: parquet}
silver.x.b: {format: parquet}
silver.x.model: {format: parquet}
bronze.a.b: {format: parquet}
"""


def _project(root: Path, project: str = "", catalog: str = "", **files: str) -> Path:
    (root / "pipelines").mkdir(parents=True, exist_ok=True)
    (root / "ducta.yaml").write_text(
        "version: 2\nproject: demo\npaths: {input: data, output: out}\n" + project
    )
    (root / "catalog.yaml").write_text(catalog or _CATALOG)
    for rel, text in files.items():
        path = root / (rel.replace("__", "/") + ".yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _docs(root: Path, env=None):
    return compile_project(validate_project(root, env))


ETL = """\
nodes:
  a: {run: m:f, inputs: [raw], outputs: [silver.x.a]}
  b: {run: m:g, inputs: [silver.x.a], outputs: [silver.x.b], retry: 5}
"""


class TestInlineChecks:
    def test_checks_can_sit_next_to_the_gate(self, tmp_path):
        pipe = (
            "nodes:\n  a:\n    run: m:f\n    inputs: [raw]\n    outputs: [silver.x.a]\n"
            "    quality:\n      row_count: {min: 3}\n      null_rate: {columns: [x], threshold: 0}\n"
            "      gate: {max_errors: 0}\n"
        )
        root = _project(tmp_path, pipelines__p=pipe)
        dq = _docs(root)["nodes_config"]["a"]["data_quality"]
        assert set(dq["checks"]) == {"row_count", "null_rate"}
        assert dq["quality_gate"]["max_errors"] == 0

    def test_it_is_the_same_as_the_nested_form(self, tmp_path):
        inline = "run: m:f\n    inputs: [raw]\n    outputs: [silver.x.a]\n"
        a = _project(
            tmp_path / "a",
            pipelines__p=f"nodes:\n  n:\n    {inline}    quality: {{row_count: {{min: 3}}}}\n",
        )
        b = _project(
            tmp_path / "b",
            pipelines__p=f"nodes:\n  n:\n    {inline}    quality: {{checks: {{row_count: {{min: 3}}}}}}\n",
        )
        assert _docs(a)["nodes_config"] == _docs(b)["nodes_config"]

    def test_a_near_miss_of_a_block_key_is_a_typo_not_a_check(self, tmp_path):
        root = _project(
            tmp_path,
            catalog=_CATALOG + "raw2: {format: parquet, path: p, checks: {fail_fas: true}}\n",
            pipelines__p=ETL,
        )
        with pytest.raises(ProjectConfigError, match="did you mean 'fail_fast'"):
            validate_project(root)

    def test_a_dataset_contract_can_be_one_line(self, tmp_path):
        root = _project(
            tmp_path,
            catalog=_CATALOG.replace(
                "raw: {format: parquet, path: data/raw}",
                "raw: {format: parquet, path: p, checks: {empty_dataset: true}}",
            ),
            pipelines__p=ETL,
        )
        contract = _docs(root)["nodes_config"]["a"]["sanity_checks"]["inputs"]["raw"]
        assert contract["checks"] == {"empty_dataset": {}}


class TestDefaults:
    def test_node_defaults_apply_unless_the_node_sets_its_own(self, tmp_path):
        root = _project(
            tmp_path,
            "defaults: {node: {retry: 2, timeout_seconds: 600}}\n",
            pipelines__p=ETL,
        )
        nodes = _docs(root)["nodes_config"]
        assert (nodes["a"]["retry"], nodes["a"]["timeout"]) == (2, 600)
        assert nodes["b"]["retry"] == 5  # the node wins

    def test_pipeline_defaults_beat_project_defaults(self, tmp_path):
        root = _project(
            tmp_path,
            "defaults: {node: {retry: 2}}\n",
            pipelines__p="defaults: {node: {retry: 4}}\n" + ETL,
        )
        nodes = _docs(root)["nodes_config"]
        assert (nodes["a"]["retry"], nodes["b"]["retry"]) == (4, 5)

    def test_an_environment_still_overrides_a_default(self, tmp_path):
        root = _project(
            tmp_path,
            "defaults: {node: {retry: 2}}\n"
            "environments:\n  prod: {pipelines.p.nodes.a.retry: 7}\n",
            pipelines__p=ETL,
        )
        assert _docs(root, "prod")["nodes_config"]["a"]["retry"] == 7
        assert _docs(root, "dev")["nodes_config"]["a"]["retry"] == 2

    def test_a_default_gate_only_reaches_nodes_that_have_quality(self, tmp_path):
        pipe = (
            "nodes:\n"
            "  a: {run: m:f, inputs: [raw], outputs: [silver.x.a], quality: {row_count: {min: 1}}}\n"
            "  b: {run: m:g, inputs: [silver.x.a], outputs: [silver.x.b]}\n"
        )
        root = _project(
            tmp_path,
            "defaults: {node: {quality: {gate: {max_errors: 0}}}}\n",
            pipelines__p=pipe,
        )
        nodes = _docs(root)["nodes_config"]
        assert nodes["a"]["data_quality"]["quality_gate"]["max_errors"] == 0
        assert "data_quality" not in nodes["b"]

    def test_catalog_defaults_match_by_glob_in_order(self, tmp_path):
        catalog = (
            "raw: {format: csv, path: data/raw}\n"
            "silver.x.a: {}\n"
            "silver.x.b: {format: delta}\n"
            "silver.x.model: {}\n"
            "bronze.a.b: {format: csv}\n"
        )
        root = _project(
            tmp_path,
            "defaults:\n  catalog:\n    '*': {write: {mode: append}}\n"
            "    'silver.*': {format: parquet}\n",
            catalog=catalog,
            pipelines__p=ETL,
        )
        out = _docs(root)["output_config"]
        assert out["silver.x.a"]["format"] == "parquet"
        assert out["silver.x.a"]["write_mode"] == "append"
        assert out["silver.x.b"]["format"] == "delta"  # the dataset wins

    def test_stream_defaults_fill_every_stream_node(self, tmp_path):
        pipe = (
            "type: streaming\nrequires_dates: false\nnodes:\n"
            "  n:\n    kind: stream\n    stream:\n      input: {format: kafka}\n"
            "      output: {format: delta, path: o}\n"
        )
        root = _project(
            tmp_path,
            "defaults: {stream: {streaming: {trigger: 10s, output_mode: append}}}\n",
            pipelines__p=pipe,
        )
        node = _docs(root)["nodes_config"]["n"]
        assert node["streaming"]["trigger"] == {"type": "processing_time", "interval": "10 seconds"}

    def test_unknown_default_keys_are_errors_with_a_suggestion(self, tmp_path):
        root = _project(tmp_path, "defaults: {node: {retrry: 2}}\n", pipelines__p=ETL)
        with pytest.raises(ProjectConfigError, match="did you mean 'retry'"):
            validate_project(root)


TEMPLATE = """\
params:
  target: null            # required
  method: random
  test_size: 0.2
type: ml
requires_dates: false
split: {method: "${params.method}", test_size: "${params.test_size}", stratify_col: "${params.target}"}
nodes:
  train:
    description: "Train a model for ${params.target}"
    run: ml:train
    inputs: [raw]
    outputs: [silver.x.model]
"""


class TestExtends:
    def _ml(self, tmp_path, extra: str = "", params: str = "{target: y}") -> Path:
        return _project(
            tmp_path,
            templates__ml=TEMPLATE,
            pipelines__risk=f"extends: templates/ml\nparams: {params}\n{extra}",
        )

    def test_the_template_is_filled_and_keeps_value_types(self, tmp_path):
        docs = _docs(self._ml(tmp_path))
        pipe = docs["pipelines_config"]["risk"]
        assert pipe["type"] == "ml"
        assert pipe["split"] == {"method": "random", "test_size": 0.2, "stratify_col": "y"}
        assert docs["nodes_config"]["train"]["description"] == "Train a model for y"

    def test_the_file_overrides_the_template_and_merges_mappings(self, tmp_path):
        extra = "split: {method: stratified}\nnodes:\n  train: {retry: 3}\n"
        docs = _docs(self._ml(tmp_path, extra))
        assert docs["pipelines_config"]["risk"]["split"]["method"] == "stratified"
        assert docs["pipelines_config"]["risk"]["split"]["test_size"] == 0.2
        train = docs["nodes_config"]["train"]
        assert train["retry"] == 3 and train["function"] == "train"

    def test_a_required_parameter_must_be_given(self, tmp_path):
        with pytest.raises(ProjectConfigError, match="needs the parameter 'target'"):
            validate_project(self._ml(tmp_path, params="{method: stratified}"))

    def test_an_unknown_parameter_suggests_the_declared_one(self, tmp_path):
        with pytest.raises(
            ProjectConfigError, match="no parameter 'targt' — did you mean 'target'"
        ):
            validate_project(self._ml(tmp_path, params="{targt: y}"))

    def test_a_missing_template_is_reported(self, tmp_path):
        root = _project(tmp_path, pipelines__p="extends: templates/nope\n")
        with pytest.raises(ProjectConfigError, match="templates/nope.yaml does not exist"):
            validate_project(root)

    def test_a_template_cannot_leave_the_project(self, tmp_path):
        root = _project(tmp_path / "proj", pipelines__p="extends: ../outside\n")
        (tmp_path / "outside.yaml").write_text("nodes: {}\n")
        with pytest.raises(ProjectConfigError, match="outside the project"):
            validate_project(root)

    def test_templates_cannot_chain(self, tmp_path):
        root = _project(
            tmp_path,
            templates__a="extends: templates/b\n",
            templates__b="nodes: {}\n",
            pipelines__p="extends: templates/a\n",
        )
        with pytest.raises(ProjectConfigError, match="cannot chain"):
            validate_project(root)

    def test_an_undeclared_placeholder_is_an_error(self, tmp_path):
        root = _project(
            tmp_path,
            templates__t='description: "${params.nope}"\nnodes: {}\n',
            pipelines__p="extends: templates/t\n",
        )
        with pytest.raises(ProjectConfigError, match=r"uses \$\{params.nope\}"):
            validate_project(root)

    def test_placeholders_outside_params_are_left_alone(self, tmp_path):
        root = _project(
            tmp_path,
            templates__t="params: {x: 1}\nnodes:\n  n: {run: m:f, outputs: [bronze.a.b]}\n",
            pipelines__p="extends: templates/t\n",
            catalog="bronze.a.b: {format: parquet, path: '${paths.output}/${env}/b'}\n",
        )
        assert _docs(root)["output_config"]["bronze.a.b"]["filepath"] == (
            "${output_path}/${environment}/b"
        )


class TestRequiredParametersWithoutNull:
    """TOML has no null, so a required parameter is declared as "<required>"."""

    def _toml_project(self, root: Path, supplied: str) -> Path:
        _project(root)
        for name in ("ducta.yaml", "catalog.yaml"):
            (root / name).rename(root / name.replace(".yaml", ".toml.tmp"))
        (root / "ducta.toml").write_text(
            'version = 2\nproject = "p"\n[paths]\ninput = "d"\noutput = "o"\n'
        )
        (root / "catalog.toml").write_text(
            '[raw]\nformat = "parquet"\npath = "p"\n["silver.x.a"]\nformat = "parquet"\n'
        )
        (root / "templates").mkdir()
        (root / "templates" / "t.toml").write_text(
            '[params]\nwho = "<required>"\n[nodes.a]\nrun = "m:f"\ninputs = ["raw"]\n'
            'outputs = ["silver.x.a"]\n'
        )
        (root / "pipelines" / "p.toml").write_text(f'extends = "templates/t"\n{supplied}')
        return root

    def test_a_missing_value_is_reported(self, tmp_path):
        with pytest.raises(ProjectConfigError, match="needs the parameter 'who'"):
            validate_project(self._toml_project(tmp_path, ""))

    def test_a_supplied_value_is_accepted(self, tmp_path):
        root = self._toml_project(tmp_path, "[params]\nwho = 'ana'\n")
        assert "p" in _docs(root)["pipelines_config"]
