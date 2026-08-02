"""Unit tests for ducta.core.dependency_inference."""

from __future__ import annotations

from ducta.core.dependency_inference import (
    build_producer_map,
    extract_input_keys,
    extract_output_keys,
    infer_pipeline_depends_on,
    merge_pipeline_depends_on,
    resolve_node_dependencies,
)


class TestExtractKeys:
    def test_string_input(self):
        assert extract_input_keys({"input": "ds1"}) == ["ds1"]

    def test_list_input(self):
        assert extract_input_keys({"input": ["a", "b"]}) == ["a", "b"]

    def test_named_map_input(self):
        assert extract_input_keys({"input": {"df1": "a", "df2": "b"}}) == ["a", "b"]

    def test_none_and_empty(self):
        assert extract_input_keys({}) == []
        assert extract_input_keys({"input": None}) == []
        assert extract_output_keys({"output": []}) == []

    def test_output_keys(self):
        assert extract_output_keys({"output": ["out1"]}) == ["out1"]

    def test_whitespace_stripped_and_blanks_dropped(self):
        assert extract_input_keys({"input": [" a ", "", "b"]}) == ["a", "b"]


class TestProducerMap:
    def test_maps_dataset_to_producer(self):
        cfgs = {"a": {"output": ["x"]}, "b": {"output": ["y", "x"]}}
        pmap = build_producer_map(["a", "b"], cfgs)
        assert pmap["x"] == ["a", "b"]
        assert pmap["y"] == ["b"]


class TestResolveNodeDependencies:
    def test_explicit_only(self):
        cfgs = {"a": {}, "b": {"dependencies": ["a"]}}
        resolved = resolve_node_dependencies(["a", "b"], cfgs, warn=False)
        assert resolved["b"] == ["a"]

    def test_inferred_from_dataset(self):
        cfgs = {"a": {"output": ["x"]}, "b": {"input": ["x"]}}
        resolved = resolve_node_dependencies(["a", "b"], cfgs, warn=False)
        assert resolved["b"] == ["a"]

    def test_explicit_union_inferred_no_duplicates(self):
        cfgs = {
            "a": {"output": ["x"]},
            "b": {"input": ["x"], "dependencies": ["a"]},
        }
        resolved = resolve_node_dependencies(["a", "b"], cfgs, warn=False)
        assert resolved["b"] == ["a"]  # not ["a", "a"]

    def test_node_does_not_depend_on_itself(self):
        cfgs = {"a": {"input": ["x"], "output": ["x"]}}
        resolved = resolve_node_dependencies(["a"], cfgs, warn=False)
        assert resolved["a"] == []


class TestPipelineDependsOn:
    def test_infer_cross_pipeline(self):
        pipelines = {"p1": {"nodes": ["a"]}, "p2": {"nodes": ["b"]}}
        nodes = {"a": {"output": ["x"]}, "b": {"input": ["x"]}}
        inferred = infer_pipeline_depends_on(pipelines, nodes)
        assert inferred["p2"] == ["p1"]
        assert inferred["p1"] == []

    def test_merge_explicit_and_inferred(self):
        pipelines = {
            "p1": {"nodes": ["a"]},
            "p2": {"nodes": ["b"], "depends_on": ["p0"]},
        }
        nodes = {"a": {"output": ["x"]}, "b": {"input": ["x"]}}
        merged = merge_pipeline_depends_on(pipelines, nodes)
        assert set(merged["p2"]) == {"p0", "p1"}
