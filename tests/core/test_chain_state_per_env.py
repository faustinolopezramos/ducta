"""Chain-state markers must be isolated per environment.

Before this, `.ducta/chain_state/<pipeline>.json` was a single flat file
shared by every environment, so a `prod` run's "already up to date" marker
could silently satisfy a `dev` (or `sandbox`) run of the same pipeline. Run
certificates had the same bug in `.ducta/runs/<run_id>/`.

Chain state now lives at `${output_path}/${environment}/.ducta/chain_state/`
(the Ducta storage convention — see `CoreSettings.DEFAULT_CHAIN_STATE_DIR`),
next to the environment's own data instead of a project-root `.ducta/`. Two
older layouts are still read (never written) as fallbacks, oldest last:
`.ducta/chain_state/<env>/<pipeline>.json` (the previous, pre-convention
per-env default, relative to cwd) and `.ducta/chain_state/<pipeline>.json`
(the original flat file, no environment at all).
"""

from __future__ import annotations

import json

import pytest

from ducta.core.executors.facade import PipelineExecutor
from ducta.core.settings import CoreSettings
from ducta.stream.constants import PipelineType
from tests.core.fakes import FakeContext


def _executor(env, **global_config) -> PipelineExecutor:
    context = FakeContext(global_config=global_config)
    settings = CoreSettings.from_context({"env": env, **global_config})
    return PipelineExecutor(context, settings=settings)


class TestChainStatePathIsEnvScoped:
    def test_two_environments_get_different_paths(self):
        dev = _executor("dev")
        prod = _executor("prod")
        assert dev._chain_state_path("sales.daily") != prod._chain_state_path("sales.daily")
        assert "dev" in dev._chain_state_path("sales.daily").parts
        assert "prod" in prod._chain_state_path("sales.daily").parts
        # env is a path segment ahead of the hidden `.ducta/chain_state`
        # namespace, not the immediate parent of the marker file.
        assert dev._chain_state_path("sales.daily").parent.name == "chain_state"

    def test_missing_environment_falls_back_to_base(self):
        executor = _executor(None)
        assert "base" in executor._chain_state_path("sales.daily").parts

    def test_pipeline_name_slashes_are_still_flattened(self):
        executor = _executor("dev")
        path = executor._chain_state_path("schema/pipeline")
        assert path.name == "schema_pipeline.json"


class TestChainStateReadWriteRoundtrip:
    def test_recorded_state_is_isolated_between_environments(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dev = _executor("dev")
        prod = _executor("prod")

        dev._record_chain_state("sales.daily", PipelineType.BATCH, "2026-01-01", "2026-01-02")

        assert dev._load_chain_state("sales.daily") is not None
        assert dev._load_chain_state("sales.daily")["start_date"] == "2026-01-01"
        # prod never ran this pipeline — it must not see dev's marker.
        assert prod._load_chain_state("sales.daily") is None

    def test_two_environments_can_hold_different_recorded_ranges(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dev = _executor("dev")
        prod = _executor("prod")

        dev._record_chain_state("sales.daily", PipelineType.BATCH, "2026-01-01", "2026-01-02")
        prod._record_chain_state("sales.daily", PipelineType.BATCH, "2025-06-01", "2025-06-30")

        assert dev._load_chain_state("sales.daily")["start_date"] == "2026-01-01"
        assert prod._load_chain_state("sales.daily")["start_date"] == "2025-06-01"

    def test_non_batch_pipelines_are_never_recorded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dev = _executor("dev")
        dev._record_chain_state("orders.stream", PipelineType.STREAMING, None, None)
        assert not dev._chain_state_path("orders.stream").exists()


class TestChainStateLegacyFallback:
    def test_load_falls_back_to_the_pre_per_env_flat_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        legacy_path = tmp_path / ".ducta" / "chain_state" / "sales.daily.json"
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(
            json.dumps(
                {"pipeline": "sales.daily", "start_date": "2024-01-01", "end_date": "2024-01-02"}
            ),
            encoding="utf-8",
        )

        dev = _executor("dev")
        data = dev._load_chain_state("sales.daily")

        assert data is not None
        assert data["start_date"] == "2024-01-01"

    def test_reading_the_legacy_file_does_not_migrate_it_by_itself(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        legacy_path = tmp_path / ".ducta" / "chain_state" / "sales.daily.json"
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(
            json.dumps(
                {"pipeline": "sales.daily", "start_date": "2024-01-01", "end_date": "2024-01-02"}
            ),
            encoding="utf-8",
        )

        dev = _executor("dev")
        dev._load_chain_state("sales.daily")

        assert not (tmp_path / ".ducta" / "chain_state" / "dev" / "sales.daily.json").exists()

    def test_a_new_recorded_run_lands_in_the_new_per_env_path_not_the_legacy_one(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        legacy_path = tmp_path / ".ducta" / "chain_state" / "sales.daily.json"
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(
            json.dumps(
                {"pipeline": "sales.daily", "start_date": "2024-01-01", "end_date": "2024-01-02"}
            ),
            encoding="utf-8",
        )

        dev = _executor("dev")
        dev._record_chain_state("sales.daily", PipelineType.BATCH, "2026-05-01", "2026-05-02")

        new_path = tmp_path / "dev" / ".ducta" / "chain_state" / "sales.daily.json"
        assert new_path.exists()
        assert json.loads(new_path.read_text())["start_date"] == "2026-05-01"
        # legacy file is left untouched, not deleted
        assert json.loads(legacy_path.read_text())["start_date"] == "2024-01-01"


class TestChainStatePerEnvLegacyFallback:
    """The pre-convention default (`.ducta/chain_state/<env>/<pipeline>.json`,
    relative to cwd — what CHAIN_STATE_DIR/`_chain_state_path` wrote before
    chain state moved under `${output_path}/${environment}/`) is read as a
    fallback between the current path and the oldest flat-file layout.
    """

    def test_load_falls_back_to_the_pre_convention_per_env_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        legacy_path = tmp_path / ".ducta" / "chain_state" / "dev" / "sales.daily.json"
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(
            json.dumps(
                {"pipeline": "sales.daily", "start_date": "2025-03-01", "end_date": "2025-03-02"}
            ),
            encoding="utf-8",
        )

        dev = _executor("dev")
        data = dev._load_chain_state("sales.daily")

        assert data is not None
        assert data["start_date"] == "2025-03-01"

    def test_current_path_wins_over_the_pre_convention_per_env_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        legacy_path = tmp_path / ".ducta" / "chain_state" / "dev" / "sales.daily.json"
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text(
            json.dumps(
                {"pipeline": "sales.daily", "start_date": "2025-03-01", "end_date": "2025-03-02"}
            ),
            encoding="utf-8",
        )

        dev = _executor("dev")
        dev._record_chain_state("sales.daily", PipelineType.BATCH, "2026-05-01", "2026-05-02")

        assert dev._load_chain_state("sales.daily")["start_date"] == "2026-05-01"
