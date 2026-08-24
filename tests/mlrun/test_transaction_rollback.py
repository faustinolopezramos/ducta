"""Unit tests for ducta.mlrun.concurrency.SafeTransaction rollback completeness."""

from __future__ import annotations

import pandas as pd
import pytest

from ducta.mlrun.concurrency import SafeTransaction, TransactionError, TransactionState
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


class TestRollbackAfterPartialFailure:
    """A transaction that fails midway must still be rollback-able.

    Regression test for the bug where SafeTransaction.rollback() refused to
    act unless `self.executed` was True — but `executed` is only set after
    *every* operation succeeds, so a failure partway through left earlier
    operations applied with no way to undo them via the public API.
    """

    def test_execute_raises_and_marks_state_failed(self, storage, tmp_path):
        txn = SafeTransaction(storage, lock_path=str(tmp_path / "txn.lock"))
        txn.write_json({"a": "modified"}, "existing.json")
        txn.write_dataframe(pd.DataFrame({"x": [1]}), "brand_new_df.parquet")

        storage.write_dataframe = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("simulated failure mid-transaction")
        )

        with pytest.raises(TransactionError):
            txn.execute()

        assert txn.state == TransactionState.FAILED
        assert txn.executed is False

    def test_rollback_restores_operations_applied_before_the_failure(self, storage, tmp_path):
        storage.write_json({"a": "original"}, "existing.json")

        txn = SafeTransaction(storage, lock_path=str(tmp_path / "txn.lock"))
        txn.write_json({"a": "modified"}, "existing.json")
        txn.write_dataframe(pd.DataFrame({"x": [1]}), "brand_new_df.parquet")

        storage.write_dataframe = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("simulated failure mid-transaction")
        )

        with pytest.raises(TransactionError):
            txn.execute()

        # The first operation was already applied before the second failed —
        # this is the state the old code left permanently in place.
        assert storage.read_json("existing.json") == {"a": "modified"}

        assert txn.rollback() is True
        assert storage.read_json("existing.json") == {"a": "original"}
        assert txn.state == TransactionState.ROLLED_BACK

    def test_rollback_on_a_never_executed_transaction_still_refuses(self, storage, tmp_path):
        txn = SafeTransaction(storage, lock_path=str(tmp_path / "txn.lock"))
        txn.write_json({"a": 1}, "brand_new.json")

        assert txn.rollback() is False


class TestArtifactSnapshotFailureIsNotTreatedAsNotExisted:
    """A backup failure for a *pre-existing* artifact must not be confused
    with "this path didn't exist" — the old code let rollback delete a real
    artifact it never actually captured a copy of.
    """

    def test_rollback_refuses_to_delete_artifact_whose_backup_failed(self, storage, tmp_path):
        original_content = tmp_path / "original_model.bin"
        original_content.write_bytes(b"original-weights")
        storage.write_artifact(str(original_content), "model.bin")
        assert storage.exists("model.bin")

        new_content = tmp_path / "new_model.bin"
        new_content.write_bytes(b"new-weights")

        txn = SafeTransaction(storage, lock_path=str(tmp_path / "txn.lock"))
        txn.write_artifact(str(new_content), "model.bin")

        original_read_artifact = storage.read_artifact
        storage.read_artifact = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("simulated backup failure")
        )
        try:
            assert txn.execute() is True
        finally:
            storage.read_artifact = original_read_artifact

        # The rollback for this operation must refuse (nothing to restore
        # from), not delete the artifact the transaction just wrote.
        assert txn.rollback() is False
        assert storage.exists("model.bin")
