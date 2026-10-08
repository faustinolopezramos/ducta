"""The ml_scoring scaffold: train and promote, then score with a serving node."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ducta.check.core import QUALITY_CHECKS_REGISTRY
from ducta.console.template import (
    MLScoringTemplate,
    TemplateFactory,
    TemplateGenerator,
    TemplateType,
)
from ducta.setting.project_loader import ProjectConfigError, compile_project, validate_project
from ducta.setting.project_schema import BUILTIN_SCORER


def _docs(tmp_path: Path) -> dict:
    root = tmp_path / "p"
    TemplateGenerator(root).generate_project(TemplateType.ML_SCORING, "p")
    return compile_project(validate_project(root, "dev"))


def test_it_is_offered():
    listed = {t["type"] for t in TemplateFactory.list_available_templates()}
    assert "ml_scoring" in listed


def test_train_then_score(tmp_path):
    docs = _docs(tmp_path)
    assert {p: c["type"] for p, c in docs["pipelines_config"].items()} == {
        "train": "ml",
        "score": "ml",
    }
    assert docs["nodes_config"]["train"]["ml_stage"] == "training"


def test_the_score_node_serves_production_with_the_builtin_scorer(tmp_path):
    node = _docs(tmp_path)["nodes_config"]["score"]
    assert node["ml_stage"] == "serving"
    assert f"{node['module']}:{node['function']}" == BUILTIN_SCORER
    assert node["model"]["stage"] == "production"
    assert node["model"]["trust_artifact"] is True


def test_the_score_node_checks_its_predictions(tmp_path):
    docs = _docs(tmp_path)
    checks = docs["nodes_config"]["score"]["data_quality"]["checks"]
    assert {"prediction_contract", "prediction_rate", "prediction_drift"} <= set(checks)
    for name in checks:
        assert name in QUALITY_CHECKS_REGISTRY
    # The drift reference is produced by train and readable by score.
    reference = checks["prediction_drift"]["reference"]
    assert reference in docs["output_config"] and reference in docs["input_config"]


def test_the_seed_data_has_signal_and_new_rows_have_no_label():
    files = MLScoringTemplate("p").seed_files()
    known = list(csv.DictReader(io.StringIO(files["data/customers.csv"])))
    new = list(csv.DictReader(io.StringIO(files["data/new_customers.csv"])))
    churn = sum(int(r["churned"]) for r in known) / len(known)
    assert 0.2 < churn < 0.4
    assert "churned" not in new[0] and len(new) == 200
    assert {r["customer_id"] for r in known}.isdisjoint(r["customer_id"] for r in new)


def test_a_check_reference_missing_from_the_catalog_is_reported(tmp_path):
    root = tmp_path / "p"
    TemplateGenerator(root).generate_project(TemplateType.ML_SCORING, "p")
    score = root / "pipelines" / "score.yaml"
    score.write_text(
        score.read_text().replace(
            "reference: gold.churn.validation_scores", "reference: gold.churn.validaton_scores"
        )
    )
    try:
        validate_project(root, "dev")
    except ProjectConfigError as e:
        assert "compares with 'gold.churn.validaton_scores'" in str(e)
        assert "gold.churn.validation_scores" in str(e)  # the suggestion
    else:
        raise AssertionError("a misspelt check reference was accepted")
