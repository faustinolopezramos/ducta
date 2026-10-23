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

Why a run failed, in plain words.

Ducta's diagnosis (:mod:`ducta.api.services.diagnosis`) already knows the kind
of failure, the line of the project's code it was raised on, and what changed
since the last good run. The model only turns those facts — with the error and
the code around that line — into an explanation and next steps. It changes
nothing, and an explanation is kept per run so reading it again costs nothing.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ducta.ai.context import find_secrets, redact, redact_code, redact_config
from ducta.ai.providers import ChatMessage, LLMProvider

EXPLAIN_PROMPT = """\
You explain why a run of a Ducta data pipeline failed, to the person who has to \
fix it. Ducta already diagnosed the failure: trust those facts and build on them.

Answer in at most 140 words, in three short parts, each starting with its title \
in bold:
**What happened** — one or two sentences, no jargon.
**Why** — the most likely cause, and how sure you are. If the facts point to \
something that changed since the last good run, say so.
**What to do** — one to three concrete steps: a file and line, a command, a \
setting. Prefer the smallest fix.

Never invent file names, columns, settings or commands that the facts do not \
show. If the facts are not enough to know the cause, say what to check. Answer \
in the language of the user's note when there is one, otherwise in English.
"""

#: Lines of code shown on each side of the line the error was raised on.
_CODE_CONTEXT = 12
#: The most lines of a node's function sent when the error names no line.
_MAX_FUNCTION_LINES = 80
#: The tail of the error text sent, in characters.
_MAX_ERROR_CHARS = 6000


@dataclass
class Explanation:
    text: str
    model: str
    created_at: str
    usage: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _code_around(root: Path, frame: Optional[Dict[str, Any]], remote: bool) -> str:
    """The project's code around the line the error was raised on, numbered."""
    if not frame or not frame.get("file") or not frame.get("line"):
        return ""
    path = (root / str(frame["file"])).resolve()
    # The frame comes from the run's own error text: only a Python file of the project is read
    # (not ``.env`` or ``sources.yaml``, whatever the text names).
    if path.suffix != ".py" or not path.is_relative_to(root.resolve()) or not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    line = int(frame["line"])
    start, end = max(1, line - _CODE_CONTEXT), min(len(lines), line + _CODE_CONTEXT)
    shown = "\n".join(
        f"{n:>4}{'>' if n == line else ' '} {lines[n - 1]}" for n in range(start, end + 1)
    )
    # A remote model never sees a credential written in the code.
    return redact_code(shown) if remote and find_secrets(shown) else shown


def node_function(root: Path, node: str) -> Optional[Dict[str, Any]]:
    """Where the function a node runs is defined: file, first and last line.

    Used when the error has no traceback (a Spark error, a log line): Ducta
    still knows which node failed, so the model sees that node's real code
    instead of guessing a file name.
    """
    import yaml  # type: ignore[import-untyped]

    from ducta.api.services.code_index import module_file
    from ducta.setting.project_loader import PIPELINES_DIR, visible_in

    root = Path(root).resolve()
    folder = root / PIPELINES_DIR
    if not folder.is_dir():
        return None
    for path in sorted(folder.rglob("*.y*ml")):
        if not visible_in(path, folder):
            continue
        try:
            nodes = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("nodes") or {}
            spec = nodes.get(node)
        except (OSError, yaml.YAMLError, AttributeError):
            continue
        run = str((spec or {}).get("run") or "")
        if ":" not in run:
            continue
        module, function = run.split(":", 1)
        source = module_file(root, module)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return None
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == function:
                return {
                    "file": source.relative_to(root).as_posix(),
                    "line": item.lineno,
                    "end": item.end_lineno or item.lineno,
                    "function": function,
                    "pipeline": path.stem,
                }
        return None
    return None


def _function_code(root: Path, where: Dict[str, Any], remote: bool) -> str:
    try:
        lines = (Path(root) / where["file"]).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    start = where["line"]
    end = min(where["end"], start + _MAX_FUNCTION_LINES - 1, len(lines))
    shown = "\n".join(f"{n:>4}  {lines[n - 1]}" for n in range(start, end + 1))
    return redact_code(shown) if remote and find_secrets(shown) else shown


def explanation_message(
    root: Path, diagnosis: Dict[str, Any], error: str, note: str = "", remote: bool = True
) -> str:
    """What the model is told: the diagnosis, the error, the code, the user's note."""
    # The diagnosis quotes the error (its message, a hint): masked like the error itself.
    facts = redact_config(
        {
            k: diagnosis.get(k)
            for k in ("kind", "title", "message", "node", "frame", "what_changed", "suggestions")
            if diagnosis.get(k)
        }
    )
    parts = ["# Ducta's diagnosis\n```json\n" + json.dumps(facts, indent=2, default=str) + "\n```"]
    if diagnosis.get("hint"):
        parts.append(f"# Ducta's hint\n{redact(str(diagnosis['hint']))}")
    if error.strip():
        parts.append("# The error\n```\n" + redact(error.strip()[-_MAX_ERROR_CHARS:]) + "\n```")
    code = _code_around(root, diagnosis.get("frame"), remote)
    if code:
        frame = diagnosis["frame"]
        parts.append(
            f"# The code ({frame['file']}, the error line marked >)\n```python\n{code}\n```"
        )
    elif diagnosis.get("node"):
        where = node_function(root, str(diagnosis["node"]))
        body = _function_code(root, where, remote) if where else ""
        if where and body:
            parts.append(
                f"# The failing node's function: {where['function']} in {where['file']} "
                f"(lines {where['line']}–{where['end']}; the error gives no line)\n"
                f"```python\n{body}\n```"
            )
    if note.strip():
        parts.append("# What the user says\n" + note.strip())
    return "\n\n".join(parts)


def explain_failure(
    root: Path,
    diagnosis: Dict[str, Any],
    error: str,
    provider: LLMProvider,
    *,
    note: str = "",
) -> Explanation:
    """The model's explanation of a failed run, from Ducta's *diagnosis* of it."""
    message = explanation_message(
        Path(root), diagnosis, error, note, remote=not provider.config.is_local
    )
    completion = provider.complete(EXPLAIN_PROMPT, [ChatMessage("user", message)])
    return Explanation(
        text=completion.text.strip(),
        model=completion.model or provider.config.model or "",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        usage=dict(completion.usage),
    )


# ── kept per run ────────────────────────────────────────────────────────────


def _path(root: Path, run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    return Path(root) / ".ducta" / "ai" / "explanations" / f"{safe}.json"


def save_explanation(root: Path, run_id: str, explanation: Explanation) -> Path:
    from ducta.ai.fsutil import atomic_write_text

    path = _path(root, run_id)
    return atomic_write_text(path, json.dumps(explanation.to_dict(), indent=2))


def load_explanation(root: Path, run_id: str) -> Optional[Explanation]:
    path = _path(root, run_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Explanation(
            **{k: data[k] for k in ("text", "model", "created_at")}, usage=data.get("usage") or {}
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
