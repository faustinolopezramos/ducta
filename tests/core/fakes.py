"""In-memory doubles for exercising the execution engine without Spark.

``tests/integration`` skips entirely when pyspark is absent, which left the part
of the core most worth covering — the DAG coordination loop, its skip cascades
and its timeout handling — with no end-to-end test at all. Everything that loop
depends on is an injected collaborator, so a handful of small fakes make the
whole engine runnable in-process on plain lists.

The fakes model *behaviour*, not just signatures: dependencies resolve through
the real dependency-inference code, so a test that builds a DAG here exercises
the same resolution the production path uses.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional


class FakeFrame:
    """A stand-in for a DataFrame.

    Exposes ``columns`` so ``PipelineValidator.validate_dataframe_schema``
    accepts it, and carries rows so assertions can follow data through the DAG.
    """

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None, name: str = "frame"):
        self.rows = list(rows or [{"id": 1}])
        self.name = name

    @property
    def columns(self) -> List[str]:
        return list(self.rows[0].keys()) if self.rows else ["id"]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FakeFrame({self.name!r}, {len(self.rows)} rows)"


class FakeContext:
    """The configuration surface the executor reads, with nothing else attached.

    Deliberately not a MagicMock: a mock invents any attribute that is read, so
    a test against one passes whether or not the engine actually consulted the
    thing under test. Attribute access here either returns real configuration or
    raises.
    """

    def __init__(
        self,
        nodes_config: Optional[Dict[str, Dict[str, Any]]] = None,
        pipelines_config: Optional[Dict[str, Any]] = None,
        global_config: Optional[Dict[str, Any]] = None,
        input_config: Optional[Dict[str, Any]] = None,
        output_config: Optional[Dict[str, Any]] = None,
    ):
        self.nodes_config = nodes_config or {}
        self.pipelines_config = pipelines_config or {}
        self.pipelines = self.pipelines_config
        self.input_config = input_config or {}
        self.output_config = output_config or {}
        self.global_config = {
            "preflight_enabled": False,
            "enable_run_certificate": False,
            "mlops_enabled": False,
            "max_parallel_nodes": 4,
            **(global_config or {}),
        }
        self.env = "test"
        self.is_ml_layer = False
        self.spark = None
        self.quality_output_paths: List[Any] = []

    def has_spark_session(self) -> bool:
        return False

    def get_node_ml_config(self, node_name: str) -> Dict[str, Any]:
        return self.nodes_config.get(node_name, {}) or {}

    def add_quality_output_path(self, path: Any) -> None:
        self.quality_output_paths.append(path)


class FakeInputLoader:
    """Serves frames from an in-memory catalog keyed by dataset name."""

    def __init__(self, datasets: Optional[Dict[str, FakeFrame]] = None):
        # `datasets if datasets is not None`, not `datasets or {}`: an empty
        # dict is falsy, so the latter silently swapped in a *new* dict and
        # broke the shared catalog the output manager writes into.
        self.datasets = datasets if datasets is not None else {}
        self.loaded: List[str] = []

    def load_inputs(
        self, node_config: Dict[str, Any], node_name: Optional[str] = None
    ) -> List[FakeFrame]:
        from ducta.gate.exceptions import MissingDependencyError

        frames = []
        for key in _input_keys(node_config):
            self.loaded.append(key)
            if key not in self.datasets:
                if node_config.get("skip_missing_deps"):
                    raise MissingDependencyError(
                        f"Node '{node_name or 'unnamed'}' has missing input(s): {key}"
                    )
                frames.append(FakeFrame(name=key))
            else:
                frames.append(self.datasets[key])
        return frames

    def get_input_param_names(self, node_config: Dict[str, Any]) -> Optional[List[str]]:
        raw = node_config.get("input")
        return list(raw.keys()) if isinstance(raw, dict) else None

    def max_input_mtime(self, node_config: Dict[str, Any]) -> Optional[float]:
        return None


class FakeOutputManager:
    """Records writes into the same catalog the loader reads from.

    Wiring output back into input is what lets a test assert that a downstream
    node genuinely consumed what its upstream produced, rather than that the two
    merely ran in the right order.
    """

    def __init__(self, datasets: Optional[Dict[str, FakeFrame]] = None):
        self.datasets = datasets if datasets is not None else {}
        self.saved: List[str] = []
        self._lock = threading.Lock()

    def save_output(self, env: Optional[str], **params: Any) -> None:
        node = params.get("node") or {}
        frame = params.get("dataframe")
        with self._lock:
            for key in _output_keys(node):
                self.saved.append(key)
                if isinstance(frame, FakeFrame):
                    self.datasets[key] = frame

    def is_output_materialized(self, out_key: str, env: Optional[str] = None) -> bool:
        return out_key in self.datasets

    def output_mtime(self, out_key: str, env: Optional[str] = None) -> Optional[float]:
        return None


class FakeQualityOutputManager:
    """Accepts persistence calls and remembers them, writing nothing."""

    def __init__(self):
        self.persisted: List[Dict[str, Any]] = []

    def persist_quality_report(self, **kwargs: Any) -> None:
        self.persisted.append(kwargs)
        return None


# ── Node functions a test can point a node config at ─────────────────────────

#: Registry the fake module loader resolves against.
FUNCTIONS: Dict[str, Callable] = {}
#: Names of nodes that executed, in completion order (for ordering assertions).
EXECUTED: List[str] = []
_EXECUTED_LOCK = threading.Lock()


def register(name: str, fn: Callable) -> str:
    """Register *fn* under *name* and return the name, for use in a node config."""
    FUNCTIONS[name] = fn
    return name


def reset() -> None:
    """Clear the registry and the execution log between tests."""
    FUNCTIONS.clear()
    with _EXECUTED_LOCK:
        EXECUTED.clear()


def _note(name: str) -> None:
    with _EXECUTED_LOCK:
        EXECUTED.append(name)


def passthrough(name: str) -> Callable:
    """A node that returns its first input (or a fresh frame) and logs that it ran."""

    def fn(*frames, start_date=None, end_date=None, **kwargs):
        _note(name)
        return frames[0] if frames else FakeFrame(name=name)

    return fn


def failing(name: str, exc: Optional[BaseException] = None) -> Callable:
    """A node that raises."""

    def fn(*frames, start_date=None, end_date=None, **kwargs):
        _note(name)
        raise exc or RuntimeError(f"{name} exploded")

    return fn


def slow(name: str, seconds: float) -> Callable:
    """A node that blocks, for exercising timeout handling."""

    def fn(*frames, start_date=None, end_date=None, **kwargs):
        import time

        _note(name)
        time.sleep(seconds)
        return FakeFrame(name=name)

    return fn


def concurrent_probe(name: str, barrier: threading.Barrier) -> Callable:
    """A node that waits on *barrier*, proving nodes really run in parallel."""

    def fn(*frames, start_date=None, end_date=None, **kwargs):
        _note(name)
        barrier.wait(timeout=5)
        return FakeFrame(name=name)

    return fn


class FakeFunctionLoader:
    """Resolves a node's ``function`` against :data:`FUNCTIONS`."""

    def __init__(self, *args: Any, **kwargs: Any):
        pass

    def load(self, node_config: Dict[str, Any]) -> Callable:
        name = node_config.get("function")
        if name not in FUNCTIONS:
            raise ValueError(f"No fake function registered under '{name}'")
        return FUNCTIONS[name]


# ── Config helpers ───────────────────────────────────────────────────────────


def node(
    function: str,
    inputs: Optional[List[str]] = None,
    outputs: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a node config pointing at a registered fake function."""
    cfg: Dict[str, Any] = {"module": "fake", "function": function}
    if inputs:
        cfg["input"] = list(inputs)
    if outputs:
        cfg["output"] = list(outputs)
    cfg.update(extra)
    return cfg


def _input_keys(node_config: Dict[str, Any]) -> List[str]:
    raw = (node_config or {}).get("input") or []
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _output_keys(node_config: Dict[str, Any]) -> List[str]:
    raw = (node_config or {}).get("output") or []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        return list(raw.values())
    return list(raw)
