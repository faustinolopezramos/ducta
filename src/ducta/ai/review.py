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

A review of one node: its code and how it is set to run.

Two passes, and Ducta has the last word on both:

* :func:`ducta_checks` — what Ducta can tell for certain, without a model: a
  retried node that appends (duplicate rows), runs close to their timeout,
  I/O or ``collect()`` inside the node's function, a credential in the code,
  dates the function cannot receive, an output others read with no checks.
* :func:`review_node` — those findings, plus the model's, from the node's code
  (numbered), its effective settings in the environment, how long its last
  runs took and what the validator says. A finding of the model's must point
  at something real: a line of the node's function (and quote it), or a
  setting the node has. One that does not is dropped and counted.

A review changes nothing. Each finding says what to do; turning one into a
change is a fix draft (``ducta ai fix PIPELINE --note …``), reviewed like any other.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml  # type: ignore[import-untyped]

from ducta.ai.builder import _pipeline_file, _validate, parse_answer
from ducta.ai.context import find_secrets, redact_code, redact_config
from ducta.ai.errors import AINotFoundError
from ducta.ai.explain import node_function
from ducta.ai.providers import ChatMessage, LLMProvider

SEVERITIES = ("high", "medium", "low")
AREAS = ("code", "config", "performance", "quality", "security")
#: The most findings of the model's that are kept.
MAX_AI_FINDINGS = 8
#: The most lines of the node's function sent.
MAX_FUNCTION_LINES = 200
#: Runs looked at for durations.
RECENT_RUNS = 10
#: The framework's per-node limit when nothing sets one (settings.node_timeout_seconds).
DEFAULT_NODE_TIMEOUT = 1800

REVIEW_PROMPT = """\
You review one node of a Ducta data pipeline: its Python function and how it \
is set to run. Ducta gives you the facts and the findings it is sure of; add \
what it cannot see — logic errors, wrong assumptions about the data, wasteful \
Spark or pandas, settings that do not fit what the runs show.

Answer with ONE fenced block, ```yaml review, then nothing else:
```yaml review
findings:
  - severity: high | medium | low
    area: code | config | performance | quality | security
    title: <what is wrong, in at most 10 words>
    line: <line number of the node's function, when it is about code>
    code: <the exact text of that line, or the part of it that matters>
    key: <the setting it is about, e.g. retry, timeout_seconds, settings.shuffle_partitions>
    detail: <why it matters here, one or two sentences>
    suggestion: <the smallest change that fixes it>
```
Rules:
- At most {max} findings, the most important first. None is a fine answer: \
`findings: []`.
- A finding about code gives `line` and `code` copied from the numbered code \
exactly; Ducta drops one whose line or text does not match.
- Do not repeat what Ducta already found. Do not invent columns, files or \
settings. Prefer facts from the runs over guesses.
- Write title, detail and suggestion in the language of the user's note, or \
English.
"""


@dataclass
class Finding:
    severity: str
    area: str
    title: str
    detail: str = ""
    suggestion: str = ""
    file: Optional[str] = None
    line: Optional[int] = None
    code: Optional[str] = None
    key: Optional[str] = None
    #: ``ducta`` (certain) or ``ai`` (the model's, checked against the code).
    source: str = "ducta"
    #: In a pipeline's review: the node it is about (``None``: the pipeline itself).
    node: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewFacts:
    """What Ducta knows about the node before anyone reviews it."""

    pipeline: str
    pipeline_rel: str
    node: str
    env: str
    spec: Dict[str, Any]
    pipeline_settings: Dict[str, Any]
    settings: Dict[str, Any]
    #: Effective value and where it comes from, per node setting.
    effective: Dict[str, Tuple[Any, str]] = field(default_factory=dict)
    #: The function the node runs: file, first and last line, name, parameters.
    function: Optional[Dict[str, Any]] = None
    code_lines: List[str] = field(default_factory=list)
    #: Seconds per successful run, newest first.
    durations: List[float] = field(default_factory=list)
    #: How each output is written (``overwrite``, ``append``, ``merge``…).
    write_modes: Dict[str, str] = field(default_factory=dict)
    #: Nodes elsewhere that read this node's outputs.
    readers: Dict[str, List[str]] = field(default_factory=dict)
    problems: List[Dict[str, Any]] = field(default_factory=list)

    def numbered_code(self, remote: bool) -> str:
        if not self.function:
            return ""
        start = self.function["line"]
        shown = "\n".join(f"{start + i:>4}  {text}" for i, text in enumerate(self.code_lines))
        return redact_code(shown) if remote and find_secrets(shown) else shown

    def line_text(self, line: int) -> Optional[str]:
        if not self.function:
            return None
        i = line - self.function["line"]
        return self.code_lines[i] if 0 <= i < len(self.code_lines) else None


@dataclass
class Review:
    pipeline: str
    node: str
    env: str
    created_at: str
    findings: List[Finding]
    #: The model that added findings; ``None`` when only Ducta's checks ran.
    model: Optional[str] = None
    #: Findings of the model's dropped: they pointed at nothing real.
    dropped: int = 0
    notes: str = ""
    usage: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["findings"] = [f.to_dict() for f in self.findings]
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Review":
        data = dict(data)
        fields = set(Finding.__dataclass_fields__)
        data["findings"] = [
            Finding(**{k: v for k, v in f.items() if k in fields})
            for f in data.get("findings") or []
        ]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


# ── facts ───────────────────────────────────────────────────────────────────


def _function_info(root: Path, node: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    where = node_function(root, node)
    if not where:
        return None, []
    lines = (root / where["file"]).read_text(encoding="utf-8").splitlines()
    end = min(where["end"], where["line"] + MAX_FUNCTION_LINES - 1, len(lines))
    code = lines[where["line"] - 1 : end]
    try:
        fn = next(
            n
            for n in ast.parse("\n".join(lines)).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == where["function"]
        )
        args = fn.args
        where["params"] = [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]
        where["varkw"] = args.kwarg is not None
    except (StopIteration, SyntaxError):
        where["params"], where["varkw"] = [], False
    where["end"] = end
    return where, code


def _durations(root: Path, env: str, pipeline: str, node: str) -> List[float]:
    from ducta.api.services.run_certificates import certificates

    runs: List[Tuple[str, float]] = []
    for _env, cert in certificates(root, env):
        if cert.get("pipeline") != pipeline:
            continue
        for n in cert.get("nodes") or []:
            if n.get("name") == node and n.get("status") == "success" and n.get("duration_seconds"):
                runs.append((str(cert.get("started_at") or ""), float(n["duration_seconds"])))
    return [d for _, d in sorted(runs, reverse=True)[:RECENT_RUNS]]


def review_facts(
    root: Path,
    pipeline: str,
    node: str,
    env: str = "dev",
    *,
    resolved: Optional[Dict[str, Any]] = None,
    problems: Optional[List[Dict[str, Any]]] = None,
) -> ReviewFacts:
    """The node as it runs in *env*: settings, code, recent durations, problems.

    *resolved* (the project in *env*) and *problems* (the validator's) can be
    passed in when several nodes are looked at: they are the project's, not the node's.
    """
    from ducta.setting.node_effective_config import effective_node_config
    from ducta.setting.project_loader import apply_environment, read_project

    root = Path(root).resolve()
    path = _pipeline_file(root, pipeline)
    if resolved is None:
        resolved = apply_environment(read_project(root), env)
    pdoc = (resolved.get("pipelines") or {}).get(pipeline) or yaml.safe_load(
        path.read_text(encoding="utf-8")
    )
    nodes = (pdoc or {}).get("nodes") or {}
    if node not in nodes:
        raise AINotFoundError(
            f"No node '{node}' in pipeline '{pipeline}' (its nodes: {', '.join(nodes) or 'none'})"
        )
    facts = ReviewFacts(
        pipeline=pipeline,
        pipeline_rel=path.relative_to(root).as_posix(),
        node=node,
        env=env,
        spec=dict(nodes[node] or {}),
        pipeline_settings={k: v for k, v in (pdoc or {}).items() if k != "nodes"},
        settings=dict(resolved.get("settings") or {}),
    )
    try:
        table = effective_node_config(root, pipeline, node)
        column = env if env in table.get("environments", []) else "base"
        facts.effective = {
            row["key"]: (row["values"].get(column), row["sources"].get(column, ""))
            for row in table.get("rows", [])
        }
    except Exception:  # noqa: BLE001 — the node's own keys still say most
        facts.effective = {}
    facts.function, facts.code_lines = _function_info(root, node)
    facts.durations = _durations(root, env, pipeline, node)
    catalog = resolved.get("catalog") or {}
    for out in facts.spec.get("outputs") or []:
        found = catalog.get(out)
        entry: Dict[str, Any] = found if isinstance(found, dict) else {}
        raw_write = entry.get("write")
        write: Dict[str, Any] = raw_write if isinstance(raw_write, dict) else {}
        facts.write_modes[str(out)] = str(write.get("mode") or "overwrite")
    for pname, p in (resolved.get("pipelines") or {}).items():
        for nname, nspec in ((p or {}).get("nodes") or {}).items():
            ins = (nspec or {}).get("inputs") or {}
            values = ins.values() if isinstance(ins, dict) else ins
            for ds in values:
                if str(ds) in facts.write_modes and not (pname == pipeline and nname == node):
                    facts.readers.setdefault(str(ds), []).append(f"{pname}.{nname}")
    files = {facts.pipeline_rel, (facts.function or {}).get("file")}
    facts.problems = [
        p
        for p in (problems if problems is not None else _validate(root, {}))
        if p.get("severity") in ("error", "warning")
        and (
            p.get("node") == node
            or (p.get("file") in files and p.get("pipeline") in (None, pipeline))
        )
    ]
    return facts


# ── what Ducta can tell for certain ─────────────────────────────────────────

_PULLS = {"collect", "toPandas", "toLocalIterator"}
_ROW_BY_ROW = {"iterrows", "itertuples"}
#: ``save`` is not here: the name is too common (a model, a figure), and
#: Spark's ``df.write…save()`` is caught by its ``.write``.
_WRITES = {
    "to_csv",
    "to_parquet",
    "to_json",
    "to_excel",
    "saveAsTable",
    "insertInto",
    "to_sql",
    "to_pickle",
    "to_feather",
    "to_hdf",
    "to_orc",
    "to_stata",
    "to_xml",
    "to_gbq",
}
_READS = {
    "read_csv",
    "read_parquet",
    "read_json",
    "read_excel",
    "read_sql",
    "read_table",
    "read_sql_query",
    "read_sql_table",
    "read_pickle",
    "read_feather",
    "read_orc",
    "read_hdf",
    "read_xml",
    "read_html",
    "read_gbq",
    "read_fwf",
    "read_stata",
}
#: What the session of a Spark function is usually called (``spark.read``, ``self.spark.read``).
_SPARK_NAMES = {"spark", "sparkSession", "session"}
#: pandas' ``to_*`` writers return the text when given no path: serialising in memory.
_PATH_KEYWORDS = {
    "path",
    "path_or_buf",
    "path_or_buffer",
    "buf",
    "excel_writer",
    "fname",
    "file",
    "con",  # to_sql
    "destination_table",  # to_gbq
}
#: What a node's function has no business doing: running commands, reaching the
#: network, deleting files, evaluating text as code. Not a sandbox — a net that
#: catches the obvious, so the person reading the diff is told where to look.
_RISKY_MODULES = {
    "subprocess": "runs commands",
    "socket": "opens network connections",
    "requests": "calls the network",
    "httpx": "calls the network",
    "urllib.request": "calls the network",
    "urllib3": "calls the network",
    "http.client": "calls the network",
    "ftplib": "calls the network",
    "smtplib": "sends mail",
    "ctypes": "loads native code",
}
_RISKY_CALLS = {
    "os.system": "runs commands",
    "os.popen": "runs commands",
    "os.remove": "deletes files",
    "os.unlink": "deletes files",
    "os.rmdir": "deletes files",
    "shutil.rmtree": "deletes files",
    "eval": "runs text as code",
    "exec": "runs text as code",
    "compile": "runs text as code",
    "__import__": "imports by name",
    "importlib.import_module": "imports by name",
    "os.rename": "moves files",
    "os.replace": "moves files",
    "os.removedirs": "deletes files",
    "os.makedirs": "creates folders",
    "shutil.move": "moves files",
    "shutil.copy": "copies files",
    "shutil.copy2": "copies files",
    "shutil.copyfile": "copies files",
    "shutil.copytree": "copies files",
    "os.execv": "runs commands",
    "os.execve": "runs commands",
    "os.execvp": "runs commands",
    "os.execl": "runs commands",
    "os.spawnl": "runs commands",
    "os.spawnv": "runs commands",
    "pickle.load": "loads objects that run code",
    "pickle.loads": "loads objects that run code",
    "marshal.loads": "loads objects that run code",
    "cloudpickle.loads": "loads objects that run code",
}
#: ``Path(...).write_text()`` and friends, whatever the object is called.
_RISKY_METHODS = {"write_text", "write_bytes", "unlink", "rmdir"}
_SQL_CHANGES = ("drop", "delete", "insert", "truncate", "create", "alter", "merge", "update")


def _dotted(node: ast.AST) -> str:
    """``a.b.c`` for a name or an attribute chain, else ``""``."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _aliases(tree: ast.AST) -> Dict[str, str]:
    """Name → what it imports: ``import os as o`` gives ``o → os``; ``from os import system``
    gives ``system → os.system``."""
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out[a.asname] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _resolved(node: ast.AST, aliases: Dict[str, str]) -> str:
    """:func:`_dotted` with its first name replaced by what it was imported as."""
    dotted = _dotted(node)
    head, _, rest = dotted.partition(".")
    if head in aliases:
        return aliases[head] + ("." + rest if rest else "")
    return dotted


def _risk(item: ast.AST, aliases: Optional[Dict[str, str]] = None) -> Optional[Tuple[str, str]]:
    """``(what, why)`` when *item* (an import or a call) is something a node should not do."""
    aliases = aliases or {}
    if isinstance(item, ast.Import):
        names = [a.name for a in item.names]
    elif isinstance(item, ast.ImportFrom):
        names = [item.module or ""]
    elif isinstance(item, ast.Call):
        dotted = _resolved(item.func, aliases)
        if dotted in _RISKY_CALLS:
            return dotted, _RISKY_CALLS[dotted]
        if isinstance(item.func, ast.Attribute) and item.func.attr in _RISKY_METHODS:
            return item.func.attr, "writes or deletes files"
        if dotted.endswith("spark.sql") and item.args:
            first = item.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if first.value.lstrip().lower().startswith(_SQL_CHANGES):
                    return "spark.sql", "changes tables"
        return None
    else:
        return None
    for name in names:
        for module, why in _RISKY_MODULES.items():
            if name == module or name.startswith(module + "."):
                return module, why
    return None


def _in_memory(name: str, call: ast.Call) -> bool:
    """``df.to_json()`` with no path returns the text: nothing is written."""
    return (
        name.startswith("to_")
        and not call.args
        and not any(k.arg in _PATH_KEYWORDS for k in call.keywords)
    )


def _code_findings(facts: ReviewFacts) -> List[Finding]:
    if not facts.function:
        return []
    start = facts.function["line"]
    try:
        tree = ast.parse("\n".join(facts.code_lines))
    except SyntaxError:
        return []
    out: List[Finding] = []
    seen: Set[Tuple[str, int]] = set()
    aliases = _aliases(tree)

    def add(kind: str, node: ast.AST, finding: Finding) -> None:
        line = start + getattr(node, "lineno", 1) - 1
        if (kind, line) in seen:
            return
        seen.add((kind, line))
        finding.file, finding.line = facts.function["file"], line  # type: ignore[index]
        finding.code = (facts.line_text(line) or "").strip() or None
        out.append(finding)

    for item in ast.walk(tree):
        risky = _risk(item, aliases)
        if risky:
            what, why = risky
            add(
                "risk",
                item,
                Finding(
                    "high",
                    "security",
                    f"The code {why} (`{what}`)",
                    "A node's function transforms the DataFrames it receives; this reaches "
                    "outside them, and it runs with the same access as the pipeline.",
                    "Remove it, or move it out of the node (an ingest node, a source, a job of "
                    "its own). If it is intended, say so in the review.",
                ),
            )
        if not isinstance(item, ast.Call):
            continue
        name = (
            item.func.attr
            if isinstance(item.func, ast.Attribute)
            else item.func.id
            if isinstance(item.func, ast.Name)
            else ""
        )
        if isinstance(item.func, ast.Name) and name != "open":
            # ``from pandas import read_sql_query as q``: judged by what it is, not what it is called.
            name = aliases.get(name, name).rsplit(".", 1)[-1]
        if (
            isinstance(item.func, ast.Attribute)
            and item.func.attr == "table"
            and _resolved(item.func.value, aliases).split(".")[-1] in _SPARK_NAMES
        ):
            add(
                "io",
                item,
                Finding(
                    "medium",
                    "code",
                    "The function reads a table itself (`spark.table`)",
                    "Inputs read inside the function are invisible to Ducta: no lineage, no "
                    "fingerprint in the certificate, the same table in every environment.",
                    "Declare it in the catalog and take it as an input.",
                ),
            )
        if name in _PULLS:
            add(
                "pull",
                item,
                Finding(
                    "medium",
                    "performance",
                    f"`{name}()` brings every row to one machine",
                    "It loads the whole dataset into the driver's memory: fine on a sample, a crash on real volumes.",
                    "Keep the work in the DataFrame API (aggregate, join, filter) and return the DataFrame.",
                ),
            )
        elif name in _ROW_BY_ROW:
            add(
                "rows",
                item,
                Finding(
                    "medium",
                    "performance",
                    f"`{name}()` processes the data row by row",
                    "Python loops over rows are orders of magnitude slower than column operations.",
                    "Use vectorised column expressions instead.",
                ),
            )
        elif (
            (name in _WRITES and not _in_memory(name, item))
            or (name == "open" and isinstance(item.func, ast.Name))
            or name in _READS
        ):
            verb = "writes" if name in _WRITES else "reads"
            add(
                "io",
                item,
                Finding(
                    "medium",
                    "code",
                    f"The function {verb} files itself (`{name}`)",
                    "Ducta reads a node's inputs and writes its outputs from the catalog; I/O inside the "
                    "function escapes environments, lineage and the run certificate.",
                    "Declare the dataset in the catalog, take it as an input and return the result.",
                ),
            )
    # ``df.write.parquet(…)`` chains on ``.write``; ``f.write(text)`` calls it:
    # only the first is a DataFrame written by the function itself.
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Attribute)
            and item.attr in ("write", "writeStream")
            and isinstance(item.value, (ast.Name, ast.Attribute, ast.Call))
            and id(item) not in called
        ):
            add(
                "io",
                item,
                Finding(
                    "medium",
                    "code",
                    "The function writes a DataFrame itself (`.write`)",
                    "Ducta writes a node's outputs from the catalog; a write inside the function escapes "
                    "environments, lineage and the run certificate.",
                    "Return the DataFrame and let the node's output write it.",
                ),
            )
        if (
            isinstance(item, ast.Attribute)
            and item.attr in ("read", "readStream")
            and _resolved(item.value, aliases).split(".")[-1] in _SPARK_NAMES
        ):
            add(
                "io",
                item,
                Finding(
                    "medium",
                    "code",
                    "The function reads data itself (`spark.read`)",
                    "Inputs read inside the function are invisible to Ducta: no lineage, no fingerprint "
                    "in the certificate, the same path in every environment.",
                    "Declare it in the catalog and take it as an input.",
                ),
            )
    secrets = find_secrets("\n".join(facts.code_lines))
    if secrets:
        out.append(
            Finding(
                "high",
                "security",
                f"A credential is written in the code ({secrets[0]})",
                "Anyone who can read the repository can use it, and it travels with every copy.",
                "Read it from an environment variable or the source configuration instead.",
                file=facts.function["file"],
            )
        )
    return out


def _config_findings(facts: ReviewFacts) -> List[Finding]:
    out: List[Finding] = []
    retry = facts.effective.get("retry", (facts.spec.get("retry"), ""))[0] or 0
    appending = [ds for ds, mode in facts.write_modes.items() if mode == "append"]
    if retry and appending:
        out.append(
            Finding(
                "high",
                "config",
                "A retried node appends: a retry can duplicate rows",
                f"retry is {retry} and {', '.join(appending)} is written with mode append; an attempt "
                "that fails after writing part of it is written again.",
                "Write with mode merge (with keys) or overwrite a partition, or set retry: 0.",
                key="retry",
            )
        )
    timeout = facts.effective.get("timeout_seconds", (facts.spec.get("timeout_seconds"), ""))[0]
    limit = timeout or facts.settings.get("node_timeout_seconds") or DEFAULT_NODE_TIMEOUT
    if facts.durations and max(facts.durations) > 0.8 * float(limit):
        out.append(
            Finding(
                "medium",
                "config",
                "Runs come close to the node's timeout",
                f"The slowest of the last {len(facts.durations)} runs took {max(facts.durations):.0f} s "
                f"of a {float(limit):.0f} s limit; a little more data and it fails.",
                "Raise timeout_seconds for this node, or make it faster.",
                key="timeout_seconds",
            )
        )
    fn = facts.function or {}
    params = set(fn.get("params") or [])
    dates = {"start_date", "end_date"}
    requires = bool(facts.pipeline_settings.get("requires_dates"))
    if fn and requires and not (dates <= params or fn.get("varkw")):
        out.append(
            Finding(
                "medium",
                "config",
                "The pipeline requires dates the function cannot receive",
                f"requires_dates is true, but {fn.get('function')}() has no start_date/end_date "
                "parameters: the dates of a run never reach it.",
                "Add start_date and end_date parameters, or set requires_dates: false.",
                file=fn.get("file"),
                line=fn.get("line"),
                key="requires_dates",
            )
        )
    read_elsewhere = [ds for ds in facts.readers if facts.readers[ds]]
    if read_elsewhere and not facts.spec.get("quality"):
        users = sorted({u for ds in read_elsewhere for u in facts.readers[ds]})
        out.append(
            Finding(
                "low",
                "quality",
                "Other nodes read this output, and nothing checks it",
                f"{', '.join(users[:5])} read {', '.join(read_elsewhere)}; bad data here reaches them silently.",
                "Add a quality block (or `ducta ai quality " f"{facts.pipeline} {facts.node}`).",
                key="quality",
            )
        )
    for p in facts.problems:
        out.append(
            Finding(
                "high" if p.get("severity") == "error" else "low",
                "config",
                "The validator reports a problem",
                str(p.get("message") or ""),
                str(
                    ((p.get("fix") or {}).get("label")) or "Run `ducta config validate` and fix it."
                ),
                file=p.get("file"),
                line=p.get("line"),
            )
        )
    return out


def ducta_checks(facts: ReviewFacts) -> List[Finding]:
    """The findings Ducta is certain of, without a model."""
    order = {s: i for i, s in enumerate(SEVERITIES)}
    return sorted(_code_findings(facts) + _config_findings(facts), key=lambda f: order[f.severity])


# ── the model's findings, checked ───────────────────────────────────────────


def _known_keys() -> Set[str]:
    from ducta.setting.project_schema import PipelineFile, TransformNode

    return set(TransformNode.model_fields) | set(PipelineFile.model_fields) | {"description"}


_SETTINGS_KEYS = {
    "spark_config",
    "shuffle_partitions",
    "max_parallel_nodes",
    "node_timeout_seconds",
    "execution_timeout_seconds",
    "run_lock",
    "mode",
    "evidence_level",
    "fail_on_error",
}


def check_finding(raw: Any, facts: ReviewFacts) -> Optional[Finding]:
    """The model's finding if it points at something real, else ``None``."""
    if not isinstance(raw, dict):
        return None
    severity = str(raw.get("severity") or "").lower().strip()
    area = str(raw.get("area") or "").lower().strip()
    title = str(raw.get("title") or "").strip()
    if severity not in SEVERITIES or area not in AREAS or not title:
        return None
    finding = Finding(
        severity,
        area,
        title,
        detail=str(raw.get("detail") or "").strip(),
        suggestion=str(raw.get("suggestion") or "").strip(),
        source="ai",
    )
    line, code, key = raw.get("line"), raw.get("code"), raw.get("key")
    if line is not None:
        try:
            line = int(line)
        except (TypeError, ValueError):
            return None
        text = facts.line_text(line)
        if text is None:
            return None  # not a line of the node's function
        if code:
            wanted = re.sub(r"\s+", " ", str(code)).strip().strip("`")
            if wanted and wanted not in re.sub(r"\s+", " ", text):
                return None  # quotes text that is not on that line
        finding.file, finding.line, finding.code = facts.function["file"], line, text.strip()  # type: ignore[index]
    if key:
        key = str(key).strip()
        head, _, rest = key.partition(".")
        if head == "settings":
            if rest.split(".")[0] not in _SETTINGS_KEYS | set(facts.settings):
                return None
        elif head not in _known_keys():
            return None
        finding.key = key
    if line is None and not key and area in ("code", "security"):
        return None  # code findings must say where
    return finding


def _render(facts: ReviewFacts, found: List[Finding], remote: bool, note: str) -> str:
    # Settings and the node's spec may hold credentials written inline (an
    # ingest's options, a storage key in spark_config): the model gets ***.
    settings = redact_config(
        {k: v for k, v in facts.settings.items() if k in _SETTINGS_KEYS and v not in (None, {}, [])}
    )
    node = redact_config({k: v for k, v in facts.spec.items() if k not in ("description",)})
    facts_doc: Dict[str, Any] = {
        "pipeline": facts.pipeline,
        "node": facts.node,
        "environment": facts.env,
        "requires_dates": bool(facts.pipeline_settings.get("requires_dates")),
        "outputs written with": facts.write_modes,
        "read elsewhere by": facts.readers,
        "seconds per recent run (newest first)": facts.durations or "no successful run yet",
    }
    effective = {
        k: f"{redact_config({k: v})[k]} ({src})"
        for k, (v, src) in facts.effective.items()
        if v is not None
    }
    parts = [
        "# The node\n```json\n" + json.dumps(facts_doc, indent=2, default=str) + "\n```",
        "# Its configuration\n```yaml\n" + yaml.safe_dump(node, sort_keys=False).strip() + "\n```",
    ]
    if effective:
        parts.append(
            "# Effective settings (value and where it comes from)\n"
            + json.dumps(effective, indent=2, default=str)
        )
    if settings:
        parts.append(
            "# Project settings in this environment\n" + json.dumps(settings, indent=2, default=str)
        )
    code = facts.numbered_code(remote)
    if code:
        f = facts.function or {}
        parts.append(
            f"# The function it runs: {f.get('function')} in {f.get('file')}\n```python\n{code}\n```"
        )
    if found:
        parts.append(
            "# Ducta already found (do not repeat)\n"
            + "\n".join(
                f"- [{x.severity}] {x.title}" + (f" (line {x.line})" if x.line else "")
                for x in found
            )
        )
    if note.strip():
        parts.append("# What the user says\n" + note.strip())
    return "\n\n".join(parts)


def review_node(
    root: Path,
    pipeline: str,
    node: str,
    provider: Optional[LLMProvider],
    *,
    env: str = "dev",
    note: str = "",
) -> Review:
    """Ducta's findings, plus the model's when *provider* is given — each checked."""
    root = Path(root).resolve()
    facts = review_facts(root, pipeline, node, env)
    found = ducta_checks(facts)
    review = Review(
        pipeline=pipeline,
        node=node,
        env=env,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        findings=list(found),
    )
    if provider is None:
        return review
    message = _render(facts, found, remote=not provider.config.is_local, note=note)
    completion = provider.complete(
        REVIEW_PROMPT.format(max=MAX_AI_FINDINGS), [ChatMessage("user", message)]
    )
    review.model = completion.model or provider.config.model
    review.usage = dict(completion.usage)
    answer = parse_answer(completion.text)
    bodies = [b for lang, b in answer.unnamed if lang in ("yaml", "yml", "")] + list(
        answer.files.values()
    )
    try:
        data = yaml.safe_load(bodies[0]) if bodies else None
    except yaml.YAMLError:
        data = None
    raw = (data or {}).get("findings") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        review.notes = "The model's answer could not be read; only Ducta's findings are shown."
        return review
    asked = raw[: MAX_AI_FINDINGS * 2]
    checked = [f for f in (check_finding(r, facts) for r in asked) if f]
    review.dropped = len(asked) - len(checked)
    # What Ducta already said (same setting, or same line) is not said twice.
    said_keys = {f.key for f in found if f.key}
    said_lines = {f.line for f in found if f.line}
    kept = [f for f in checked if not (f.key in said_keys or (f.line in said_lines and not f.key))]
    order = {s: i for i, s in enumerate(SEVERITIES)}
    review.findings = sorted(
        found + kept[:MAX_AI_FINDINGS], key=lambda f: (order[f.severity], f.source != "ducta")
    )
    return review


# ── kept per node ───────────────────────────────────────────────────────────


def _path(root: Path, pipeline: str, node: str) -> Path:
    def safe(s: str) -> str:
        return "".join(c for c in s if c.isalnum() or c in "-_.")

    return Path(root) / ".ducta" / "ai" / "reviews" / f"{safe(pipeline)}__{safe(node)}.json"


def save_review(root: Path, review: Review) -> Path:
    from ducta.ai.fsutil import atomic_write_text

    path = _path(root, review.pipeline, review.node)
    return atomic_write_text(path, json.dumps(review.to_dict(), indent=2, ensure_ascii=False))


def load_review(root: Path, pipeline: str, node: str) -> Optional[Review]:
    try:
        return Review.from_dict(json.loads(_path(root, pipeline, node).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None
