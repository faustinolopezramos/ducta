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

A problem the UI can act on: where it is, what it is about, how to fix it.
"""

from __future__ import annotations

from typing import Iterable, List, Literal, Optional

from pydantic import BaseModel, Field

from ducta.setting.problems import Problem, parse_problems


class ProblemFixModel(BaseModel):
    label: str
    replace: List[str] = Field(description="[old, new] — replace the first in the problem's file")


class ProblemModel(BaseModel):
    severity: Literal["error", "warning", "info"]
    message: str
    code: str = Field(description="Stable kind, e.g. unknown_dataset, cycle, unknown_key")
    source: str = Field(description="Which check found it: config, graph, code, preflight")
    file: Optional[str] = Field(default=None, description="Project-relative path")
    line: Optional[int] = None
    column: Optional[int] = None
    node: Optional[str] = None
    pipeline: Optional[str] = None
    dataset: Optional[str] = None
    fix: Optional[ProblemFixModel] = None

    @classmethod
    def from_problem(cls, problem: Problem) -> "ProblemModel":
        return cls.model_validate(problem.to_dict())


def problem_models(
    errors: Iterable[str] = (), warnings: Iterable[str] = (), source: str = "config"
) -> List[ProblemModel]:
    return [ProblemModel.from_problem(p) for p in parse_problems(errors, warnings, source)]
