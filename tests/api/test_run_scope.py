"""What a scoped run covers."""

from __future__ import annotations

import pytest

from ducta.api.services.run_scope import downstream_of, resolve_scope, upstream_of

NODES = {
    "a": {"output": ["x"]},
    "b": {"input": {"x": "x"}, "output": ["y"]},
    "c": {"input": ["y"], "output": ["z"]},
    "d": {"output": ["w"]},
}
MEMBERS = ["a", "b", "c", "d"]


def test_downstream_follows_the_data():
    assert downstream_of("b", MEMBERS, NODES) == ["b", "c"]
    assert downstream_of("a", MEMBERS, NODES) == ["a", "b", "c"]
    assert downstream_of("d", MEMBERS, NODES) == ["d"]


def test_upstream_is_what_a_node_needs():
    assert upstream_of("c", MEMBERS, NODES) == ["a", "b", "c"]
    assert upstream_of("a", MEMBERS, NODES) == ["a"]


def test_scopes():
    assert resolve_scope(None, None, MEMBERS, NODES) is None
    assert resolve_scope("selected", ["c", "a"], MEMBERS, NODES) == ["a", "c"]
    assert resolve_scope("from", ["b"], MEMBERS, NODES) == ["b", "c"]
    assert resolve_scope("until", ["b"], MEMBERS, NODES) == ["a", "b"]
    assert resolve_scope("after", ["b"], MEMBERS, NODES) == ["c"]
    assert resolve_scope("stale", None, MEMBERS, NODES, not_fresh=["c", "zz"]) == ["c"]


@pytest.mark.parametrize(
    "scope, nodes, fresh",
    [
        ("selected", None, None),
        ("from", ["a", "b"], None),
        ("stale", None, []),
        ("x", ["a"], None),
        (None, ["nope"], None),
    ],
)
def test_bad_scopes_explain_themselves(scope, nodes, fresh):
    with pytest.raises(ValueError):
        resolve_scope(scope, nodes, MEMBERS, NODES, not_fresh=fresh)
