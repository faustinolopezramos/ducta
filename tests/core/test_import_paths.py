"""Import-path smoke test for the core package splits.

``executor.py`` became ``executors/{base,batch,streaming,hybrid,facade}.py`` and
``node_executor.py`` became ``execution/{state,loader,quality,output,ml_builder,
ingestion,coordinator,runner}.py``. Both original modules are gone, so these are
the paths real consumers now rely on: if one breaks, it fails here with a clear
message instead of surfacing as a mysterious ImportError deep inside a run.

Mirrors ``tests/gate/test_output_compat.py``, which does the same for the
earlier ``output.py`` split.
"""

from __future__ import annotations

import importlib

import pytest

EXECUTOR_NAMES = [
    "BaseExecutor",
    "BatchExecutor",
    "HybridExecutor",
    "PipelineExecutor",
    "StreamingExecutor",
]

EXECUTION_NAMES = [
    "FunctionLoader",
    "IngestionExecutor",
    "MLContextBuilder",
    "NodeExecutor",
    "OutputWriter",
    "ParallelCoordinator",
    "QualityCheckExecutor",
    "ThreadSafeExecutionState",
]


class TestRemovedModulesAreGone:
    @pytest.mark.parametrize("module", ["ducta.core.executor", "ducta.core.node_executor"])
    def test_the_old_module_no_longer_exists(self, module):
        # Deleted deliberately: leaving an empty shim behind invites new code to
        # keep importing a path that no longer describes where anything lives.
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


class TestPackageSurfaces:
    @pytest.mark.parametrize("name", EXECUTOR_NAMES)
    def test_executor_names_are_importable_from_the_package(self, name):
        module = importlib.import_module("ducta.core.executors")
        assert hasattr(module, name)

    @pytest.mark.parametrize("name", EXECUTION_NAMES)
    def test_execution_names_are_importable_from_the_package(self, name):
        module = importlib.import_module("ducta.core.execution")
        assert hasattr(module, name)

    @pytest.mark.parametrize("name", EXECUTOR_NAMES + EXECUTION_NAMES)
    def test_every_name_is_still_re_exported_from_ducta_core(self, name):
        # ducta.core is the documented public surface; the split must not have
        # changed what it offers.
        module = importlib.import_module("ducta.core")
        assert hasattr(module, name)
        assert name in module.__all__


class TestSubmodulePaths:
    @pytest.mark.parametrize(
        "path,name",
        [
            ("ducta.core.executors.base", "BaseExecutor"),
            ("ducta.core.executors.batch", "BatchExecutor"),
            ("ducta.core.executors.streaming", "StreamingExecutor"),
            ("ducta.core.executors.hybrid", "HybridExecutor"),
            ("ducta.core.executors.facade", "PipelineExecutor"),
            ("ducta.core.execution.state", "ThreadSafeExecutionState"),
            ("ducta.core.execution.loader", "FunctionLoader"),
            ("ducta.core.execution.quality", "QualityCheckExecutor"),
            ("ducta.core.execution.output", "OutputWriter"),
            ("ducta.core.execution.ml_builder", "MLContextBuilder"),
            ("ducta.core.execution.ingestion", "IngestionExecutor"),
            ("ducta.core.execution.coordinator", "ParallelCoordinator"),
            ("ducta.core.execution.runner", "NodeExecutor"),
        ],
    )
    def test_each_class_lives_where_its_module_says(self, path, name):
        module = importlib.import_module(path)
        cls = getattr(module, name)
        # Defined here, not merely re-exported: catches a name silently drifting
        # to a different module while the import still resolves.
        assert cls.__module__ == path


class TestSingleIdentity:
    def test_the_package_and_submodule_expose_the_same_class(self):
        import ducta.core as core
        from ducta.core.execution import NodeExecutor as from_package
        from ducta.core.execution.runner import NodeExecutor as from_module

        assert from_package is from_module is core.NodeExecutor

    def test_utils_helpers_are_imported_from_utils(self):
        # `extract_pipeline_nodes` was reachable through executor.py only because
        # that module imported it; a consumer importing it from there broke when
        # executor.py became a shim. It belongs to utils.
        from ducta.core.utils import extract_pipeline_nodes

        assert callable(extract_pipeline_nodes)
