"""`ExecutionManager.execute` takes the project root as given — even relative.

The FastAPI tutorial passes `Path("./my_project")`. The run resolved data paths
against that relative root from another working directory, found no inputs, and
reported the pipeline "skipped" with exit code 0.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ducta.api.execution.manager import ExecutionManager


def test_a_relative_source_path_reaches_the_run_absolute(tmp_path, monkeypatch):
    (tmp_path / "my_project").mkdir()
    monkeypatch.chdir(tmp_path)
    seen = {}

    async def capture(self, execution_id, spec):
        seen["source_path"] = spec.source_path

    monkeypatch.setattr(ExecutionManager, "_run_execution", capture)

    async def scenario():
        manager = ExecutionManager()
        record = manager.execute(source_path=Path("./my_project"), pipeline_name="etl", env="dev")
        await asyncio.sleep(0)  # let the scheduled task start
        await asyncio.sleep(0)
        return record

    record = asyncio.run(scenario())

    expected = (tmp_path / "my_project").resolve()
    assert seen["source_path"] == expected
    assert Path(seen["source_path"]).is_absolute()
    assert record.workspace == str(expected)
