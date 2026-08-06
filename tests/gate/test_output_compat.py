"""Import compatibility smoke test for the output/ package split.

output.py was split into a package (output/{__init__,paths,dataframes,unity_catalog,manager}.py).
These are the exact import paths real consumers rely on; if any of them breaks, it fails here
with a clear message instead of surfacing as a mysterious ImportError somewhere else.
"""


def test_data_output_manager_importable():
    from ducta.gate.output import DataOutputManager  # noqa: F401  (core/executors/base.py)


def test_is_cloud_path_importable_from_output():
    from ducta.gate.output import is_cloud_path  # noqa: F401  (check/storage.py)


def test_newest_mtime_importable_from_output():
    from ducta.gate.output import _newest_mtime  # noqa: F401  (input.py, intra-package)


def test_gate_init_reexports_output_symbols():
    from ducta.gate import (  # noqa: F401
        DataOutputManager,
        UnityCatalogConfig,
        UnityCatalogManager,
        join_cloud_path,
        parse_iso_datetime,
        validate_date_range,
    )
