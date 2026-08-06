import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.setting.layered_config import (
    LayerConfig,
    LayerContextBuilder,
    LayeredProjectDetector,
    detect_and_prepare_layered_execution,
)


class TestLayerConfig:
    def test_init_with_defaults(self):
        lc = LayerConfig("bronze", {"path": "bronze"})
        assert lc.name == "bronze"
        assert lc.path == Path("bronze")
        assert lc.global_settings == "global.yaml"
        assert lc.config_path == "config"

    def test_init_with_overrides(self):
        lc = LayerConfig(
            "custom",
            {
                "path": "custom_path",
                "description": "Custom layer",
                "depends_on": ["other"],
                "global_settings": "custom_global.yaml",
                "config_path": "custom_config",
                "environments_path": "custom_env",
            },
        )
        assert lc.path == Path("custom_path")
        assert lc.description == "Custom layer"
        assert lc.depends_on == ["other"]

    def test_get_config_paths(self, temp_dir):
        lc = LayerConfig("bronze", {"path": "bronze"})
        paths = lc.get_config_paths(temp_dir)
        assert paths["global_settings"] == temp_dir / "bronze" / "global.yaml"
        assert paths["pipelines_config"] == temp_dir / "bronze" / "config" / "pipelines.yaml"
        assert paths["nodes_config"] == temp_dir / "bronze" / "config" / "nodes.yaml"
        assert paths["layer_path"] == temp_dir / "bronze"

    def test_get_pipeline_names_no_file(self, temp_dir):
        lc = LayerConfig("bronze", {"path": "bronze"})
        names = lc.get_pipeline_names(temp_dir)
        assert names == set()

    def test_get_pipeline_names_with_file(self, temp_dir):
        lc = LayerConfig("bronze", {"path": "bronze"})
        pipeline_dir = temp_dir / "bronze" / "config"
        pipeline_dir.mkdir(parents=True)
        (pipeline_dir / "pipelines.yaml").write_text("p1: {nodes: []}\np2: {nodes: []}\n")
        names = lc.get_pipeline_names(temp_dir)
        assert names == {"p1", "p2"}


class TestLayeredProjectDetector:
    def test_init_no_project(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        assert detector.is_layered_project is False
        assert len(detector.layers) == 0

    def test_auto_detect_layers(self, temp_dir):
        for layer in ["bronze", "silver"]:
            (temp_dir / layer).mkdir()
            (temp_dir / layer / "global.yaml").write_text("")
            (temp_dir / layer / "config").mkdir()
        detector = LayeredProjectDetector(project_root=temp_dir)
        assert detector.is_layered_project is True
        assert "bronze" in detector.layers
        assert "silver" in detector.layers

    def test_auto_detect_no_layers(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        assert detector.is_layered_project is False

    def test_load_settings_from_settings_file(self, temp_dir):
        settings_dir = temp_dir / ".ducta"
        settings_dir.mkdir()
        settings = {
            "ducta": {
                "layers": [
                    {"name": "bronze", "path": "bronze"},
                    {"name": "silver", "path": "silver", "depends_on": ["bronze"]},
                ],
                "execution_order": ["bronze", "silver"],
            }
        }
        (settings_dir / "settings.json").write_text(json.dumps(settings))
        settings_file = settings_dir / "settings.json"
        assert settings_file.exists()

        detector = LayeredProjectDetector(project_root=temp_dir)
        assert detector.is_layered_project is True
        assert "bronze" in detector.layers
        assert "silver" in detector.layers
        assert detector.execution_order == ["bronze", "silver"]

    def test_load_settings_missing_file(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        assert detector.is_layered_project is False

    @patch("ducta.setting.layered_config._find_manifest")
    def test_load_ducta_yaml_not_layered(self, mock_find, temp_dir):
        manifest = temp_dir / "ducta.yaml"
        manifest.write_text("project: {type: single}\n")
        mock_find.return_value = manifest
        detector = LayeredProjectDetector(project_root=temp_dir)
        assert detector.is_layered_project is False

    @patch("ducta.setting.layered_config._find_manifest")
    def test_load_ducta_yaml_layered(self, mock_find, temp_dir):
        manifest = temp_dir / "ducta.yaml"
        manifest.write_text(
            "project: {type: layered}\n"
            "layers:\n"
            "  raw: {path: raw, config: raw/config}\n"
            "execution: {order: [raw]}\n"
        )
        mock_find.return_value = manifest
        detector = LayeredProjectDetector(project_root=temp_dir)
        assert detector.is_layered_project is True
        assert "raw" in detector.layers

    def test_get_layer(self, temp_dir):
        lc = LayerConfig("bronze", {"path": "bronze"})
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = lc
        assert detector.get_layer("bronze") is lc
        assert detector.get_layer("missing") is None

    def test_list_layers(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["a"] = MagicMock()
        detector.layers["b"] = MagicMock()
        assert sorted(detector.list_layers()) == ["a", "b"]

    def test_get_execution_order(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.execution_order = ["a", "b"]
        assert detector.get_execution_order() == ["a", "b"]

    def test_validate_layer_exists(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = MagicMock()
        assert detector.validate_layer_exists("bronze") is True
        assert detector.validate_layer_exists("missing") is False

    def test_find_layers_for_pipeline(self, temp_dir):
        # No ConfigLoaderFactory patch on purpose: this test writes real
        # pipelines.yaml files, so it must exercise the real loader. Mocking the
        # factory makes load_config return a MagicMock, which get_pipeline_names
        # correctly rejects as "not a mapping" — the test would pass vacuously.
        lc_bronze = LayerConfig("bronze", {"path": "bronze"})
        lc_silver = LayerConfig("silver", {"path": "silver"})
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = lc_bronze
        detector.layers["silver"] = lc_silver
        detector.execution_order = ["bronze", "silver"]
        detector.is_layered_project = True

        (temp_dir / "bronze" / "config").mkdir(parents=True)
        (temp_dir / "bronze" / "config" / "pipelines.yaml").write_text("p1: {nodes: []}")
        (temp_dir / "silver" / "config").mkdir(parents=True)
        (temp_dir / "silver" / "config" / "pipelines.yaml").write_text("p2: {nodes: []}")

        matches = detector.find_layers_for_pipeline("p1")
        assert matches == ["bronze"]

    def test_validate_execution_order_valid(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        lc1 = LayerConfig("bronze", {"path": "bronze"})
        lc2 = LayerConfig("silver", {"path": "silver", "depends_on": ["bronze"]})
        detector.layers["bronze"] = lc1
        detector.layers["silver"] = lc2
        detector.execution_order = ["bronze", "silver"]
        assert detector.validate_execution_order() is True

    def test_validate_execution_order_invalid(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        lc1 = LayerConfig("bronze", {"path": "bronze", "depends_on": ["silver"]})
        lc2 = LayerConfig("silver", {"path": "silver", "depends_on": ["bronze"]})
        detector.layers["bronze"] = lc1
        detector.layers["silver"] = lc2
        detector.execution_order = ["bronze", "silver"]
        assert detector.validate_execution_order() is False


class TestLayerContextBuilder:
    def test_build_context_args_layer_not_found(self, temp_dir):
        detector = LayeredProjectDetector(project_root=temp_dir)
        result = LayerContextBuilder.build_context_args(detector, "nonexistent")
        assert result is None

    def test_build_context_args_missing_files(self, temp_dir):
        lc = LayerConfig("bronze", {"path": "bronze"})
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = lc
        result = LayerContextBuilder.build_context_args(detector, "bronze")
        assert result is None

    def test_build_context_args_success(self, temp_dir):
        layer_path = temp_dir / "bronze"
        config_path = layer_path / "config"
        config_path.mkdir(parents=True)
        (layer_path / "global.yaml").write_text("")
        (config_path / "pipelines.yaml").write_text("")
        (config_path / "nodes.yaml").write_text("")
        (config_path / "input.yaml").write_text("")
        (config_path / "output.yaml").write_text("")

        lc = LayerConfig("bronze", {"path": "bronze"})
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = lc
        result = LayerContextBuilder.build_context_args(detector, "bronze")
        assert result is not None
        assert result["layer"] == "bronze"
        assert "global_settings" in result

    def test_inject_sys_path(self, temp_dir):
        import sys

        src = temp_dir / "bronze" / "src"
        src.mkdir(parents=True)
        lc = LayerConfig("bronze", {"path": "bronze"})
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = lc
        before = list(sys.path)
        try:
            LayerContextBuilder.inject_sys_path(detector, "bronze")
            # Roots are resolved, so compare resolved (on macOS a temp dir under
            # /var resolves to /private/var).
            assert str(src.resolve()) in sys.path
            # The layer root goes ahead of its src/, so `import src.foo` finds
            # this layer's package before any same-named one further up.
            assert sys.path.index(str(temp_dir.resolve() / "bronze")) < sys.path.index(
                str(src.resolve())
            )
        finally:
            sys.path[:] = before

    def test_layer_sys_path_restores_what_it_added(self, temp_dir):
        import sys

        from ducta.setting.layered_config import layer_sys_path

        (temp_dir / "bronze" / "src").mkdir(parents=True)
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = LayerConfig("bronze", {"path": "bronze"})

        before = list(sys.path)
        with layer_sys_path(detector, "bronze"):
            assert str((temp_dir / "bronze" / "src").resolve()) in sys.path
        # Running a second layer in the same process must not inherit the first.
        assert sys.path == before


class TestDetectAndPrepareLayeredExecution:
    def test_single_layer_routing(self, temp_dir):
        layer_path = temp_dir / "bronze"
        config_path = layer_path / "config"
        config_path.mkdir(parents=True)
        (layer_path / "global.yaml").write_text("")
        (config_path / "pipelines.yaml").write_text("")
        (config_path / "nodes.yaml").write_text("")
        (config_path / "input.yaml").write_text("")
        (config_path / "output.yaml").write_text("")

        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = LayerConfig("bronze", {"path": "bronze"})
        detector.execution_order = ["bronze"]
        detector.is_layered_project = True

        args = MagicMock()
        args.all_layers = False
        args.layer = "bronze"
        args.env = "dev"
        args.pipeline = None

        with patch("ducta.setting.layered_config.LayeredProjectDetector", return_value=detector):
            found, kind, context_args = detect_and_prepare_layered_execution(args)
            assert found is True
            assert kind == "single"
            assert context_args is not None

    def test_all_layers_routing(self):
        args = MagicMock()
        args.all_layers = True

        with patch("ducta.setting.layered_config.LayeredProjectDetector") as mock_det:
            detector = MagicMock()
            detector.is_layered_project = True
            detector.validate_execution_order.return_value = True
            mock_det.return_value = detector
            found, kind, context_args = detect_and_prepare_layered_execution(args)
            assert found is True
            assert kind == "all"

    def test_invalid_execution_order(self):
        args = MagicMock()

        with patch("ducta.setting.layered_config.LayeredProjectDetector") as mock_det:
            detector = MagicMock()
            detector.is_layered_project = True
            detector.validate_execution_order.return_value = False
            mock_det.return_value = detector
            found, kind, context_args = detect_and_prepare_layered_execution(args)
            assert found is True
            assert kind is None

    def test_layer_not_found(self):
        args = MagicMock()
        args.all_layers = False
        args.layer = "nonexistent"
        args.env = "dev"
        args.pipeline = None

        with patch("ducta.setting.layered_config.LayeredProjectDetector") as mock_det:
            detector = MagicMock()
            detector.is_layered_project = True
            detector.validate_execution_order.return_value = True
            detector.validate_layer_exists.return_value = False
            mock_det.return_value = detector
            found, kind, context_args = detect_and_prepare_layered_execution(args)
            assert found is True
            assert kind is None


class TestEnvTravelsWithTheContextArgs:
    """`env` is part of the returned contract, not a parameter that goes nowhere.

    It used to be accepted and ignored: the method took an `env` argument, never
    read it, and returned a dict without it. Every caller then had to remember
    to pass the environment to `Context(...)` separately — and
    `ducta config validate` did not, so a layered project was validated against
    its base configuration whatever `--env` said.
    """

    def _layer(self, temp_dir):
        layer_path = temp_dir / "bronze"
        config_path = layer_path / "config"
        config_path.mkdir(parents=True)
        (layer_path / "global.yaml").write_text("")
        for name in ("pipelines", "nodes", "input", "output"):
            (config_path / f"{name}.yaml").write_text("")
        detector = LayeredProjectDetector(project_root=temp_dir)
        detector.layers["bronze"] = LayerConfig("bronze", {"path": "bronze"})
        return detector

    def test_the_requested_env_is_returned(self, temp_dir):
        detector = self._layer(temp_dir)

        args = LayerContextBuilder.build_context_args(detector, "bronze", "prod")

        assert args is not None
        assert args["env"] == "prod"

    def test_the_default_env_is_returned_when_none_is_given(self, temp_dir):
        detector = self._layer(temp_dir)

        args = LayerContextBuilder.build_context_args(detector, "bronze")

        assert args is not None
        assert args["env"] == "base"

    def test_every_path_key_is_still_present(self, temp_dir):
        detector = self._layer(temp_dir)

        args = LayerContextBuilder.build_context_args(detector, "bronze", "dev")

        assert set(args) >= {
            "global_settings",
            "pipelines_config",
            "nodes_config",
            "input_config",
            "output_config",
            "layer",
            "layer_path",
            "env",
        }
