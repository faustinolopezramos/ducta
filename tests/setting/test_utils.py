"""Unit tests for ducta.setting.utils.deep_merge_dicts.

Regression: an empty dict `{}` override for a key was a no-op — merging
`deep_merge_dicts(existing_dict, {})` just recurses and returns `existing`
unchanged, so a child/env config had no way to say "clear this whole
section" the base declared. `None` (delete key) and `{"__reset__": true}`
(replace outright) sentinels now express that.
"""

from __future__ import annotations

from ducta.setting.utils import deep_merge_dicts


class TestDeepMergeDictsBasic:
    def test_merges_nested_dicts(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3}}
        assert deep_merge_dicts(base, override) == {"a": {"x": 1, "y": 3}}

    def test_non_dict_override_replaces(self):
        base = {"a": {"x": 1}}
        override = {"a": "scalar"}
        assert deep_merge_dicts(base, override) == {"a": "scalar"}

    def test_neither_input_mutated(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = deep_merge_dicts(base, override)
        assert base == {"a": {"x": 1}}
        assert override == {"a": {"y": 2}}
        assert result == {"a": {"x": 1, "y": 2}}

    def test_empty_dict_override_is_still_a_no_op_merge(self):
        # Not a "clear this section" signal — {} merges as empty, keeping
        # whatever base already had. Use None or __reset__ for that.
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {}}
        assert deep_merge_dicts(base, override) == {"a": {"x": 1, "y": 2}}


class TestDeepMergeDictsNullDeletesKey:
    def test_none_value_removes_the_key(self):
        base = {"a": {"x": 1}, "b": 2}
        override = {"a": None}
        assert deep_merge_dicts(base, override) == {"b": 2}

    def test_none_value_for_missing_key_is_a_no_op(self):
        base = {"b": 2}
        override = {"a": None}
        assert deep_merge_dicts(base, override) == {"b": 2}


class TestDeepMergeDictsResetSentinel:
    def test_reset_replaces_nested_dict_outright(self):
        base = {"quality": {"checks": {"row_count": {"min": 10}}, "profile": "strict"}}
        override = {"quality": {"__reset__": True, "checks": {}}}
        result = deep_merge_dicts(base, override)
        # Only what's in the reset dict survives — "profile" from base is gone.
        assert result == {"quality": {"checks": {}}}

    def test_reset_marker_itself_is_stripped(self):
        base = {"a": {"old": 1}}
        override = {"a": {"__reset__": True, "new": 2}}
        result = deep_merge_dicts(base, override)
        assert "__reset__" not in result["a"]
        assert result == {"a": {"new": 2}}
