"""Unit tests for StorageBackend.append_lines (O(new) incremental writes).

LocalStorageBackend overrides this with a real open("a") append; the ABC's
default (read-modify-write via read_json/write_json) is exercised through a
minimal in-memory subclass so a third-party backend that doesn't override
append_lines still behaves correctly.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ducta.mlrun.storage import LocalStorageBackend, StorageBackend, StorageMetadata


def _storage(tmp_path):
    return LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)


class TestLocalStorageBackendAppendLines:
    def test_creates_file_when_absent(self, tmp_path):
        storage = _storage(tmp_path)
        storage.append_lines(['{"a": 1}'], "runs/metrics.jsonl")

        full_path = tmp_path / "mlops" / "runs" / "metrics.jsonl"
        assert full_path.exists()
        assert full_path.read_text(encoding="utf-8") == '{"a": 1}\n'

    def test_appends_without_touching_existing_content(self, tmp_path):
        storage = _storage(tmp_path)
        storage.append_lines(['{"a": 1}'], "runs/metrics.jsonl")
        storage.append_lines(['{"a": 2}', '{"a": 3}'], "runs/metrics.jsonl")

        full_path = tmp_path / "mlops" / "runs" / "metrics.jsonl"
        lines = full_path.read_text(encoding="utf-8").splitlines()
        assert lines == ['{"a": 1}', '{"a": 2}', '{"a": 3}']

    def test_sequential_appends_do_not_clobber_each_other(self, tmp_path):
        storage = _storage(tmp_path)
        for i in range(20):
            storage.append_lines([f'{{"i": {i}}}'], "runs/metrics.jsonl")

        full_path = tmp_path / "mlops" / "runs" / "metrics.jsonl"
        lines = full_path.read_text(encoding="utf-8").splitlines()
        assert lines == [f'{{"i": {i}}}' for i in range(20)]

    def test_no_suffix_defaults_to_jsonl(self, tmp_path):
        storage = _storage(tmp_path)
        storage.append_lines(["x"], "runs/metrics")
        assert (tmp_path / "mlops" / "runs" / "metrics.jsonl").exists()


class _InMemoryBackend(StorageBackend):
    """Minimal backend exercising only the ABC's default append_lines
    fallback (read-modify-write via read_json/write_json) — never overridden."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    def write_dataframe(self, df, path, mode="overwrite"):  # pragma: no cover - unused
        raise NotImplementedError

    def read_dataframe(self, path):  # pragma: no cover - unused
        raise NotImplementedError

    def write_json(self, data, path, mode="overwrite"):
        self._store[path] = dict(data)
        return StorageMetadata(path=path, created_at="", updated_at="", size_bytes=0, format="json")

    def read_json(self, path):
        if path not in self._store:
            raise FileNotFoundError(path)
        return self._store[path]

    def write_artifact(self, artifact_path, destination, mode="overwrite"):  # pragma: no cover
        raise NotImplementedError

    def read_artifact(self, path, local_destination):  # pragma: no cover - unused
        raise NotImplementedError

    def exists(self, path):
        return path in self._store

    def list_paths(self, prefix):  # pragma: no cover - unused
        return [p for p in self._store if p.startswith(prefix)]

    def delete(self, path):
        self._store.pop(path, None)


class TestDefaultAppendLinesFallback:
    def test_creates_the_lines_wrapper_when_absent(self):
        backend = _InMemoryBackend()
        backend.append_lines(["a", "b"], "metrics")
        assert backend.read_json("metrics") == {"lines": ["a", "b"]}

    def test_appends_onto_existing_lines(self):
        backend = _InMemoryBackend()
        backend.append_lines(["a"], "metrics")
        backend.append_lines(["b", "c"], "metrics")
        assert backend.read_json("metrics") == {"lines": ["a", "b", "c"]}

    def test_never_loses_prior_lines_on_repeated_calls(self):
        backend = _InMemoryBackend()
        expected: List[str] = []
        for i in range(10):
            backend.append_lines([str(i)], "metrics")
            expected.append(str(i))
        assert backend.read_json("metrics")["lines"] == expected
