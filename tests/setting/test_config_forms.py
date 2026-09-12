from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ducta.setting.config_forms import FlexibleConfigResolver


class TestFlexibleConfigResolver:
    def test_resolve_file_none_data(self):
        result = FlexibleConfigResolver.resolve_file("/some/path.yaml", None, "dev")
        assert result is None

    def test_resolve_file_env_config_root(self):
        result = FlexibleConfigResolver.resolve_file(
            "/some/path.yaml", {"env_config": {"env": "dev"}}, "dev"
        )
        assert result is None

    def test_resolve_file_not_dict(self):
        result = FlexibleConfigResolver.resolve_file("/some/path.yaml", "not a dict", "dev")
        assert result is None

    def test_resolve_dir_not_a_directory(self, temp_dir):
        result = FlexibleConfigResolver.resolve_dir(temp_dir / "nonexistent", "dev")
        assert result is None

    def test_resolve_dir_empty_directory(self, temp_dir):
        result = FlexibleConfigResolver.resolve_dir(temp_dir, "dev")
        assert result is None

    @patch("ducta.setting.config_forms.Context")
    @patch("ducta.setting.config_forms._load")
    @patch("ducta.setting.config_forms._find")
    def test_resolve_dir_bundle(self, mock_find, mock_load, mock_ctx, temp_dir):
        mock_find.return_value = temp_dir / "Ducta.yaml"
        mock_load.return_value = {
            "global_config": {"input_path": "/in", "output_path": "/out", "mode": "local"},
            "pipelines_config": {},
            "nodes_config": {},
            "input_config": {},
            "output_config": {},
        }
        mock_ctx_instance = MagicMock()
        mock_ctx_instance.global_config = {
            "input_path": "/in",
            "output_path": "/out",
            "mode": "local",
        }
        mock_ctx.return_value = mock_ctx_instance
        ctx = FlexibleConfigResolver.resolve_dir(temp_dir, "dev")
        assert ctx is not None
        assert ctx.global_config["input_path"] == "/in"

    @patch("ducta.setting.config_forms.Context")
    @patch("ducta.setting.config_forms._load")
    @patch("ducta.setting.config_forms._find")
    @patch("ducta.setting.config_forms._dir_convention_paths")
    def test_resolve_dir_convention(self, mock_dcp, mock_find, mock_load, mock_ctx, temp_dir):
        mock_find.return_value = None
        mock_dcp.return_value = {
            "global_config": str(temp_dir / "global.yaml"),
            "pipelines_config": str(temp_dir / "config/pipelines.yaml"),
            "nodes_config": str(temp_dir / "config/nodes.yaml"),
            "input_config": str(temp_dir / "config/input.yaml"),
            "output_config": str(temp_dir / "config/output.yaml"),
        }
        mock_load.return_value = {
            "global_config": {"input_path": "/in", "output_path": "/out", "mode": "local"},
            "pipelines_config": {},
            "nodes_config": {},
            "input_config": {},
            "output_config": {},
        }
        mock_ctx_instance = MagicMock()
        mock_ctx.return_value = mock_ctx_instance
        ctx = FlexibleConfigResolver.resolve_dir(temp_dir, "dev")
        assert ctx is not None

    @patch("ducta.setting.config_forms.Context")
    def test_resolve_file_bundle(self, mock_ctx, temp_dir):
        bundle = {
            "global_config": {"input_path": "/in", "output_path": "/out", "mode": "local"},
            "pipelines_config": {"p1": {"nodes": ["n1"]}},
            "nodes_config": {"n1": {"function": "mymod.my_func"}},
            "input_config": {"ds1": {"format": "parquet"}},
            "output_config": {"out1": {"format": "delta"}},
        }
        f = temp_dir / "bundle.yaml"
        f.write_text("dummy")
        mock_ctx_instance = MagicMock()
        mock_ctx_instance.global_config = {
            "input_path": "/in",
            "output_path": "/out",
            "mode": "local",
        }
        mock_ctx_instance.pipelines_config = {"p1": {"nodes": ["n1"]}}
        mock_ctx_instance._config_file_path = str(f.resolve())
        mock_ctx.return_value = mock_ctx_instance

        with patch("ducta.setting.config_forms._load", return_value=bundle):
            ctx = FlexibleConfigResolver.resolve_file(str(f), bundle, "dev")
            assert ctx is not None
            assert ctx.global_config["input_path"] == "/in"
            assert "p1" in ctx.pipelines_config
            assert ctx._config_file_path is not None

    @patch("ducta.setting.config_forms.Context")
    @patch("ducta.setting.config_forms._load")
    def test_resolve_dir_quickstart(self, mock_load, mock_ctx, temp_dir):
        global_f = temp_dir / "global.yaml"
        global_f.write_text("dummy")
        pipeline_f = temp_dir / "pipeline.yaml"
        pipeline_f.write_text("dummy")

        def _load_side_effect(path):
            p = Path(path)
            if "global" in p.name:
                return {"input_path": "/in", "output_path": "/out", "mode": "local"}
            if "pipeline" in p.name:
                return {
                    "pipelines": {"p1": {"nodes": ["n1"]}},
                    "nodes": {"n1": {"function": "mymod.my_func"}},
                    "input": {"ds1": {"format": "parquet"}},
                    "output": {"out1": {"format": "delta"}},
                }
            return None

        mock_load.side_effect = _load_side_effect
        mock_ctx_instance = MagicMock()
        mock_ctx_instance.global_config = {"input_path": "/in"}
        mock_ctx.return_value = mock_ctx_instance
        ctx = FlexibleConfigResolver.resolve_dir(temp_dir, "dev")
        assert ctx is not None


class TestInternalHelpers:
    def test_is_bundle_true(self):
        from ducta.setting.config_forms import _is_bundle

        assert _is_bundle(
            {
                "global_config": {},
                "pipelines_config": {},
                "nodes_config": {},
                "input_config": {},
                "output_config": {},
            }
        )

    def test_is_bundle_false_no_keys(self):
        from ducta.setting.config_forms import _is_bundle

        assert _is_bundle({"env_config": {}}) is False

    def test_is_bundle_false_missing_key(self):
        from ducta.setting.config_forms import _is_bundle

        assert _is_bundle({"global_config": {}, "pipelines_config": {}}) is False

    def test_find_returns_first_match(self, temp_dir):
        from ducta.setting.config_forms import _find

        (temp_dir / "global.yaml").write_text("")
        (temp_dir / "global.yml").write_text("")
        found = _find(temp_dir, "global")
        assert found is not None
        assert found.suffix == ".yaml"

    def test_find_returns_none(self, temp_dir):
        from ducta.setting.config_forms import _find

        assert _find(temp_dir, "nonexistent") is None

    def test_dir_convention_paths_all_found(self, temp_dir):
        from ducta.setting.config_forms import _dir_convention_paths

        (temp_dir / "global.yaml").write_text("")
        (temp_dir / "pipelines.yaml").write_text("")
        (temp_dir / "nodes.yaml").write_text("")
        (temp_dir / "input.yaml").write_text("")
        (temp_dir / "output.yaml").write_text("")
        result = _dir_convention_paths(temp_dir)
        assert result is not None
        assert "global_config" in result
        assert "pipelines_config" in result

    def test_dir_convention_paths_missing(self, temp_dir):
        from ducta.setting.config_forms import _dir_convention_paths

        (temp_dir / "global.yaml").write_text("")
        result = _dir_convention_paths(temp_dir)
        assert result is None

    def test_dir_convention_paths_in_config_subdir(self, temp_dir):
        from ducta.setting.config_forms import _dir_convention_paths

        (temp_dir / "global.yaml").write_text("")
        cfg = temp_dir / "config"
        cfg.mkdir()
        (cfg / "pipelines.yaml").write_text("")
        (cfg / "nodes.yaml").write_text("")
        (cfg / "input.yaml").write_text("")
        (cfg / "output.yaml").write_text("")
        result = _dir_convention_paths(temp_dir)
        assert result is not None

    def test_load_returns_none_on_exception(self):
        from ducta.setting.config_forms import _load

        assert _load(Path("/nonexistent/file.yaml")) is None
