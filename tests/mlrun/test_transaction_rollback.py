"""Unit tests for ducta.mlrun.concurrency.SafeTransaction rollback completeness."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.mlrun.concurrency import SafeTransaction
from ducta.mlrun.storage import LocalStorageBackend


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)


class TestRollbackDeletesNewlyCreatedPaths:
    def test_rollback_deletes_newly_created_json(self, storage, tmp_path):
        txn = SafeTransaction(storage, lock_path=str(tmp_path / "txn.lock"))
        txn.write_json({"a": 1}, "brand_new.json")
        assert txn.execute() is True
        assert storage.exists("brand_new.json")

        txn.rollback()

        assert not storage.exists("brand_new.json")

    def test_rollback_deletes_newly_created_dataframe(self, storage, tmp_path):
        # Explicit .parquet suffix: write_dataframe() auto-appends it when
        # absent, but read_dataframe()/exists()/delete() don't — passing a
        # fully-qualified path (as every real caller in this codebase does)
        # keeps this test isolated to the rollback behavior being verified.
        df = pd.DataFrame({"x": [1, 2, 3]})
        txn = SafeTransaction(storage, lock_path=str(tmp_path / "txn.lock"))
        txn.write_dataframe(df, "brand_new_df.parquet")
        assert txn.execute() is True
        assert storage.exists("brand_new_df.parquet")

        txn.rollback()

        assert not storage.exists("brand_new_df.parquet")

    def test_rollback_restores_previous_json_content(self, storage, tmp_path):
        storage.write_json({"a": "original"}, "existing.json")

        txn = SafeTransaction(storage, lock_path=str(tmp_path / "txn.lock"))
        txn.write_json({"a": "modified"}, "existing.json")
        assert txn.execute() is True
        assert storage.read_json("existing.json") == {"a": "modified"}

        txn.rollback()

        assert storage.read_json("existing.json") == {"a": "original"}
