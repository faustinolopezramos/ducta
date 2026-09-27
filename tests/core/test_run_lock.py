"""Run lock: at most one run writes a given output dataset at a time."""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import threading
import time
from pathlib import Path

import pytest

from ducta.core.errors import PipelineLockedError
from ducta.core.run_lock import (
    RunLock,
    RunLockSettings,
    _FileLeaseStore,
    _S3LeaseStore,
    lock_filename,
    output_keys,
)
from ducta.core.settings import CoreSettings


def _lock(tmp_path: Path, keys, run_id="r1", backend="local", **overrides) -> RunLock:
    settings = RunLockSettings(backend=backend, lock_dir=str(tmp_path), **overrides)
    return RunLock(settings, keys, pipeline="p", run_id=run_id)


@pytest.mark.parametrize("backend", ["local", "storage"])
class TestExclusion:
    def test_second_run_on_same_output_is_locked(self, tmp_path, backend):
        first = _lock(tmp_path, ["core.sales"], "r1", backend)
        first.acquire()
        try:
            with pytest.raises(PipelineLockedError) as exc:
                _lock(tmp_path, ["core.sales"], "r2", backend).acquire()
            assert exc.value.key == "core.sales"
            assert exc.value.holder["run_id"] == "r1"
            assert exc.value.exit_code == 7
        finally:
            first.release()

    def test_released_lock_can_be_taken_again(self, tmp_path, backend):
        with _lock(tmp_path, ["core.sales"], "r1", backend):
            pass
        with _lock(tmp_path, ["core.sales"], "r2", backend):
            pass

    def test_disjoint_outputs_do_not_block_each_other(self, tmp_path, backend):
        with _lock(tmp_path, ["core.a"], "r1", backend):
            with _lock(tmp_path, ["core.b"], "r2", backend):
                pass

    def test_overlap_on_any_key_blocks_and_takes_nothing(self, tmp_path, backend):
        with _lock(tmp_path, ["core.b"], "r1", backend):
            blocked = _lock(tmp_path, ["core.a", "core.b"], "r2", backend)
            with pytest.raises(PipelineLockedError):
                blocked.acquire()
            # All-or-nothing: core.a must not stay held by the failed attempt.
            with _lock(tmp_path, ["core.a"], "r3", backend):
                pass

    def test_wait_mode_acquires_once_the_holder_releases(self, tmp_path, backend):
        holder = _lock(tmp_path, ["core.sales"], "r1", backend)
        holder.acquire()
        threading.Timer(1.2, holder.release).start()
        waiter = _lock(
            tmp_path, ["core.sales"], "r2", backend, on_conflict="wait", wait_timeout_seconds=10
        )
        waiter.acquire()
        waiter.release()

    def test_wait_mode_gives_up_after_its_timeout(self, tmp_path, backend):
        with _lock(tmp_path, ["core.sales"], "r1", backend):
            waiter = _lock(
                tmp_path, ["core.sales"], "r2", backend, on_conflict="wait", wait_timeout_seconds=1
            )
            with pytest.raises(PipelineLockedError):
                waiter.acquire()

    def test_disabled_lock_never_blocks(self, tmp_path, backend):
        with _lock(tmp_path, ["core.sales"], "r1", backend):
            _lock(tmp_path, ["core.sales"], "r2", backend, enabled=False).acquire()


class TestStorageLease:
    def _write_lease(self, tmp_path, key, **doc):
        (tmp_path / lock_filename(key)).write_text(json.dumps(doc))

    def test_expired_lease_is_taken_over(self, tmp_path):
        self._write_lease(tmp_path, "core.sales", run_id="dead", expires_at=time.time() - 5)
        lock = _lock(tmp_path, ["core.sales"], "r2", "storage")
        lock.acquire()
        doc = json.loads((tmp_path / lock_filename("core.sales")).read_text())
        assert doc["run_id"] == "r2"
        lock.release()

    def test_live_lease_is_respected(self, tmp_path):
        self._write_lease(tmp_path, "core.sales", run_id="alive", expires_at=time.time() + 60)
        with pytest.raises(PipelineLockedError) as exc:
            _lock(tmp_path, ["core.sales"], "r2", "storage").acquire()
        assert exc.value.holder["run_id"] == "alive"

    def test_heartbeat_keeps_the_lease_alive_past_its_ttl(self, tmp_path):
        holder = _lock(tmp_path, ["core.sales"], "r1", "storage", ttl_seconds=3)
        holder.acquire()
        try:
            time.sleep(4.5)  # longer than the TTL; renewed every second
            with pytest.raises(PipelineLockedError):
                _lock(tmp_path, ["core.sales"], "r2", "storage").acquire()
            assert holder.lost is False
        finally:
            holder.release()

    def test_a_lease_replaced_by_someone_else_is_reported_lost(self, tmp_path):
        holder = _lock(tmp_path, ["core.sales"], "r1", "storage", ttl_seconds=3)
        holder.acquire()
        try:
            self._write_lease(
                tmp_path, "core.sales", run_id="intruder", expires_at=time.time() + 60
            )
            time.sleep(1.5)
            assert holder.lost is True
        finally:
            holder.release()
        # Release must not delete a lease that is not ours.
        doc = json.loads((tmp_path / lock_filename("core.sales")).read_text())
        assert doc["run_id"] == "intruder"

    def test_file_store_replace_is_compare_and_swap(self, tmp_path):
        store = _FileLeaseStore(tmp_path)
        token = store.create("k", b"v1")
        assert store.create("k", b"other") is None
        assert store.replace("k", b"v2", b"stale") is None
        assert store.read("k")[0] == b"v1"
        assert store.replace("k", b"v2", token) == b"v2"
        assert store.read("k")[0] == b"v2"


def _hold_local_lock(lock_dir: str, ready) -> None:
    lock = RunLock(
        RunLockSettings(backend="local", lock_dir=lock_dir),
        ["core.sales"],
        pipeline="p",
        run_id="child",
    )
    lock.acquire()
    ready.set()
    time.sleep(60)


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL")
def test_local_lock_is_released_when_the_holding_process_dies(tmp_path):
    """The point of the OS lock: a crashed run leaves nothing to clean up."""
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    child = ctx.Process(target=_hold_local_lock, args=(str(tmp_path), ready))
    child.start()
    try:
        assert ready.wait(30)
        with pytest.raises(PipelineLockedError) as exc:
            _lock(tmp_path, ["core.sales"], "parent").acquire()
        assert exc.value.holder["run_id"] == "child"

        os.kill(child.pid, signal.SIGKILL)
        child.join(10)
        with _lock(tmp_path, ["core.sales"], "parent"):
            pass
    finally:
        if child.is_alive():
            child.kill()


class _FakeS3:
    """Just enough of S3 conditional writes to exercise the lease protocol."""

    class Err(Exception):
        def __init__(self, code):
            self.response = {"Error": {"Code": code}}

    def __init__(self):
        self.objects = {}
        self.version = 0

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None):
        current = self.objects.get(Key)
        if IfNoneMatch == "*" and current is not None:
            raise self.Err("PreconditionFailed")
        if IfMatch is not None and (current is None or current[1] != IfMatch):
            raise self.Err("PreconditionFailed")
        self.version += 1
        etag = f'"{self.version}"'
        self.objects[Key] = (Body, etag)
        return {"ETag": etag}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self.Err("NoSuchKey")
        body, etag = self.objects[Key]

        class _B:
            def read(self_inner):
                return body

        return {"Body": _B(), "ETag": etag}

    def delete_object(self, Bucket, Key, IfMatch=None):
        current = self.objects.get(Key)
        if current and IfMatch is not None and current[1] != IfMatch:
            raise self.Err("PreconditionFailed")
        self.objects.pop(Key, None)


def test_s3_lease_protocol_with_conditional_writes():
    store = _S3LeaseStore("s3://bucket/locks/dev", client=_FakeS3())
    settings = RunLockSettings(backend="storage", lock_dir="s3://bucket/locks/dev")
    first = RunLock(settings, ["core.sales"], pipeline="p", run_id="r1", store=store)
    first.acquire()
    with pytest.raises(PipelineLockedError):
        RunLock(settings, ["core.sales"], pipeline="p", run_id="r2", store=store).acquire()
    first.release()
    RunLock(settings, ["core.sales"], pipeline="p", run_id="r3", store=store).acquire()


def test_output_keys_cover_every_node_or_just_one():
    ctx = {
        "nodes_config": {
            "a": {"output": ["core.x", "core.y"]},
            "b": {"output": "core.z"},
        }
    }
    pipeline = {"nodes": ["a", "b"]}
    assert output_keys(ctx, pipeline) == ["core.x", "core.y", "core.z"]
    assert output_keys(ctx, pipeline, node_name="b") == ["core.z"]


class TestSettings:
    def test_defaults(self):
        s = CoreSettings.from_context({"output_path": "/data", "environment": "dev"})
        assert (s.run_lock_enabled, s.run_lock_backend, s.run_lock_on_conflict) == (
            True,
            "local",
            "fail",
        )
        assert s.run_lock_dir.endswith("/.ducta/locks")

    def test_s3_lock_dir_keeps_its_scheme(self):
        s = CoreSettings.from_context(
            {"run_lock": {"backend": "storage", "dir": "s3://bucket/locks"}, "environment": "dev"}
        )
        assert s.run_lock_dir.startswith("s3://bucket/locks/")
