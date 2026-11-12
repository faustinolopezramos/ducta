"""A ``run_in_process`` worker of a reproduction reads what the reproduction wrote.

``capture_run_overrides`` carried the redirected outputs but not the inputs
``redirect_writes`` repointed, nor the fallback roots: the worker of a downstream
node read the REAL dataset (review 2026-11-11).
"""

from __future__ import annotations

import pickle

from ducta.core.node_worker import build_node_payload
from ducta.core.scratch import prepare_reproduction
from ducta.core.worker_bootstrap import bootstrap_worker_context, capture_run_overrides
from ducta.setting.project.context import load_project_context

PROJECT = {
    "ducta.yaml": "version: 2\nproject: demo\npaths: {input: data, output: out}\n",
    "catalog.yaml": (
        "raw:\n  format: csv\n  path: ${paths.input}/raw.csv\n"
        "silver.sales.clean: {format: parquet}\n"
        "gold.sales.totals: {format: parquet}\n"
    ),
    "pipelines/etl.yaml": (
        "nodes:\n"
        "  clean:\n    run: pipelines.etl:clean\n    inputs: [raw]\n"
        "    outputs: [silver.sales.clean]\n"
        "  totals:\n    run: pipelines.etl:totals\n    inputs: [silver.sales.clean]\n"
        "    outputs: [gold.sales.totals]\n    run_in_process: true\n"
    ),
}


def _worker_of_a_reproduction(tmp_path, monkeypatch):
    for name, text in PROJECT.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    monkeypatch.chdir(tmp_path)
    _, parent = load_project_context(tmp_path, "dev")
    target = prepare_reproduction(parent, "dev", "abc123", pipeline_name="etl")
    payload = build_node_payload(
        "totals",
        env="dev",
        ml_info={},
        base_path=str(tmp_path),
        output_path=str(parent.output_path),
        overrides=capture_run_overrides(parent),
    )
    payload = pickle.loads(pickle.dumps(payload))  # it crosses a process boundary
    _, worker = bootstrap_worker_context(payload)
    return parent, worker, target


def test_worker_reads_the_upstream_output_of_the_reproduction(tmp_path, monkeypatch):
    parent, worker, target = _worker_of_a_reproduction(tmp_path, monkeypatch)
    read = worker.input_config["silver.sales.clean"]["filepath"]
    assert read == parent.input_config["silver.sales.clean"]["filepath"]
    assert "reproduce" in read and "abc123" in read


def test_worker_keeps_the_fallback_to_the_real_data(tmp_path, monkeypatch):
    parent, worker, _ = _worker_of_a_reproduction(tmp_path, monkeypatch)
    assert worker._read_fallback_paths == parent._read_fallback_paths
    assert worker.global_config["_read_fallback_paths"] == parent._read_fallback_paths


def test_worker_knows_it_is_a_reproduction(tmp_path, monkeypatch):
    # The retrain trigger and the certificate read it: a reproduction must not retrain.
    _, worker, _ = _worker_of_a_reproduction(tmp_path, monkeypatch)
    assert worker.reproduction_of == "abc123"
