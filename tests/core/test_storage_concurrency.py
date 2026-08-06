"""Regression: LocalStorageBackend lost writes, and the two backends disagreed.

`put_object` derived its temp file from `target.with_suffix(".tmp")` — a name
built from the *stem*, so "a/b.json" and "a/b.txt" both mapped to "a/b.tmp".
Two concurrent writers (the same key, or any two keys sharing a stem) raced on
that single path: one torn file, or an `os.replace` of a temp another thread had
already moved, losing a write outright.

`list_objects` additionally resolved its argument as a *directory* here while
`S3StorageBackend` treated it as a key prefix, so the same call returned
different things depending on which backend was configured.
"""

from __future__ import annotations

import threading

import pytest

from ducta.core.storage.base import LocalStorageBackend


@pytest.fixture
def backend(tmp_path):
    return LocalStorageBackend(tmp_path)


class TestPutObjectAtomicity:
    def test_keys_sharing_a_stem_do_not_clobber_each_other(self, backend):
        backend.put_object("a/b.json", b"J" * 1000)
        backend.put_object("a/b.txt", b"T" * 1000)

        assert backend.get_object("a/b.json") == b"J" * 1000
        assert backend.get_object("a/b.txt") == b"T" * 1000

    def test_concurrent_writes_to_stem_sharing_keys_all_survive(self, backend):
        errors: list = []

        def write(key: str, payload: bytes):
            try:
                for _ in range(200):
                    backend.put_object(key, payload * 500)
            except Exception as exc:  # noqa: BLE001 - recorded for the assertion
                errors.append(exc)

        threads = [
            threading.Thread(target=write, args=("a/b.json", b"J")),
            threading.Thread(target=write, args=("a/b.txt", b"T")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent writes raised: {errors[:3]}"
        json_bytes = backend.get_object("a/b.json")
        txt_bytes = backend.get_object("a/b.txt")
        assert set(json_bytes) == {ord("J")}
        assert set(txt_bytes) == {ord("T")}

    def test_concurrent_writes_to_the_same_key_never_yield_a_torn_file(self, backend):
        payloads = [bytes([c]) * 5000 for c in (b"A"[0], b"B"[0], b"C"[0], b"D"[0])]
        errors: list = []

        def write(payload: bytes):
            try:
                for _ in range(150):
                    backend.put_object("shared/key.bin", payload)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent writes raised: {errors[:3]}"
        # Whichever writer won, the file must be exactly one payload — never a
        # mixture of two, which is what a shared temp path produced.
        final = backend.get_object("shared/key.bin")
        assert final in payloads

    def test_no_temp_files_are_left_behind(self, backend):
        backend.put_object("dir/file.json", b"x")

        leftovers = [p.name for p in (backend.root_dir / "dir").iterdir() if ".tmp" in p.name]

        assert leftovers == []


class TestListObjectsPrefixSemantics:
    def test_partial_prefix_matches_like_s3(self, backend):
        backend.put_object("certificates/run1/certificate.json", b"{}")
        backend.put_object("certificates/run2/certificate.json", b"{}")
        backend.put_object("other/thing.json", b"{}")

        # "cert" is a key prefix, not a directory — S3 matches it, and so must this.
        assert backend.list_objects("cert") == [
            "certificates/run1/certificate.json",
            "certificates/run2/certificate.json",
        ]

    def test_directory_prefix_still_works(self, backend):
        backend.put_object("certificates/run1/certificate.json", b"{}")
        backend.put_object("other/thing.json", b"{}")

        assert backend.list_objects("certificates") == ["certificates/run1/certificate.json"]

    def test_empty_prefix_lists_everything(self, backend):
        backend.put_object("a/one.json", b"{}")
        backend.put_object("b/two.json", b"{}")

        assert backend.list_objects() == ["a/one.json", "b/two.json"]

    def test_non_matching_prefix_returns_empty(self, backend):
        backend.put_object("a/one.json", b"{}")

        assert backend.list_objects("zzz") == []

    def test_prefix_does_not_match_a_longer_sibling_name(self, backend):
        backend.put_object("run/one.json", b"{}")
        backend.put_object("runner/two.json", b"{}")

        assert backend.list_objects("runner") == ["runner/two.json"]


class TestPathTraversalStillBlocked:
    @pytest.mark.parametrize("key", ["../escape.json", "a/../../escape.json"])
    def test_traversal_is_rejected(self, backend, key):
        with pytest.raises(ValueError, match="[Pp]ath traversal"):
            backend.put_object(key, b"x")
