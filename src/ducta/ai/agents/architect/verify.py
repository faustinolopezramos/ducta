"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

Ducta Architect, step three: what was built, checked as it now stands.

Validates every environment; on request, runs the pipelines in a
non-protected environment (dev), in dependency order, and freezes each node's
inputs as a snapshot test. It never runs in a protected environment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ducta.ai.errors import AIConfigError


@dataclass
class VerifyReport:
    pipelines: List[str]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    runs: List[Dict[str, Any]] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and all(r.get("ok") for r in self.runs)

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


def _in_dependency_order(project: Any, names: Sequence[str]) -> List[str]:
    done: List[str] = []
    pending = list(names)
    while pending:
        ready = [
            p
            for p in pending
            if all(d in done or d not in names for d in project.pipelines[p].depends_on)
        ]
        if not ready:
            return done + pending
        done.append(ready[0])
        pending.remove(ready[0])
    return done


def verify(
    root: Path,
    pipelines: Sequence[str],
    *,
    env: str = "dev",
    run: bool = False,
    tests: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> VerifyReport:
    """Check *pipelines* as the project now has them; run and snapshot them in *env* if asked."""
    from ducta.ai.builder import _describe, _validate
    from ducta.api.services.governance import protected_environments
    from ducta.setting.project_loader import ProjectConfigError, validate_project

    root = Path(root).resolve()
    try:
        project = validate_project(root)
    except ProjectConfigError as e:
        return VerifyReport(list(pipelines), errors=list(e.problems))
    names = list(pipelines) or sorted(project.pipelines)
    unknown = [p for p in names if p not in project.pipelines]
    if unknown:
        raise AIConfigError(f"No pipeline {', '.join(unknown)} in the project")
    report = VerifyReport(_in_dependency_order(project, names))

    for p in _validate(root, {}):
        if p.get("pipeline") not in (None, *names) and p.get("node") is None:
            continue
        line = _describe(p)
        if p.get("severity") == "error":
            report.errors.append(line)
        elif p.get("pipeline") in names:
            report.warnings.append(line)
    # The deep preflight (imports the modules, checks write modes against formats…).
    for line in _preflight(root, env, names):
        if line not in report.errors:
            report.errors.append(line)
    if report.errors or not run:
        if not run and not report.errors:
            report.next_steps.append(
                f"ducta ai architect verify {' '.join(report.pipelines)} --run   # run them in {env}"
            )
        return report

    if env in protected_environments(root):
        raise AIConfigError(
            f"{env} is a protected environment: Architect only runs in dev-like ones"
        )
    from ducta.ai.agents.runs import run_pipeline

    for name in report.pipelines:
        needs_dates = project.pipelines[name].requires_dates
        if needs_dates and not (start_date and end_date):
            report.runs.append(
                {
                    "pipeline": name,
                    "ok": False,
                    "exit_code": None,
                    "output": "needs --start-date/--end-date",
                }
            )
            break
        outcome = run_pipeline(
            root,
            env,
            name,
            start_date=start_date if needs_dates else None,
            end_date=end_date if needs_dates else None,
        )
        report.runs.append(
            {
                "pipeline": name,
                "ok": outcome.ok,
                "exit_code": outcome.exit_code,
                "output": outcome.output[-2000:],
            }
        )
        if not outcome.ok:
            report.next_steps.append(
                f"ducta ai fix {name} --error-file <the output above>   # or: ducta ai explain"
            )
            break

    if tests and report.runs and all(r["ok"] for r in report.runs):
        report.tests = _snapshot_tests(root, project, report.pipelines, env)
    for name in report.pipelines:
        for node, spec in project.pipelines[name].nodes.items():
            if getattr(spec, "run", None) and getattr(spec, "outputs", None):
                report.next_steps.append(
                    f"ducta ai quality {name} {node} --env {env}   # checks proven on the real output"
                )
    return report


def _preflight(root: Path, env: str, names: Sequence[str]) -> List[str]:
    """``ducta config validate`` in a child process: its errors on *names*."""
    import json
    import subprocess

    from ducta.ai.agents.runs import ducta_command

    try:
        done = subprocess.run(
            ducta_command("config", "validate", "--env", env, "--output-format", "json"),
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return [f"`ducta config validate` did not run: {e}"]
    text = done.stdout or ""
    try:
        data = json.loads(text[text.index("{") :])
    except ValueError:
        return [] if done.returncode == 0 else [f"`ducta config validate` exited {done.returncode}"]
    out = [
        str(p.get("message"))
        for p in data.get("config_error") or []
        if p.get("severity") == "error"
    ]
    for name, found in (data.get("pipelines") or {}).items():
        if name in names:
            out += [
                f"{name}: {p.get('message')}"
                for p in found.get("problems") or []
                if p.get("severity") == "error"
            ]
    return out


def _snapshot_tests(root: Path, project: Any, names: Sequence[str], env: str) -> List[str]:
    from ducta.api.services.code_index import module_file
    from ducta.api.services.node_tests import generate_snapshot_test

    written: List[str] = []
    for name in names:
        for node, spec in project.pipelines[name].nodes.items():
            run = getattr(spec, "run", None)
            if not run or ":" not in run:
                continue
            module, function = run.split(":", 1)
            try:
                out = generate_snapshot_test(
                    project_root=root,
                    env=env,
                    node=node,
                    module=module,
                    function=function,
                    source_file=module_file(root, module),
                    inputs=dict(getattr(spec, "inputs", None) or {}),
                    output=(list(getattr(spec, "outputs", None) or []) or [None])[0],
                )
            except (FileExistsError, LookupError) as e:
                written.append(f"{node}: skipped ({e})")
                continue
            written.append(str(out.get("test_file") or node))
    return written
