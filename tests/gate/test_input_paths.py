"""Resolving a dataset's local ``filepath``."""

import pytest

from ducta.gate.exceptions import ConfigurationError
from ducta.gate.input_paths import has_glob_pattern, resolve_local_path


class TestResolveLocalPath:
    def test_an_existing_file_is_returned_as_posix(self, tmp_path):
        f = tmp_path / "a.csv"
        f.write_text("x\n")
        assert resolve_local_path(str(f)) == f.as_posix()

    def test_an_existing_directory_is_returned(self, tmp_path):
        assert resolve_local_path(str(tmp_path)) == tmp_path.as_posix()

    def test_a_glob_that_matches_keeps_the_pattern_for_spark(self, tmp_path):
        (tmp_path / "a.csv").write_text("x\n")
        pattern = tmp_path / "*.csv"
        assert resolve_local_path(str(pattern)) == pattern.as_posix()

    def test_a_glob_that_matches_nothing_is_an_error(self, tmp_path):
        with pytest.raises(ConfigurationError, match="matched no files"):
            resolve_local_path(str(tmp_path / "*.csv"))

    def test_a_glob_in_a_missing_directory_is_an_error(self, tmp_path):
        with pytest.raises(ConfigurationError, match="Parent directory"):
            resolve_local_path(str(tmp_path / "nope" / "*.csv"))

    def test_a_missing_file_is_an_error(self, tmp_path):
        with pytest.raises(ConfigurationError, match="does not exist"):
            resolve_local_path(str(tmp_path / "missing.csv"))


class TestReadFallback:
    @pytest.fixture
    def layout(self, tmp_path):
        own = tmp_path / "trial" / "out"
        shared = tmp_path / "shared" / "out"
        (shared / "silver").mkdir(parents=True)
        (shared / "silver" / "orders.parquet").write_text("x")
        return own, shared

    def test_a_missing_input_is_found_under_the_shared_prefix(self, layout):
        own, shared = layout
        missing = own / "silver" / "orders.parquet"
        resolved = resolve_local_path(str(missing), [str(shared)], str(own))
        assert resolved == (shared / "silver" / "orders.parquet").as_posix()

    def test_a_path_outside_the_output_path_is_not_looked_up(self, layout, tmp_path):
        own, shared = layout
        with pytest.raises(ConfigurationError, match="does not exist"):
            resolve_local_path(
                str(tmp_path / "elsewhere" / "orders.parquet"), [str(shared)], str(own)
            )

    def test_without_a_fallback_a_missing_input_is_an_error(self, layout):
        own, _ = layout
        with pytest.raises(ConfigurationError, match="does not exist"):
            resolve_local_path(str(own / "silver" / "orders.parquet"), [], str(own))


class TestHasGlobPattern:
    @pytest.mark.parametrize("path", ["/a/*.csv", "/a/f?.csv", "/a/[ab].csv"])
    def test_glob_characters(self, path):
        assert has_glob_pattern(path) is True

    def test_plain_path(self):
        assert has_glob_pattern("/a/file.csv") is False
