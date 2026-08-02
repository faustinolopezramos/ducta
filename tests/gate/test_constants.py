from ducta.gate.constants import (
    CLOUD_URI_PREFIXES,
    DEFAULT_CSV_OPTIONS,
    DEFAULT_ENCODING,
    DEFAULT_VACUUM_RETENTION_HOURS,
    MIN_VACUUM_RETENTION_HOURS,
    ExecutionMode,
    SupportedFormats,
    WriteMode,
    is_cloud_path,
)


class TestSupportedFormats:
    def test_values(self):
        assert SupportedFormats.PARQUET.value == "parquet"
        assert SupportedFormats.JSON.value == "json"
        assert SupportedFormats.CSV.value == "csv"
        assert SupportedFormats.DELTA.value == "delta"
        assert SupportedFormats.PICKLE.value == "pickle"
        assert SupportedFormats.AVRO.value == "avro"
        assert SupportedFormats.ORC.value == "orc"
        assert SupportedFormats.XML.value == "xml"
        assert SupportedFormats.QUERY.value == "query"
        assert SupportedFormats.UNITY_CATALOG.value == "unity_catalog"

    def test_all_formats_covered(self):
        names = {e.value for e in SupportedFormats}
        expected = {
            "parquet",
            "json",
            "csv",
            "delta",
            "pickle",
            "avro",
            "orc",
            "xml",
            "query",
            "unity_catalog",
        }
        assert names == expected


class TestWriteMode:
    def test_values(self):
        assert WriteMode.OVERWRITE.value == "overwrite"
        assert WriteMode.APPEND.value == "append"
        assert WriteMode.IGNORE.value == "ignore"
        assert WriteMode.ERROR.value == "error"


class TestExecutionMode:
    def test_values(self):
        assert ExecutionMode.LOCAL.value == "local"
        assert ExecutionMode.DISTRIBUTED.value == "distributed"


class TestConstants:
    def test_csv_options(self):
        assert DEFAULT_CSV_OPTIONS == {"header": "true"}

    def test_encoding(self):
        assert DEFAULT_ENCODING == "UTF-8"

    def test_vacuum_retention(self):
        assert DEFAULT_VACUUM_RETENTION_HOURS == 168
        assert MIN_VACUUM_RETENTION_HOURS == 168
        assert DEFAULT_VACUUM_RETENTION_HOURS == MIN_VACUUM_RETENTION_HOURS

    def test_cloud_uri_prefixes(self):
        assert "s3://" in CLOUD_URI_PREFIXES
        assert "abfss://" in CLOUD_URI_PREFIXES
        assert "gs://" in CLOUD_URI_PREFIXES
        assert "dbfs:/" in CLOUD_URI_PREFIXES


class TestIsCloudPath:
    def test_s3_path(self):
        assert is_cloud_path("s3://bucket/key") is True

    def test_abfss_path(self):
        assert is_cloud_path("abfss://container@storage.dfs.core.windows.net/path") is True

    def test_gs_path(self):
        assert is_cloud_path("gs://bucket/path") is True

    def test_dbfs_path(self):
        assert is_cloud_path("dbfs:/path/to/file") is True

    def test_local_path(self):
        assert is_cloud_path("/local/path/to/file") is False

    def test_relative_path(self):
        assert is_cloud_path("relative/path") is False

    def test_empty_string(self):
        assert is_cloud_path("") is False

    def test_https_is_not_cloud(self):
        assert is_cloud_path("https://example.com/file") is False

    def test_case_sensitive(self):
        assert is_cloud_path("S3://bucket/key") is False

    def test_none_coercion(self):
        assert is_cloud_path(None) is False
