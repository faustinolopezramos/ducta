"""Unit tests for ducta.setting.utils (deep_merge, leaves)."""

from __future__ import annotations

from ducta.setting.utils import deep_merge, leaves


class TestDeepMerge:
    def test_merges_nested_dicts(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3}}
        assert deep_merge(base, override) == {"a": {"x": 1, "y": 3}}

    def test_scalars_and_lists_replace(self):
        assert deep_merge({"a": {"x": 1}}, {"a": "scalar"}) == {"a": "scalar"}
        assert deep_merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}

    def test_none_is_a_value_not_a_deletion(self):
        assert deep_merge({"a": 1, "b": 2}, {"a": None}) == {"a": None, "b": 2}

    def test_empty_dict_override_keeps_what_base_had(self):
        assert deep_merge({"a": {"x": 1}}, {"a": {}}) == {"a": {"x": 1}}

    def test_inputs_are_not_modified_and_override_is_copied(self):
        base = {"a": {"x": [1]}}
        override = {"b": {"y": [2]}}
        result = deep_merge(base, override)
        result["b"]["y"].append(9)
        assert override == {"b": {"y": [2]}}
        assert base == {"a": {"x": [1]}}

    def test_non_mapping_base_is_replaced(self):
        assert deep_merge(None, {"a": 1}) == {"a": 1}


class TestLeaves:
    def test_flattens_nested_mappings_to_paths(self):
        assert leaves({"a": {"b": 1, "c": {"d": 2}}, "e": 3}) == {
            ("a", "b"): 1,
            ("a", "c", "d"): 2,
            ("e",): 3,
        }

    def test_empty_mapping_is_a_leaf(self):
        assert leaves({"a": {}}) == {("a",): {}}

    def test_prefix_is_prepended(self):
        assert leaves({"b": 1}, ("a",)) == {("a", "b"): 1}

    def test_keys_are_strings(self):
        assert leaves({1: {2: "x"}}) == {("1", "2"): "x"}
