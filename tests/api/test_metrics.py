"""Metrics from run certificates, and freshness against metadata.sla."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ducta.api.services.metrics import freshness, project_metrics, sla_deadline

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _cert(pipeline, hours_ago, status="success", seconds=10.0, nodes=None):
    return {
        "pipeline": pipeline,
        "status": status,
        "started_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "duration_seconds": seconds,
        "nodes": nodes or [],
    }


def test_sla_deadlines():
    assert sla_deadline("6h", NOW) == NOW - timedelta(hours=6)
    assert sla_deadline("daily 06:00", NOW) == NOW.replace(hour=6, minute=0)
    assert sla_deadline("daily 18:00", NOW) == NOW.replace(hour=18) - timedelta(days=1)
    assert sla_deadline("hourly", NOW) == NOW - timedelta(hours=1)
    assert sla_deadline("whenever", NOW) is None


def test_freshness():
    assert freshness(NOW - timedelta(hours=1), "daily 06:00", NOW) == "ok"
    assert freshness(NOW - timedelta(hours=7), "daily 06:00", NOW) == "late"
    assert freshness(None, "6h", NOW) == "late"
    assert freshness(None, None, NOW) == "no_sla"


def test_pipeline_and_node_metrics():
    certs = [
        _cert(
            "etl", 50, seconds=10, nodes=[{"name": "a", "status": "success", "duration_seconds": 4}]
        ),
        _cert(
            "etl",
            26,
            status="failed",
            seconds=2,
            nodes=[{"name": "a", "status": "failed", "duration_seconds": 1}],
        ),
        _cert(
            "etl", 2, seconds=30, nodes=[{"name": "a", "status": "success", "duration_seconds": 8}]
        ),
        _cert("etl", 24 * 40, seconds=99),  # outside the 30-day window
    ]
    result = project_metrics(certs, {"etl": "daily 06:00", "other": "6h"}, days=30, now=NOW)
    etl = next(p for p in result["pipelines"] if p["pipeline"] == "etl")
    assert etl["runs"] == 3
    assert etl["success_rate"] == round(2 / 3, 3)
    assert etl["p50_seconds"] == 10
    assert etl["last_status"] == "success"
    assert etl["freshness"] == "ok"
    assert [t["seconds"] for t in etl["trend"]] == [10, 2, 30]
    other = next(p for p in result["pipelines"] if p["pipeline"] == "other")
    assert (other["runs"], other["freshness"]) == (0, "late")
    [node] = result["nodes"]
    assert (node["node"], node["runs"], node["failures"], node["p50_seconds"]) == ("a", 3, 1, 4)
