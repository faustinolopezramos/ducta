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

How well a model drafts for Ducta, measured: ``ducta ai eval``.

Every case runs on a fresh copy of the ``medallion_basic`` template (the
``shop`` project: one ``etl`` pipeline, no data of yours) in a temporary
folder that is deleted afterwards. Nothing is applied anywhere. A case passes
when Ducta's own checks say so — a draft that validates and has what the case
expects, a review or explanation the model answered readably — so the result
does not depend on anyone's judgement and can be compared across models and
prompt versions (each result records ``prompt_version``).

A model does not answer the same way twice, so a case can run ``repeat``
times, each on its own copy: it passes only when every run does, and one that
passes some runs is *flaky*. Every report is kept in ``~/.ducta/ai/evals/``
(``DUCTA_HOME``), the CLI's and the server's alike, so two models — or two
versions of Ducta's prompts — can be compared later (:func:`compare`).

The template itself goes to the model, so with a remote provider the CLI and
the API ask before it runs. No project is read, so a project's ``ai:`` policy
does not apply.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ducta.ai.drafts import Draft, add_usage
from ducta.ai.errors import AICancelledError, AIConfigError, AIError, AINotFoundError
from ducta.ai.providers import LLMProvider

#: The template every case starts from.
TEMPLATE = "medallion_basic"
#: Reports kept in the history (the oldest are removed first).
MAX_REPORTS = 50
#: Most runs per case.
MAX_REPEAT = 10
#: The kinds that end in a draft (they count attempts).
DRAFT_KINDS = ("new", "fix", "extend", "revise", "architect")


@dataclass(frozen=True)
class EvalCase:
    id: str
    #: ``new``, ``fix``, ``extend``, ``revise``, ``architect``, ``review`` or ``explain``.
    kind: str
    #: What the model is asked: a request (``new``, ``extend``, ``revise``,
    #: ``architect``), a note (``fix``), unused otherwise.
    prompt: str = ""
    #: The pipeline a ``fix``, ``extend`` or ``review`` is about.
    pipeline: str = "etl"
    #: Text replacements in the project's files before the case runs (how a fix is broken).
    breaks: Dict[str, Sequence[str]] = field(default_factory=dict)
    #: Text the drafted pipeline file must contain (``new``, ``extend``, ``revise``).
    expect: Sequence[str] = ()
    #: ``revise``: the change asked for after the first draft.
    note: str = ""
    #: What the case is about, in a few words (the web app lists it).
    about: str = ""


CASES: List[EvalCase] = [
    EvalCase(
        "new-gold-daily",
        "new",
        "gold pipeline that sums the amount per order_date from silver.etl.clean_data",
        expect=("silver.etl.clean_data",),
        about="gold pipeline that sums the amount per order_date",
    ),
    EvalCase(
        "new-silver-filter",
        "new",
        "silver pipeline that keeps only the orders with an amount above 100, "
        "reading bronze.etl.raw_data",
        expect=("bronze.etl.raw_data",),
        about="silver pipeline that keeps the orders above 100",
    ),
    EvalCase(
        "new-spanish",
        "new",
        "pipeline gold que cuente los pedidos por categoría a partir de silver.etl.clean_data",
        expect=("silver.etl.clean_data",),
        about="the same kind of request, asked in Spanish",
    ),
    EvalCase(
        "fix-wrong-dataset",
        "fix",
        breaks={
            "pipelines/etl.yaml": (
                "inputs: {raw_data: bronze.etl.raw_data}",
                "inputs: {raw_data: bronze.etl.raw_dta}",
            )
        },
        about="an input names a dataset that does not exist",
    ),
    EvalCase(
        "fix-missing-function",
        "fix",
        breaks={
            "pipelines/etl.yaml": ("run: pipelines.etl:load\n", "run: pipelines.etl:load_data\n")
        },
        about="a node runs a function that is not there",
    ),
    EvalCase(
        "extend-add-node",
        "extend",
        "a node that counts the orders per category, reading silver.etl.clean_data",
        expect=("silver.etl.clean_data",),
        about="a new node, the existing ones left as they are",
    ),
    EvalCase(
        "revise-draft",
        "revise",
        "gold pipeline that sums the amount per order_date from silver.etl.clean_data",
        expect=("order_count",),
        note="also count the orders of each day, in a column named order_count",
        about="a draft changed with a note (add order_count)",
    ),
    EvalCase(
        "architect-plan",
        "architect",
        "a gold pipeline that sums the amount per category from silver.etl.clean_data",
        about="a blueprint for the amount per category",
    ),
    EvalCase("review-pipeline", "review", about="review the etl pipeline"),
    EvalCase("explain-keyerror", "explain", about="explain a KeyError in transform"),
]

#: The failure ``explain-keyerror`` explains: what Ducta's diagnosis of it would say.
_DIAGNOSIS = {
    "kind": "code",
    "title": "KeyError in node transform",
    "message": "KeyError: 'amount_usd'",
    "node": "transform",
}
_ERROR = (
    "Traceback (most recent call last):\n"
    '  File "pipelines/etl.py", in transform\n'
    "    df = df[df['amount_usd'] > 0]\n"
    "KeyError: 'amount_usd'\n"
)


@dataclass
class EvalResult:
    case: str
    kind: str
    passed: bool
    seconds: float
    #: Validation attempts, added up over the runs (drafts only).
    attempts: int = 0
    usage: Dict[str, int] = field(default_factory=dict)
    prompt_version: str = ""
    #: Why it did not pass, in Ducta's words (the first few).
    misses: List[str] = field(default_factory=list)
    #: How many times the case ran, and how many of those passed.
    runs: int = 1
    passes: int = 0

    @property
    def flaky(self) -> bool:
        return 0 < self.passes < self.runs


@dataclass
class EvalReport:
    provider: str
    model: str
    created_at: str
    results: List[EvalResult]
    repeat: int = 1
    #: The name it is kept under in the history (empty until saved).
    id: str = ""
    #: Who ran it: ``cli`` or ``server`` (empty in a report from before it was recorded).
    source: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    def summary(self) -> Dict[str, Any]:
        drafts = [r for r in self.results if r.kind in DRAFT_KINDS]
        draft_runs = sum(r.runs for r in drafts)
        return {
            "passed": self.passed,
            "total": len(self.results),
            "pass_rate": round(self.passed / len(self.results), 3) if self.results else 0.0,
            "flaky": [r.case for r in self.results if r.flaky],
            "mean_attempts": (
                round(sum(r.attempts for r in drafts) / draft_runs, 2) if draft_runs else 0.0
            ),
            "seconds": round(sum(r.seconds for r in self.results), 1),
            "usage": add_usage(*(r.usage for r in self.results)),
        }

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["summary"] = self.summary()
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvalReport":
        known = set(EvalResult.__dataclass_fields__)
        results = [
            EvalResult(**{k: v for k, v in r.items() if k in known})
            for r in data.get("results") or []
        ]
        return cls(
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            created_at=str(data.get("created_at") or ""),
            results=results,
            repeat=int(data.get("repeat") or 1),
            id=str(data.get("id") or ""),
            source=str(data.get("source") or ""),
        )

    def head(self) -> Dict[str, Any]:
        """What a list of reports shows: who, when, and how it went."""
        summary = self.summary()
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "repeat": self.repeat,
            "source": self.source,
            "cases": [r.case for r in self.results],
            **{k: summary[k] for k in ("passed", "total", "pass_rate", "flaky", "usage")},
        }


def select(ids: Optional[Sequence[str]] = None) -> List[EvalCase]:
    """The cases named by *ids* (all when none), refusing an unknown one."""
    if not ids:
        return list(CASES)
    known = {c.id: c for c in CASES}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise AIConfigError(
            f"Unknown eval case(s): {', '.join(unknown)}. Cases: {', '.join(known)}"
        )
    return [known[i] for i in ids]


def make_template(folder: Path) -> Path:
    """The ``shop`` project from the template, in *folder*."""
    from ducta.console.template import TemplateCommand

    target = folder / "shop"
    command = TemplateCommand()
    # Its "Created … / Next:" summary is for a person creating a project. Silenced
    # on this instance only: redirecting sys.stdout would silence the whole process —
    # every other request of the API server that runs an evaluation.
    command._show_success_message = lambda *args, **kwargs: None  # type: ignore[method-assign]
    code = command.handle_template_command(
        template_type=TEMPLATE, project_name="shop", output_path=str(target)
    )
    if code != 0 or not (target / "ducta.yaml").is_file():
        raise AIConfigError(f"The {TEMPLATE} template could not be created for the evaluation")
    return target


def _break(root: Path, case: EvalCase) -> None:
    for rel, (old, new) in case.breaks.items():
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if old not in text:
            raise AIConfigError(f"Eval case {case.id}: '{old.strip()}' is not in {rel}")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _take_draft(result: EvalResult, draft: Draft, case: EvalCase, *, add: bool = False) -> None:
    """What *draft* says about *case*: attempts, tokens, and what keeps it from passing."""
    from ducta.ai.builder import is_pipeline_file

    result.attempts += len(draft.attempts)
    result.usage = add_usage(result.usage, draft.usage) if add else draft.usage
    result.prompt_version = draft.prompt_version
    result.misses = [str(p.get("message")) for p in draft.blocking][:3]
    if not draft.ok and not result.misses:
        result.misses = ["the draft does not validate"]
    pipeline_text = "\n".join(text for rel, text in draft.files.items() if is_pipeline_file(rel))
    result.misses += [
        f"the pipeline does not mention {e}" for e in case.expect if e not in pipeline_text
    ]
    result.passed = draft.ok and not result.misses


def run_case(
    root: Path,
    case: EvalCase,
    provider: LLMProvider,
    *,
    should_stop: Optional[Callable[[], bool]] = None,
) -> EvalResult:
    """Run *case* once on the project at *root* (a copy it may change)."""
    from ducta.ai.builder import fix, generate, revise

    _break(root, case)
    started = time.monotonic()
    result = EvalResult(case=case.id, kind=case.kind, passed=False, seconds=0.0)
    try:
        if case.kind == "new":
            _take_draft(
                result, generate(root, case.prompt, provider, should_stop=should_stop), case
            )
        elif case.kind == "fix":
            _take_draft(
                result,
                fix(root, case.pipeline, provider, note=case.prompt, should_stop=should_stop),
                case,
            )
        elif case.kind == "extend":
            from ducta.ai.extend import extend, extension_summary

            draft = extend(root, case.pipeline, case.prompt, provider, should_stop=should_stop)
            _take_draft(result, draft, case)
            if draft.ok and not extension_summary(root, draft)["nodes"]:
                result.misses.append("no node was added")
                result.passed = False
        elif case.kind == "revise":
            first = generate(root, case.prompt, provider, should_stop=should_stop)
            if not first.ok:
                _take_draft(result, first, case)
                result.misses.insert(0, "the first draft does not validate")
                result.passed = False
            else:
                result.attempts = len(first.attempts)
                result.usage = first.usage
                _take_draft(
                    result,
                    revise(root, first, case.note, provider, should_stop=should_stop),
                    case,
                    add=True,
                )
        elif case.kind == "architect":
            from ducta.ai.agents.architect.design import design

            _take_draft(result, design(root, case.prompt, provider, should_stop=should_stop), case)
        elif case.kind == "review":
            from ducta.ai.pipeline_review import review_pipeline

            review = review_pipeline(root, case.pipeline, provider)
            result.usage, result.prompt_version = review.usage, review.prompt_version
            result.misses = [review.notes] if review.notes else []
            if review.dropped:
                result.misses.append(f"{review.dropped} finding(s) cited nothing real")
            result.passed = not review.notes
        elif case.kind == "explain":
            from ducta.ai.explain import explain_failure

            explanation = explain_failure(root, dict(_DIAGNOSIS), _ERROR, provider)
            result.usage, result.prompt_version = explanation.usage, explanation.prompt_version
            parts = ("What happened", "Why", "What to do")
            result.misses = [f"no '{p}' part" for p in parts if p not in explanation.text]
            if "amount_usd" not in explanation.text:
                result.misses.append("does not name the missing column")
            result.passed = not result.misses
        else:
            raise AIConfigError(f"Eval case {case.id}: unknown kind '{case.kind}'")
    except (AIConfigError, AICancelledError):
        raise
    except AIError as e:
        result.misses = [e.message]
        result.passed = False
    result.passes = int(result.passed)
    result.seconds = round(time.monotonic() - started, 2)
    return result


def _merge(runs: List[EvalResult]) -> EvalResult:
    """One result for a case that ran several times: it passes only if every run did."""
    first = runs[0]
    misses: List[str] = []
    for run in runs:
        misses += [m for m in run.misses if m not in misses]
    return EvalResult(
        case=first.case,
        kind=first.kind,
        passed=all(r.passed for r in runs),
        seconds=round(sum(r.seconds for r in runs), 2),
        attempts=sum(r.attempts for r in runs),
        usage=add_usage(*(r.usage for r in runs)),
        prompt_version=runs[-1].prompt_version,
        misses=misses[:5],
        runs=len(runs),
        passes=sum(1 for r in runs if r.passed),
    )


def run_eval(
    provider: LLMProvider,
    cases: Optional[Sequence[EvalCase]] = None,
    *,
    repeat: int = 1,
    on_result: Optional[Callable[[EvalResult], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> EvalReport:
    """Every case, *repeat* times, each run on its own fresh copy; nothing is kept.

    *should_stop* is asked before every run and passed on to the drafts: when
    it says so, :class:`AICancelledError` ends the evaluation (no report).
    """
    if not 1 <= repeat <= MAX_REPEAT:
        raise AIConfigError(f"--repeat goes from 1 to {MAX_REPEAT}")
    results: List[EvalResult] = []
    with tempfile.TemporaryDirectory(prefix="ducta-ai-eval-") as tmp:
        template = make_template(Path(tmp))
        n = 0
        for case in cases or CASES:
            runs: List[EvalResult] = []
            for _ in range(repeat):
                if should_stop and should_stop():
                    raise AICancelledError("The evaluation was stopped")
                root = Path(tmp) / f"case-{n}"
                n += 1
                shutil.copytree(template, root)
                runs.append(run_case(root, case, provider, should_stop=should_stop))
                shutil.rmtree(root, ignore_errors=True)
            result = _merge(runs)
            results.append(result)
            if on_result:
                on_result(result)
    return EvalReport(
        provider=provider.config.provider,
        model=provider.config.model or "",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        results=results,
        repeat=repeat,
    )


# ── history ─────────────────────────────────────────────────────────────────


def reports_dir() -> Path:
    from ducta.ai.config import ducta_home

    return ducta_home() / "ai" / "evals"


REPORT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-z0-9._-]{1,80}\Z")


def _report_id(report: EvalReport) -> str:
    stamp = re.sub(r"[-:]", "", report.created_at.replace("+00:00", "Z"))
    slug = re.sub(r"[^a-z0-9._-]+", "-", report.model.lower()).strip("-")[:60] or "model"
    return f"{stamp}-{slug}"


def save_report(report: EvalReport) -> Path:
    """Keep *report* in the history (it gets its ``id``), dropping the oldest past
    :data:`MAX_REPORTS`."""
    folder = reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    base = _report_id(report)
    report.id, n = base, 1
    while (folder / f"{report.id}.json").exists():
        n += 1
        report.id = f"{base}-{n}"
    path = folder / f"{report.id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    for old in sorted(folder.glob("*.json"))[:-MAX_REPORTS]:
        old.unlink(missing_ok=True)
    return path


def list_reports() -> List[EvalReport]:
    """The kept reports, newest first (an unreadable file is skipped)."""
    out: List[EvalReport] = []
    folder = reports_dir()
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json"), reverse=True):
        try:
            report = EvalReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
        report.id = path.stem
        out.append(report)
    return out


def load_report(ref: str) -> EvalReport:
    """A kept report by its id, or a report file (``--out``) by its path."""
    path = reports_dir() / f"{ref}.json" if REPORT_ID.match(ref) else Path(ref).expanduser()
    if not path.is_file():
        raise AINotFoundError(f"No eval report '{ref}'. See `ducta ai eval --list`")
    try:
        report = EvalReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as e:
        raise AIConfigError(f"'{ref}' is not an eval report: {e}") from e
    report.id = report.id or path.stem
    return report


def previous_report(report: EvalReport) -> Optional[EvalReport]:
    """The newest kept report of the same provider and model made before *report*."""
    for other in list_reports():
        if (
            other.id != report.id
            and other.provider == report.provider
            and other.model == report.model
            and other.created_at <= report.created_at
        ):
            return other
    return None


def _score(result: Optional[EvalResult]) -> Optional[str]:
    return f"{result.passes}/{result.runs}" if result else None


def compare(a: EvalReport, b: EvalReport) -> Dict[str, Any]:
    """What changed from report *a* to report *b*, case by case."""
    before = {r.case: r for r in a.results}
    after = {r.case: r for r in b.results}
    cases: List[Dict[str, Any]] = []
    for case in list(before) + [c for c in after if c not in before]:
        old, new = before.get(case), after.get(case)
        if old is None:
            change = "added"
        elif new is None:
            change = "removed"
        elif new.passed and not old.passed:
            change = "gained"
        elif old.passed and not new.passed:
            change = "lost"
        else:
            change = "same"
        cases.append(
            {
                "case": case,
                "a": _score(old),
                "b": _score(new),
                "change": change,
                # Only when both are known: a case whose model never answered has none.
                "prompt_changed": bool(
                    old
                    and new
                    and old.prompt_version
                    and new.prompt_version
                    and old.prompt_version != new.prompt_version
                ),
            }
        )
    sa, sb = a.summary(), b.summary()

    def tokens(summary: Dict[str, Any]) -> int:
        usage = summary["usage"]
        return int(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))

    return {
        "a": a.head(),
        "b": b.head(),
        "cases": cases,
        "pass_rate": round(sb["pass_rate"] - sa["pass_rate"], 3),
        "mean_attempts": round(sb["mean_attempts"] - sa["mean_attempts"], 2),
        "seconds": round(sb["seconds"] - sa["seconds"], 1),
        "tokens": tokens(sb) - tokens(sa),
    }


__all__ = [
    "CASES",
    "EvalCase",
    "EvalReport",
    "EvalResult",
    "compare",
    "list_reports",
    "load_report",
    "previous_report",
    "run_case",
    "run_eval",
    "save_report",
    "select",
]
