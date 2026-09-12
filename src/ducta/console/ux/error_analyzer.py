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
"""

import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.text import Text

ERROR_PATTERNS = {
    "UNRESOLVED_COLUMN": {
        "pattern": r"\[UNRESOLVED_COLUMN\.WITH_SUGGESTION\] A column.*?`([^`]+)`.*?Did you mean.*?\[([^\]]+)\]",
        "type": "Column Not Found",
        "emoji": "🔍",
        "color": "bright_yellow",
    },
    "COLUMN_NOT_FOUND_ALT": {
        "pattern": r"cannot resolve '([^']+)'.*?given input columns: \[([^\]]+)\]",
        "type": "Column Not Found",
        "emoji": "❌",
        "color": "bright_red",
    },
    "TYPE_MISMATCH": {
        "pattern": r"cannot resolve.*?due to data type mismatch|incompatible.*?type",
        "type": "Type Mismatch",
        "emoji": "⚠️",
        "color": "bright_yellow",
    },
    "PARSE_EXCEPTION": {
        "pattern": r"ParseException",
        "type": "SQL Parse Error",
        "emoji": "📝",
        "color": "bright_red",
    },
    "FILE_NOT_FOUND": {
        "pattern": r"FileNotFoundError|Path does not exist|No such file or directory",
        "type": "File Not Found",
        "emoji": "📁",
        "color": "bright_red",
    },
    "KEY_ERROR": {
        "pattern": r"KeyError:\s*['\"]([^'\"]+)['\"]",
        "type": "Key Error",
        "emoji": "🔑",
        "color": "bright_yellow",
    },
    "ATTRIBUTE_ERROR": {
        "pattern": r"AttributeError.*?'([^']+)'.*?has no attribute\s*'([^']+)'",
        "type": "Attribute Error",
        "emoji": "🔧",
        "color": "bright_yellow",
    },
    "VALUE_ERROR": {
        "pattern": r"ValueError",
        "type": "Value Error",
        "emoji": "💢",
        "color": "bright_yellow",
    },
    "INDEX_ERROR": {
        "pattern": r"IndexError",
        "type": "Index Error",
        "emoji": "📍",
        "color": "bright_yellow",
    },
    "TYPE_ERROR": {
        "pattern": r"TypeError",
        "type": "Type Error",
        "emoji": "🔤",
        "color": "bright_yellow",
    },
    "IMPORT_ERROR": {
        "pattern": r"ImportError|ModuleNotFoundError|No module named",
        "type": "Import Error",
        "emoji": "📦",
        "color": "bright_red",
    },
    "MEMORY_ERROR": {
        "pattern": r"OutOfMemoryError|MemoryError",
        "type": "Memory Error",
        "emoji": "💾",
        "color": "bright_red",
    },
    "NULL_POINTER": {
        "pattern": r"NullPointerException|'NoneType' object",
        "type": "Null Reference Error",
        "emoji": "⭕",
        "color": "bright_yellow",
    },
    "DIVISION_BY_ZERO": {
        "pattern": r"ZeroDivisionError|division by zero",
        "type": "Division by Zero",
        "emoji": "➗",
        "color": "bright_red",
    },
    "SCHEMA_MISMATCH": {
        "pattern": r"Schema mismatch|expected.*?but got",
        "type": "Schema Mismatch",
        "emoji": "📋",
        "color": "bright_yellow",
    },
    "TIMEOUT": {
        "pattern": r"TimeoutError|timeout|timed out",
        "type": "Timeout Error",
        "emoji": "⏱️",
        "color": "bright_red",
    },
    "CONNECTION_ERROR": {
        "pattern": r"ConnectionError|Connection refused|unable to connect",
        "type": "Connection Error",
        "emoji": "🔌",
        "color": "bright_red",
    },
}


def _hint_import_error(m: re.Match) -> dict:
    name_match = re.search(r"No module named ['\"]([^'\"]+)['\"]", m.string)
    mod = name_match.group(1) if name_match else "unknown"
    return {
        "context": {"module": mod},
        "message": f"Cannot import module '{mod}'",
        "suggestions": [f"pip install {mod}"],
    }


ERROR_HINTS: Dict[str, Any] = {
    "UNRESOLVED_COLUMN": lambda m: {
        "context": {
            "wrong_column": m.group(1),
            "available_columns": m.group(2).replace("`", "").split(", "),
        },
        "message": f"Column '{m.group(1)}' does not exist",
    },
    "COLUMN_NOT_FOUND_ALT": lambda m: {
        "context": {"wrong_column": m.group(1), "available_columns": m.group(2).split(", ")},
        "message": f"Cannot resolve column '{m.group(1)}'",
    },
    "KEY_ERROR": lambda m: {
        "context": {"missing_key": m.group(1)},
        "message": f"Key '{m.group(1)}' does not exist",
    },
    "ATTRIBUTE_ERROR": lambda m: {
        "context": {"object_type": m.group(1), "attribute": m.group(2)},
        "message": f"Object '{m.group(1)}' has no attribute '{m.group(2)}'",
    },
    "IMPORT_ERROR": _hint_import_error,
    "FILE_NOT_FOUND": lambda m: {"message": "File or directory not found"},
    "MEMORY_ERROR": lambda m: {
        "message": "Insufficient memory",
        "suggestions": ["Reduce dataset size", "Increase memory", "Process in batches"],
    },
    "TIMEOUT": lambda m: {
        "message": "Operation exceeded time limit",
        "suggestions": ["Increase timeout", "Optimize query", "Check network"],
    },
    "NULL_POINTER": lambda m: {"message": "Attempt to access None/null object"},
    "DIVISION_BY_ZERO": lambda m: {"message": "Division by zero detected"},
}


def _extract_json_stacktrace(error_msg: str) -> Optional[List[Dict[str, str]]]:
    if '"stacktrace"' not in error_msg:
        return None
    match = re.search(r'"stacktrace":\s*\[([^\]]+)\]', error_msg)
    if not match:
        return None
    frames = []
    for file_path, line_num in re.findall(
        r'"file":\s*"([^"]+)".*?"line":\s*"?(\d+)"?', match.group(1)
    ):
        if file_path and not file_path.startswith("java.base") and ".py" in file_path:
            frames.append({"file": file_path, "line": line_num})
    return frames if frames else None


def _extract_plaintext_traceback(error_msg: str) -> Optional[List[Dict[str, str]]]:
    frames = []
    for file_path, line_num in re.findall(r'File\s+"([^"]+\.py)",\s+line\s+(\d+)', error_msg):
        if not any(exclude in file_path for exclude in ["site-packages", "lib/python"]):
            frames.append({"file": file_path, "line": line_num})
    return frames if frames else None


def extract_python_traceback(error_msg: str) -> Optional[List[Dict[str, str]]]:
    frames = _extract_json_stacktrace(error_msg)
    if not frames:
        frames = _extract_plaintext_traceback(error_msg)
    return frames


def extract_error_message(error_msg: str) -> str:
    json_match = re.search(r'"msg":\s*"([^"]+)"', error_msg)
    if json_match:
        return json_match.group(1)
    exception_match = re.search(r"(?:Exception|Error):\s*(.+?)(?:\n|\\n)", error_msg)
    if exception_match:
        return re.sub(r"\\[rn]", " ", exception_match.group(1).strip())
    lines = error_msg.split("\n")
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) > 20 and not line.startswith("{"):
            return line
    return error_msg[:200] + "..." if len(error_msg) > 200 else error_msg


def _classify_quality_outcome(
    exception: Optional[Exception], error_msg: str
) -> Optional[Dict[str, Any]]:
    """Classify a quality verdict, which is a decision rather than a defect.

    A blocked quality gate is the system doing its job: the data did not meet
    the rules the node declared, so the node was stopped. Falling through to the
    regex table below rendered it as "❌ Unknown Error", which tells the reader
    something broke and gives them nothing to act on — when in fact the gate has
    the exact rules it tripped on.

    ``classify_error`` has always accepted the exception object and never looked
    at it; this is what it was for.
    """
    if exception is None:
        return None
    try:
        from ducta.check.core import QualityChecksFailed, QualityGateBlocked
    except Exception:  # noqa: BLE001 — the analyzer must never break on an import
        return None

    if isinstance(exception, QualityGateBlocked):
        gate_result = getattr(exception, "gate_result", None)
        rules = list(getattr(gate_result, "triggered_rules", None) or [])
        return {
            "error_type": "Quality Gate Blocked",
            "emoji": "🚦",
            "color": "bright_yellow",
            "severity": "medium",
            "suggestions": rules or ["Check the node's data_quality.quality_gate thresholds."],
            "context": {"gate": getattr(gate_result, "gate_name", None)},
        }

    if isinstance(exception, QualityChecksFailed):
        results = getattr(exception, "results", None) or []
        failed = [getattr(r, "check_name", "?") for r in results if not getattr(r, "passed", True)]
        return {
            "error_type": "Quality Checks Failed",
            "emoji": "🚦",
            "color": "bright_yellow",
            "severity": "medium",
            "suggestions": [f"Failed check(s): {', '.join(failed)}"] if failed else [],
        }
    return None


def classify_error(error_msg: str, exception: Optional[Exception] = None) -> Dict[str, Any]:
    result = {
        "error_type": "Unknown Error",
        "emoji": "❌",
        "color": "bright_red",
        "message": extract_error_message(error_msg),
        "suggestions": [],
        "python_location": None,
        "all_frames": [],
        "severity": "high",
        "context": {},
        "raw_error": error_msg,
    }

    # Checked before the regex table: these are verdicts about the data, and the
    # exception type says so exactly, where matching on message text would only
    # guess.
    quality = _classify_quality_outcome(exception, error_msg)
    if quality is not None:
        result.update(quality)
        return result

    for key, config in ERROR_PATTERNS.items():
        match = re.search(config["pattern"], error_msg, re.IGNORECASE | re.DOTALL)
        if match:
            result["error_type"] = config["type"]
            result["emoji"] = config["emoji"]
            result["color"] = config["color"]
            hint = ERROR_HINTS.get(key)
            if hint:
                extra = hint(match)
                if isinstance(extra, dict):
                    result.update({k: v for k, v in extra.items() if v is not None})
            break
    frames = extract_python_traceback(error_msg)
    if frames:
        result["python_location"] = frames[-1]
        result["all_frames"] = frames
    if exception:
        exc_name = type(exception).__name__
        result["exception_type"] = exc_name
        Ducta_types = {
            "ConfigurationError": ("Configuration Error", "⚙️", "bright_yellow", "high"),
            "ValidationError": ("Validation Error", "📋", "bright_yellow", "medium"),
            "SecurityError": ("Security Violation", "🛡️", "bright_red", "critical"),
            "ExecutionError": ("Execution Error", "🚀", "bright_red", "high"),
        }
        if exc_name in Ducta_types:
            etype, emoji, color, severity = Ducta_types[exc_name]
            result.update(error_type=etype, emoji=emoji, color=color, severity=severity)
        if hasattr(exception, "__traceback__"):
            result["full_traceback"] = "".join(traceback.format_tb(exception.__traceback__))
    return result


def _shorten_path(file_path: str, max_len: int = 60) -> str:
    p = Path(file_path)
    if len(str(p)) <= max_len:
        return str(p)
    parts = p.parts
    for i in range(3, 0, -1):
        if i < len(parts):
            shortened = str(Path("...") / Path(*parts[-i:]))
            if len(shortened) <= max_len:
                return shortened
    return parts[-1] if parts else file_path


def _render_context(console: Console, context: Dict[str, Any]) -> None:
    if not context:
        return
    if "wrong_column" in context:
        wrong = context["wrong_column"]
        available = context.get("available_columns", [])
        similar = [
            c for c in available if c.lower().replace("_", "") in wrong.lower().replace("_", "")
        ]
        avail_display = "\n".join(
            f"  ✓ {c}" if c in similar else f"    {c}" for c in available[:10]
        )
        if len(available) > 10:
            avail_display += f"\n    ... and {len(available) - 10} more"
        text = Text.assemble(
            ("  ❌ You used: ", "bold bright_red"),
            (wrong, "bold bright_red"),
            ("\n  ✓ Available columns:\n", "bold bright_green"),
            (avail_display, ""),
        )
        console.print(text)
    elif "missing_key" in context:
        console.print(
            Text.assemble(
                ("  🔑 Missing key: ", "bold bright_yellow"),
                (context["missing_key"], "bold bright_red"),
            )
        )
    elif "object_type" in context and "attribute" in context:
        console.print(
            Text.assemble(
                ("  Type: ", "dim"),
                (context["object_type"], "bright_cyan"),
                ("\n  Missing attribute: ", "dim"),
                (context["attribute"], "bold bright_red"),
            )
        )
    elif "module" in context:
        console.print(
            Text.assemble(
                ("  📦 Module: ", "bold bright_yellow"),
                (context["module"], "bold bright_red"),
            )
        )


def print_error_report(
    analysis: Dict[str, Any], node_name: str, console: Optional[Console] = None
) -> None:
    if console is None:
        console = Console()
    etype = analysis["error_type"]
    color = analysis["color"]
    message = analysis["message"]
    suggestions = analysis.get("suggestions", [])
    location = analysis.get("python_location")
    frames = analysis.get("all_frames", [])
    context = analysis.get("context", {})
    severity = analysis.get("severity", "high")

    sev_emoji = {"critical": "🚨", "high": "❌", "medium": "⚠️", "low": "ℹ️"}
    console.print()
    console.print(
        f"{sev_emoji.get(severity, '❌')} {etype} in node '{node_name}'", style=f"bold {color}"
    )
    console.print(f"  ERROR: {message}", style="bold bright_white")
    if location:
        console.print(
            Text.assemble(
                ("  📍 ", "bold bright_cyan"),
                (f"{_shorten_path(location['file'])}", "bright_white"),
                (" at line ", "dim"),
                (location["line"], "bright_yellow"),
            )
        )
    if len(frames) > 1:
        stack = Text.assemble(("  📚 Call stack:\n", "bold bright_cyan"))
        for i, f in enumerate(frames[-3:], 1):
            stack.append(f"    {i}. {_shorten_path(f['file'], 50)}:{f['line']}\n", "bright_white")
        console.print(stack)

    _render_context(console, context)

    if suggestions:
        console.print("  💡 Suggestions:", style="bold bright_cyan")
        for i, s in enumerate(suggestions[:5], 1):
            console.print(f"    {i}. {s}", style="bright_green")
    console.print()


class SparkErrorAnalyzer:
    analyze_error = staticmethod(classify_error)
    print_error_report = staticmethod(print_error_report)
    extract_python_traceback = staticmethod(extract_python_traceback)
    extract_error_message = staticmethod(extract_error_message)


def format_error_for_developer(
    error: Exception,
    node_name: str,
    console: Optional[Console] = None,
) -> None:
    analysis = classify_error(str(error), error)
    print_error_report(analysis, node_name, console)


def try_format_error(error: Exception, label: str) -> bool:
    """Attempt to render *error* via :func:`format_error_for_developer` on the
    active Rich console. Returns whether it succeeded, so callers can fall
    back to their own logging without duplicating the try/except/import
    boilerplate."""
    try:
        from ducta.console.ux.rich_logger import RichLoggerManager

        format_error_for_developer(error, label, RichLoggerManager.get_console())
        return True
    except Exception:
        return False
