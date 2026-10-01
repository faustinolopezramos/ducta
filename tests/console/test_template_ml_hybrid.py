"""The ML and hybrid scaffolds: shapes the engine reads, and data that gives them work to do."""

from __future__ import annotations

from pathlib import Path

import pytest

from ducta.console.template import (
    HybridBasicTemplate,
    MLBasicTemplate,
    TemplateFactory,
    TemplateGenerator,
    TemplateType,
)
from ducta.setting.project_loader import compile_project, validate_project
from ducta.stream.validators import StreamingValidator


def _generate(tmp_path: Path, kind: TemplateType) -> Path:
    root = tmp_path / "p"
    TemplateGenerator(root).generate_project(kind, "p")
    return root


def _docs(root: Path, env: str = "dev") -> dict:
    return compile_project(validate_project(root, env))


def test_both_are_offered():
    listed = {t["type"] for t in TemplateFactory.list_available_templates()}
    assert {"ml_basic", "hybrid_basic"} <= listed


class TestMLBasic:
    def test_the_pipeline_is_ml_with_a_declared_split_and_hyperparameters(self, tmp_path):
        docs = _docs(_generate(tmp_path, TemplateType.ML_BASIC))
        pipeline = docs["pipelines_config"]["churn_model"]
        assert pipeline["type"] == "ml"
        assert pipeline["split"]["method"] == "stratified"
        assert pipeline["split"]["stratify_col"] == "churned"
        assert pipeline["hyperparams"]["n_estimators"] == 100
        assert pipeline["model_version"] == "1.0.0"

    def test_the_run_is_seeded_and_tracked(self, tmp_path):
        g = _docs(_generate(tmp_path, TemplateType.ML_BASIC))["global_config"]
        assert g["random_seed"] == 42
        assert g["mlops_enabled"] is True
        assert (
            _docs(_generate(tmp_path / "x", TemplateType.ML_BASIC), "prod")["global_config"][
                "mlops_required"
            ]
            is True
        )

    def test_the_training_node_is_marked_as_training(self, tmp_path):
        nodes = _docs(_generate(tmp_path, TemplateType.ML_BASIC))["nodes_config"]
        assert nodes["train"]["ml_stage"] == "training"
        assert nodes["train"]["input"] == {"features": "silver.churn.features"}

    def test_function_parameters_match_the_mapped_inputs(self, tmp_path):
        """`inputs: {parameter: dataset}` names the function's parameters."""
        import inspect

        code = MLBasicTemplate("p").generate_sample_code()
        namespace: dict = {}
        exec(compile(code, "churn.py", "exec"), namespace)
        nodes = _docs(_generate(tmp_path, TemplateType.ML_BASIC))["nodes_config"]
        for name in ("prepare_features", "train"):
            params = set(inspect.signature(namespace[name]).parameters)
            assert set(nodes[name]["input"]) <= params, name

    def test_the_seed_data_is_dirty_and_has_signal(self):
        csv = MLBasicTemplate("p").seed_files()["data/customers.csv"]
        rows = csv.strip().splitlines()[1:]
        assert len(rows) == 606
        assert len(rows) > len(set(rows)), "the de-duplication step would be a no-op"
        assert any(r.split(",")[2] == "" for r in rows), "no missing spend to drop"
        churned = sum(r.rsplit(",", 1)[1] == "1" for r in rows) / len(rows)
        assert 0.2 < churned < 0.45, "an imbalanced but learnable target"

    def test_the_seed_data_is_deterministic(self):
        a, b = MLBasicTemplate("p").seed_files(), MLBasicTemplate("q").seed_files()
        assert a == b

    def test_it_installs_the_mlops_extra_and_ignores_models(self, tmp_path):
        root = _generate(tmp_path, TemplateType.ML_BASIC)
        assert "ducta[spark,mlops]" in (root / "requirements.txt").read_text()
        assert "mlops_data/" in (root / ".gitignore").read_text()

    def test_the_catalog_contract_matches_the_seed_columns(self, tmp_path):
        root = _generate(tmp_path, TemplateType.ML_BASIC)
        header = (root / "data" / "customers.csv").read_text().splitlines()[0].split(",")
        contract = _docs(root)["nodes_config"]["prepare_features"]["sanity_checks"]["inputs"]
        assert contract["customers"]["checks"]["schema"]["expected_columns"] == header


class TestHybridBasic:
    def test_it_is_one_hybrid_pipeline_with_a_batch_node_before_the_stream(self, tmp_path):
        docs = _docs(_generate(tmp_path, TemplateType.HYBRID_BASIC))
        assert docs["pipelines_config"]["orders"]["type"] == "hybrid"
        nodes = docs["nodes_config"]
        assert nodes["build_products"]["module"] == "pipelines.orders"
        assert nodes["enrich_orders"]["type"] == "streaming"
        assert nodes["enrich_orders"]["dependencies"] == ["build_products"]

    def test_the_stream_node_validates_against_the_engine(self, tmp_path):
        nodes = _docs(_generate(tmp_path, TemplateType.HYBRID_BASIC))["nodes_config"]
        StreamingValidator().validate_streaming_node_config(
            {**nodes["enrich_orders"], "name": "enrich_orders"}
        )

    def test_the_dimension_path_is_under_a_key_named_path(self, tmp_path):
        """Only a value under `path` has ${paths.output}/${env} expanded."""
        node = _docs(_generate(tmp_path, TemplateType.HYBRID_BASIC))["nodes_config"][
            "enrich_orders"
        ]
        assert node["function"]["params"]["products"]["path"].endswith("/silver/shop/products")

    def test_it_finishes_by_itself(self, tmp_path):
        node = _docs(_generate(tmp_path, TemplateType.HYBRID_BASIC))["nodes_config"][
            "enrich_orders"
        ]
        assert node["streaming"]["trigger"] == {"type": "available_now"}

    def test_the_seed_data_has_a_duplicate_and_one_file_per_micro_batch(self):
        files = HybridBasicTemplate("p").seed_files()
        products = files["data/products.csv"].strip().splitlines()[1:]
        assert len(products) == 31 and len(set(products)) == 30
        orders = [p for p in files if p.startswith("data/orders/")]
        assert len(orders) == 5
        assert all(files[p].count("order_id") == 3 for p in orders)

    def test_every_order_matches_a_product(self):
        import json

        files = HybridBasicTemplate("p").seed_files()
        ids = {int(r.split(",")[0]) for r in files["data/products.csv"].splitlines()[1:]}
        for path, text in files.items():
            if path.startswith("data/orders/"):
                for line in text.splitlines():
                    assert json.loads(line)["product_id"] in ids

    def test_the_transform_is_registered_automatically(self, tmp_path):
        g = _docs(_generate(tmp_path, TemplateType.HYBRID_BASIC))["global_config"]
        assert "pipelines.orders" in g["streaming_transform_modules"]


@pytest.mark.parametrize("kind", [TemplateType.ML_BASIC, TemplateType.HYBRID_BASIC])
def test_each_ships_a_readme_that_names_its_real_files(tmp_path, kind):
    root = _generate(tmp_path, kind)
    readme = (root / "README.md").read_text()
    template = TemplateFactory.create_template(kind, "p")
    assert f"pipelines/{template.DEFAULT_PIPELINE}.yaml" in readme
    assert "config/" not in readme.replace(".ducta/schema/", "")
    for path in template.seed_files():
        assert (root / path).is_file()
