"""Regression: `resolve_execution_chain` silently produced wrong/partial chains.

Two independent defects, both invisible at runtime:

1. A cycle in `depends_on` made Kahn's algorithm emit a *truncated* chain — empty
   when the target itself sits in the cycle. `run_pipeline_chain` then iterated
   nothing and returned None: the user asked for a pipeline, none ran, exit 0.
2. The subgraph was ordered by iterating a `set`, so independent ancestors ran in
   a different order on every process (string hash randomization) — undermining
   the reproducibility guarantee `DependencyResolver.topological_sort` documents
   and implements one level down, for nodes.
"""

from __future__ import annotations

import pytest

from ducta.setting.pipeline_dependency_resolver import PipelineDependencyResolver


def _chain(target, cfg, depends_on_map=None):
    return PipelineDependencyResolver.resolve_execution_chain(target, cfg, depends_on_map)


class TestCycleDetection:
    def test_direct_cycle_raises_instead_of_returning_empty_chain(self):
        cfg = {"a": {"depends_on": ["b"]}, "b": {"depends_on": ["a"]}}

        with pytest.raises(ValueError, match="[Cc]ircular|cycle"):
            _chain("a", cfg)

    def test_transitive_cycle_raises(self):
        cfg = {
            "a": {"depends_on": ["b"]},
            "b": {"depends_on": ["c"]},
            "c": {"depends_on": ["a"]},
        }

        with pytest.raises(ValueError, match="[Cc]ircular|cycle"):
            _chain("a", cfg)

    def test_cycle_among_ancestors_raises_even_when_target_is_outside_it(self):
        # target -> a, and a <-> b form a cycle upstream of it.
        cfg = {
            "target": {"depends_on": ["a"]},
            "a": {"depends_on": ["b"]},
            "b": {"depends_on": ["a"]},
        }

        with pytest.raises(ValueError, match="[Cc]ircular|cycle"):
            _chain("target", cfg)

    def test_cycle_is_detected_through_the_depends_on_map_override(self):
        # The inferred/merged map is what run_pipeline_chain actually passes.
        cfg = {"a": {}, "b": {}}
        depends_on_map = {"a": ["b"], "b": ["a"]}

        with pytest.raises(ValueError, match="[Cc]ircular|cycle"):
            _chain("a", cfg, depends_on_map)


class TestChainCorrectness:
    def test_no_dependencies_returns_just_the_target(self):
        assert _chain("solo", {"solo": {}}) == ["solo"]

    def test_target_runs_last_and_ancestors_precede_their_dependents(self):
        cfg = {
            "raw": {},
            "clean": {"depends_on": ["raw"]},
            "report": {"depends_on": ["clean"]},
        }

        assert _chain("report", cfg) == ["raw", "clean", "report"]

    def test_unrelated_pipelines_are_excluded(self):
        cfg = {
            "raw": {},
            "clean": {"depends_on": ["raw"]},
            "unrelated": {},
        }

        assert _chain("clean", cfg) == ["raw", "clean"]

    def test_diamond_dependency_visits_each_pipeline_once(self):
        cfg = {
            "root": {},
            "left": {"depends_on": ["root"]},
            "right": {"depends_on": ["root"]},
            "join": {"depends_on": ["left", "right"]},
        }

        chain = _chain("join", cfg)

        assert len(chain) == len(set(chain)) == 4
        assert chain[0] == "root"
        assert chain[-1] == "join"


class TestDeterminism:
    def test_independent_ancestors_follow_declaration_order(self):
        # Four same-rank ancestors: the tie-break must be the order they are
        # declared in pipelines_config, not set-iteration order.
        cfg = {
            "delta": {},
            "beta": {},
            "gamma": {},
            "alpha": {},
            "t": {"depends_on": ["alpha", "beta", "gamma", "delta"]},
        }

        chain = _chain("t", cfg)

        assert chain == ["delta", "beta", "gamma", "alpha", "t"]

    def test_result_is_stable_across_repeated_calls(self):
        cfg = {
            "alpha": {},
            "beta": {},
            "gamma": {},
            "delta": {},
            "t": {"depends_on": ["alpha", "beta", "gamma", "delta"]},
        }

        results = {tuple(_chain("t", cfg)) for _ in range(25)}

        assert len(results) == 1

    def test_ordering_is_stable_under_hash_randomization(self):
        """The real regression: run the resolver in fresh subprocesses.

        PYTHONHASHSEED differs per process, which is precisely what made the
        previous `list(ancestors | {target})` non-deterministic. Repeating the
        call inside one process cannot catch it — the seed is fixed there.
        """
        import subprocess
        import sys
        import textwrap
        from pathlib import Path

        src = str(Path(__file__).resolve().parents[2] / "src")
        script = (
            textwrap.dedent(
                """
            import sys
            sys.path.insert(0, %r)
            from ducta.setting.pipeline_dependency_resolver import PipelineDependencyResolver as R
            cfg = {
                "alpha": {}, "beta": {}, "gamma": {}, "delta": {}, "epsilon": {},
                "t": {"depends_on": ["alpha", "beta", "gamma", "delta", "epsilon"]},
            }
            print(",".join(R.resolve_execution_chain("t", cfg)))
            """
            )
            % src
        )

        seen = set()
        for seed in ("0", "1", "42", "12345", "99999"):
            out = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={"PYTHONHASHSEED": seed, "PATH": ""},
            )
            assert out.returncode == 0, out.stderr
            seen.add(out.stdout.strip())

        assert len(seen) == 1, f"chain order varied across hash seeds: {seen}"
