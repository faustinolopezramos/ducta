"""Tests for dataset reference resolution.

A node declares its I/O as reference names into ``input_config`` /
``output_config``, and nothing resolved those references before: the schema
endpoint reported ``format="unknown"`` with ``path``/``schema`` always null,
while the UI hard-coded ``"parquet"`` for every dataset. These tests pin the
resolution down, including the cases where the honest answer is "undeclared".
"""

from __future__ import annotations

import textwrap

import pytest

from ducta.api.services.dataset_service import DatasetService, io_names, node_io
from ducta.api.services.node_service import NodeService
from ducta.api.services.project import ProjectService


def _write(path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path):
    """A workspace whose registries declare different formats per side.

    ``bronze.raw_results`` is landed as csv and written as parquet — a real
    distinction the old code could not express, since it invented one format
    for both sides.
    """
    _write(
        tmp_path / "environment.yaml",
        """
        base_path: "."
        env_config:
          base:
            global_config_path: "config/global.yaml"
            pipelines_config_path: "config/pipelines.yaml"
            nodes_config_path: "config/nodes.yaml"
            input_config_path: "config/input.yaml"
            output_config_path: "config/output.yaml"
        """,
    )
    for name in ("global", "pipelines", "nodes"):
        _write(tmp_path / "config" / f"{name}.yaml", "{}\n")
    _write(
        tmp_path / "config" / "input.yaml",
        """
        bronze.raw_results:
          format: csv
          filepath: "${DATA_ROOT}/landing/results.csv"
        silver.clean_results:
          format: delta
          filepath: "${DATA_ROOT}/silver/clean"
          schema: "id BIGINT, name STRING"
        """,
    )
    _write(
        tmp_path / "config" / "output.yaml",
        """
        bronze.raw_results:
          format: parquet
          filepath: "${DATA_ROOT}/bronze/results"
          write_mode: overwrite
        silver.clean_results:
          format: delta
          filepath: "${DATA_ROOT}/silver/clean"
          write_mode: merge
        gold.standings:
          format: parquet
          filepath: "${DATA_ROOT}/gold/standings"
          write_mode: overwrite
        """,
    )
    _write(
        tmp_path / "projects" / "demo" / "config" / "nodes.yaml",
        """
        ingest_results:
          module: src.ingest
          function: run
          output: ["bronze.raw_results"]
        clean_results:
          module: src.clean
          function: run
          input: ["bronze.raw_results"]
          output: ["silver.clean_results"]
        build_standings:
          module: src.standings
          function: run
          input: ["silver.clean_results"]
          output: ["gold.standings", "gold.never_declared"]
        """,
    )
    _write(
        tmp_path / "projects" / "demo" / "config" / "pipelines.yaml",
        """
        etl_results:
          type: batch
          nodes: [ingest_results, clean_results]
        etl_reporting:
          type: batch
          nodes: [build_standings]
        """,
    )
    return tmp_path


@pytest.fixture
def service(workspace):
    return DatasetService(workspace, ProjectService(workspace), NodeService(root=workspace))


class TestIoNames:
    def test_a_list_of_strings_passes_through(self):
        assert io_names(["a", "b"]) == ["a", "b"]

    def test_a_bare_string_becomes_one_name(self):
        assert io_names("a") == ["a"]

    def test_a_dict_yields_its_keys(self):
        assert io_names({"a": {}, "b": {}}) == ["a", "b"]

    def test_dict_entries_use_name_then_id(self):
        assert io_names([{"name": "a"}, {"id": "b"}]) == ["a", "b"]

    def test_none_is_empty(self):
        assert io_names(None) == []

    def test_entries_without_a_name_are_dropped(self):
        assert io_names([{"format": "parquet"}]) == []


class TestNodeIo:
    def test_the_canonical_singular_key_is_read(self):
        assert node_io({"input": ["a"]}, "input") == ["a"]

    def test_the_normalized_plural_key_is_read(self):
        assert node_io({"inputs": ["a"]}, "input") == ["a"]

    def test_plural_wins_when_both_are_present(self):
        assert node_io({"inputs": ["a"], "input": ["b"]}, "input") == ["a"]


class TestResolveRef:
    def test_the_output_side_carries_its_own_format_and_write_mode(self, service):
        ref = service.resolve_ref("bronze.raw_results", "output")
        assert ref.declared is True
        assert ref.format == "parquet"
        assert ref.write_mode == "overwrite"
        assert ref.path == "${DATA_ROOT}/bronze/results"

    def test_the_input_side_resolves_independently(self, service):
        """The same name is landed as csv and written as parquet."""
        ref = service.resolve_ref("bronze.raw_results", "input")
        assert ref.format == "csv"
        assert ref.path == "${DATA_ROOT}/landing/results.csv"

    def test_a_declared_schema_is_carried(self, service):
        assert service.resolve_ref("silver.clean_results", "input").schema_ == (
            "id BIGINT, name STRING"
        )

    def test_an_undeclared_reference_reports_itself_as_undeclared(self, service):
        ref = service.resolve_ref("gold.never_declared", "output")
        assert ref.declared is False
        assert ref.format is None
        assert ref.path is None

    def test_the_medallion_layer_comes_from_the_namespace(self, service):
        assert service.resolve_ref("gold.standings", "output").layer == "gold"

    def test_a_name_outside_the_convention_has_no_layer(self, service):
        assert service.resolve_ref("gold.never_declared", "output").layer == "gold"
        assert service.resolve_ref("whatever.thing", "output").layer is None

    def test_the_other_side_is_the_fallback(self, service):
        """``gold.standings`` is only declared as an output; a reader still gets its format."""
        ref = service.resolve_ref("gold.standings", "input")
        assert ref.declared is True
        assert ref.format == "parquet"


class TestProjectRegistry:
    def test_every_referenced_dataset_is_listed(self, service):
        names = [d.name for d in service.list_for_project("demo").datasets]
        assert names == [
            "bronze.raw_results",
            "gold.never_declared",
            "gold.standings",
            "silver.clean_results",
        ]

    def test_producer_and_consumer_are_recovered_from_the_wiring(self, service):
        by_name = {d.name: d for d in service.list_for_project("demo").datasets}
        raw = by_name["bronze.raw_results"]
        assert [p.node for p in raw.producers] == ["ingest_results"]
        assert [c.node for c in raw.consumers] == ["clean_results"]

    def test_a_consumer_in_another_pipeline_is_reported_with_its_pipeline(self, service):
        by_name = {d.name: d for d in service.list_for_project("demo").datasets}
        clean = by_name["silver.clean_results"]
        assert [(c.node, c.pipeline) for c in clean.consumers] == [
            ("build_standings", "etl_reporting")
        ]
        assert [(p.node, p.pipeline) for p in clean.producers] == [("clean_results", "etl_results")]

    def test_declared_in_names_both_registries(self, service):
        by_name = {d.name: d for d in service.list_for_project("demo").datasets}
        assert by_name["bronze.raw_results"].declared_in == ["input", "output"]
        assert by_name["gold.standings"].declared_in == ["output"]
        assert by_name["gold.never_declared"].declared_in == []

    def test_a_produced_dataset_reports_the_output_declaration(self, service):
        """write_mode only exists on the output side, so that side must win."""
        by_name = {d.name: d for d in service.list_for_project("demo").datasets}
        assert by_name["silver.clean_results"].write_mode == "merge"
