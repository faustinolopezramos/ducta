from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.gate.gateway.spark_setup import (
    DEFAULT_SOURCES_PATH,
    _default_lib_dir,
    _download_drivers_for_sources,
    collect_jdbc_jars,
)


class TestDefaults:
    def test_default_sources_path(self):
        assert DEFAULT_SOURCES_PATH == "config/sources.yaml"

    def test_default_lib_dir(self):
        result = _default_lib_dir()
        assert str(result).endswith("lib/jdbc")


class TestCollectJdbcJars:
    def test_no_sources_file(self, temp_dir):
        with patch(
            "ducta.gate.gateway.spark_setup._default_lib_dir",
            return_value=temp_dir / "lib" / "jdbc",
        ):
            result = collect_jdbc_jars(
                sources_path=temp_dir / "config" / "sources.yaml",
                download=True,
            )
            assert result == []

    def test_with_existing_jars(self, temp_dir):
        lib_dir = temp_dir / "lib" / "jdbc"
        lib_dir.mkdir(parents=True)
        (lib_dir / "postgresql-42.6.0.jar").write_text("fake")
        result = collect_jdbc_jars(
            sources_path=temp_dir / "nonexistent.yaml",
            lib_dir=lib_dir,
            download=False,
        )
        assert len(result) == 1
        assert "postgresql-42.6.0.jar" in result[0]

    def test_download_false_skips(self, temp_dir):
        result = collect_jdbc_jars(
            sources_path=temp_dir / "nonexistent.yaml",
            lib_dir=temp_dir / "nope",
            download=False,
        )
        assert result == []

    @patch("ducta.gate.gateway.spark_setup._download_drivers_for_sources")
    def test_download_error_does_not_raise(self, mock_download, temp_dir):
        mock_download.side_effect = Exception("download failed")
        sources = temp_dir / "sources.yaml"
        sources.write_text("sources:\n  db:\n    type: postgresql\n")
        result = collect_jdbc_jars(sources_path=sources, download=True, lib_dir=temp_dir / "lib")
        assert result == []


class TestDownloadDriversForSources:
    def test_no_sources(self, temp_dir):
        sources = temp_dir / "sources.yaml"
        sources.write_text("sources: {}\n")
        _download_drivers_for_sources(sources, temp_dir)

    def test_unknown_type_does_not_raise(self, temp_dir):
        sources = temp_dir / "sources.yaml"
        sources.write_text("sources:\n  bad:\n    type: unknown\n")
        _download_drivers_for_sources(sources, temp_dir)

    def test_with_valid_source(self, temp_dir):
        sources = temp_dir / "sources.yaml"
        sources.write_text(
            "sources:\n  mydb:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: test\n"
        )
        with patch("ducta.gate.gateway.connector.JDBCConnector") as MockConnClass:
            MockConnClass.DRIVERS = {"postgresql": {"default_port": 5432}}
            instance = MagicMock()
            MockConnClass.return_value = instance
            _download_drivers_for_sources(sources, temp_dir)
            instance.download_driver.assert_called_once()

    def test_driver_download_failure_does_not_raise(self, temp_dir):
        sources = temp_dir / "sources.yaml"
        sources.write_text(
            "sources:\n  mydb:\n    type: postgresql\n    host: localhost\n    port: 5432\n    database: test\n"
        )
        with patch("ducta.gate.gateway.connector.JDBCConnector") as MockConnClass:
            MockConnClass.DRIVERS = {"postgresql": {"default_port": 5432}}
            instance = MagicMock()
            MockConnClass.return_value = instance
            instance.download_driver.side_effect = Exception("download failed")
            _download_drivers_for_sources(sources, temp_dir)
