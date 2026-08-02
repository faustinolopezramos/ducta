"""Unit tests for ducta.mlrun.storage.LocalStorageBackend.write_artifact atomicity."""

from __future__ import annotations

from ducta.mlrun.storage import LocalStorageBackend


def _make_storage(tmp_path):
    return LocalStorageBackend(base_path=str(tmp_path / "mlops"), enable_circuit_breaker=False)


class TestFileArtifact:
    def test_write_and_read_roundtrip(self, tmp_path):
        storage = _make_storage(tmp_path)
        src = tmp_path / "model.bin"
        src.write_bytes(b"weights-v1")

        storage.write_artifact(str(src), "artifacts/model.bin")

        dest = tmp_path / "download.bin"
        storage.read_artifact("artifacts/model.bin", str(dest))
        assert dest.read_bytes() == b"weights-v1"

    def test_overwrite_replaces_content_atomically(self, tmp_path):
        storage = _make_storage(tmp_path)
        src1 = tmp_path / "v1.bin"
        src1.write_bytes(b"v1")
        src2 = tmp_path / "v2.bin"
        src2.write_bytes(b"v2")

        storage.write_artifact(str(src1), "artifacts/model.bin")
        storage.write_artifact(str(src2), "artifacts/model.bin", mode="overwrite")

        dest = tmp_path / "download.bin"
        storage.read_artifact("artifacts/model.bin", str(dest))
        assert dest.read_bytes() == b"v2"

    def test_no_leftover_temp_files(self, tmp_path):
        storage = _make_storage(tmp_path)
        src = tmp_path / "model.bin"
        src.write_bytes(b"data")
        storage.write_artifact(str(src), "artifacts/model.bin")

        artifact_dir = tmp_path / "mlops" / "artifacts"
        leftovers = [p for p in artifact_dir.iterdir() if p.name.startswith(".model.bin")]
        assert leftovers == []


class TestDirectoryArtifact:
    def test_write_and_read_directory_roundtrip(self, tmp_path):
        storage = _make_storage(tmp_path)
        src_dir = tmp_path / "model_dir"
        src_dir.mkdir()
        (src_dir / "weights.bin").write_bytes(b"w1")
        (src_dir / "config.json").write_text("{}")

        storage.write_artifact(str(src_dir), "artifacts/model_dir")

        dest_dir = tmp_path / "download_dir"
        storage.read_artifact("artifacts/model_dir", str(dest_dir))
        assert (dest_dir / "weights.bin").read_bytes() == b"w1"
        assert (dest_dir / "config.json").exists()

    def test_overwrite_directory_replaces_content_atomically(self, tmp_path):
        storage = _make_storage(tmp_path)
        src1 = tmp_path / "d1"
        src1.mkdir()
        (src1 / "a.txt").write_text("v1")

        src2 = tmp_path / "d2"
        src2.mkdir()
        (src2 / "b.txt").write_text("v2")

        storage.write_artifact(str(src1), "artifacts/model_dir")
        storage.write_artifact(str(src2), "artifacts/model_dir", mode="overwrite")

        dest_dir = tmp_path / "download_dir"
        storage.read_artifact("artifacts/model_dir", str(dest_dir))
        assert not (dest_dir / "a.txt").exists()
        assert (dest_dir / "b.txt").read_text() == "v2"

    def test_no_leftover_temp_or_backup_dirs(self, tmp_path):
        storage = _make_storage(tmp_path)
        src1 = tmp_path / "d1"
        src1.mkdir()
        (src1 / "a.txt").write_text("v1")
        src2 = tmp_path / "d2"
        src2.mkdir()
        (src2 / "b.txt").write_text("v2")

        storage.write_artifact(str(src1), "artifacts/model_dir")
        storage.write_artifact(str(src2), "artifacts/model_dir", mode="overwrite")

        artifact_dir = tmp_path / "mlops" / "artifacts"
        leftovers = [p for p in artifact_dir.iterdir() if p.name.startswith(".model_dir")]
        assert leftovers == []
