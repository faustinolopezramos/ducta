"""Unit tests for ducta.core.dependency_resolver."""

from __future__ import annotations

import pytest

from ducta.core.dependency_resolver import DependencyResolver, detect_cycles_dfs


class TestDetectCyclesDfs:
    def test_acyclic_graph_ok(self):
        # returns None (no raise) for a DAG
        assert detect_cycles_dfs({"a": ["b"], "b": ["c"], "c": []}) is None

    def test_self_loop_detected(self):
        with pytest.raises(ValueError, match="Circular dependency"):
            detect_cycles_dfs({"a": ["a"]})

    def test_cycle_detected(self):
        with pytest.raises(ValueError, match="Circular dependency"):
            detect_cycles_dfs({"a": ["b"], "b": ["c"], "c": ["a"]})


class TestBuildDependencyGraph:
    def test_linear_chain(self):
        nodes = ["a", "b", "c"]
        cfgs = {
            "a": {},
            "b": {"dependencies": ["a"]},
            "c": {"dependencies": ["b"]},
        }
        dag = DependencyResolver.build_dependency_graph(nodes, cfgs)
        # dag maps a node -> set of its dependents
        assert dag["a"] == {"b"}
        assert dag["b"] == {"c"}
        assert dag["c"] == set()

    def test_dependency_outside_pipeline_raises(self):
        nodes = ["a"]
        cfgs = {"a": {"dependencies": ["ghost"]}}
        with pytest.raises(ValueError, match="not in the pipeline"):
            DependencyResolver.build_dependency_graph(nodes, cfgs)

    def test_inferred_edge_from_dataset_flow(self):
        # b consumes what a produces -> b depends on a, even without `dependencies`
        nodes = ["a", "b"]
        cfgs = {
            "a": {"output": ["ds_x"]},
            "b": {"input": ["ds_x"]},
        }
        dag = DependencyResolver.build_dependency_graph(nodes, cfgs)
        assert dag["a"] == {"b"}


class TestTopologicalSort:
    def test_orders_dependencies_first(self):
        dag = {"a": {"b"}, "b": {"c"}, "c": set()}
        order = DependencyResolver.topological_sort(dag)
        assert order.index("a") < order.index("b") < order.index("c")

    def test_all_nodes_present(self):
        dag = {"a": {"c"}, "b": {"c"}, "c": set()}
        order = DependencyResolver.topological_sort(dag)
        assert set(order) == {"a", "b", "c"}
        assert order.index("c") == 2

    def test_cycle_raises(self):
        dag = {"a": {"b"}, "b": {"a"}}
        with pytest.raises(ValueError, match="Circular dependency"):
            DependencyResolver.topological_sort(dag)

    def test_independent_nodes_ordered_by_dict_insertion_not_hash_order(self):
        # Independent nodes (no deps among them) inserted in a deliberately
        # non-alphabetical order. Before the fix, seeding the ready-queue from
        # `set(dag.keys())` meant this order depended on Python's per-process
        # hash randomization, not the dict's (== pipeline declaration) order.
        dag = {"zeta": set(), "alpha": set(), "mu": set()}
        order = DependencyResolver.topological_sort(dag)
        assert order == ["zeta", "alpha", "mu"]

    def test_order_is_stable_across_repeated_calls(self):
        dag = {"zeta": set(), "alpha": {"mu"}, "mu": set()}
        first = DependencyResolver.topological_sort(dag)
        for _ in range(20):
            assert DependencyResolver.topological_sort(dag) == first
