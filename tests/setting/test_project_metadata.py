"""Recognised `metadata` keys (ADR 0001): checked when present, free-form otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ducta.setting.project_loader import validate_project
from ducta.setting.project_schema import CatalogEntry, PipelineFile, check_metadata

DEMOS = Path.home() / "Desktop" / "demo_ducta" / "projects"


@pytest.mark.parametrize(
    "meta",
    [
        {},
        {"owner": "data-team", "tags": ["silver"], "sla": "daily 06:00"},
        {"sla": "6h", "pii": ["email"], "criticality": "high", "docs": "https://x.io/a"},
        {"sla": "hourly", "anything": {"else": 1}},
    ],
)
def test_valid_metadata(meta):
    assert check_metadata(meta) == meta


@pytest.mark.parametrize(
    "meta, needle",
    [
        ({"owner": ""}, "owner"),
        ({"tags": "silver"}, "tags"),
        ({"pii": [1]}, "pii"),
        ({"sla": "whenever"}, "sla"),
        ({"criticality": "urgent"}, "criticality"),
        ({"docs": "not a url"}, "docs"),
    ],
)
def test_invalid_metadata(meta, needle):
    with pytest.raises(ValueError, match=needle):
        check_metadata(meta)


def test_pipeline_node_and_dataset_all_check_it():
    with pytest.raises(ValidationError, match="criticality"):
        PipelineFile.model_validate({"metadata": {"criticality": "x"}})
    with pytest.raises(ValidationError, match="sla"):
        PipelineFile.model_validate({"nodes": {"a": {"run": "m:f", "metadata": {"sla": "soon"}}}})
    with pytest.raises(ValidationError, match="pii"):
        CatalogEntry.model_validate({"format": "parquet", "metadata": {"pii": "email"}})
    entry = CatalogEntry.model_validate({"format": "parquet", "metadata": {"pii": ["email"]}})
    assert entry.metadata == {"pii": ["email"]}


@pytest.mark.skipif(not DEMOS.is_dir(), reason="demo_ducta projects not on this machine")
@pytest.mark.parametrize("name", ["batch", "streaming", "hybrid"])
def test_the_demo_projects_still_validate(name):
    validate_project(DEMOS / name)


def test_alert_rules_are_checked():
    from ducta.setting.project_schema import ProjectFile

    base = {"version": 2, "project": "p", "paths": {"input": "d", "output": "d"}}
    ok = ProjectFile.model_validate(
        {
            **base,
            "alerts": [
                {"when": ["failure"], "channels": [{"type": "slack", "webhook_env": "SLACK_URL"}]}
            ],
        }
    )
    assert ok.alerts[0].pipelines == ["*"]
    with pytest.raises(ValidationError, match="webhook_env"):
        ProjectFile.model_validate(
            {**base, "alerts": [{"when": ["failure"], "channels": [{"type": "slack"}]}]}
        )
    with pytest.raises(ValidationError):
        ProjectFile.model_validate(
            {
                **base,
                "alerts": [{"on": ["exploded"], "channels": [{"type": "email", "to": ["a@b.c"]}]}],
            }
        )
