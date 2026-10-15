#!/usr/bin/env python3
"""Check the environment Ducta runs in, and print the result as JSON.

Part of the Ducta agent skill. Read-only: it runs ``java -version`` and asks
Ducta's own Python which packages it can import — it installs, writes and
changes nothing, and never prints an environment variable's value except the
paths in JAVA_HOME / SPARK_HOME. Standard library only, so any ``python3``
(3.8+) can run it, on any OS.

Usage:
    python3 scripts/check_env.py [--project PATH]

The Python running this script may not be the one Ducta is installed in (a
virtualenv, conda, pipx): the script finds the ``ducta`` command and asks the
interpreter behind it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: What each optional extra (``pip install 'ducta[<extra>]'``) makes importable.
EXTRAS: Dict[str, List[str]] = {
    "spark": ["pyspark", "pyarrow"],
    "api": ["fastapi", "uvicorn", "sqlalchemy"],
    "mlops": ["mlflow", "sklearn", "optuna"],
    "boost": ["xgboost", "lightgbm"],
    "ai": ["httpx", "anthropic", "keyring"],
    "delta": ["delta"],
    "databricks": ["databricks.connect"],
    "monitoring": ["prometheus_client"],
}

#: Run inside Ducta's interpreter: its version, and which modules it can find.
_PROBE = r"""
import importlib.util, json, sys
out = {"python": sys.version.split()[0], "executable": sys.executable}
try:
    from importlib.metadata import version
    out["ducta"] = version("ducta")
except Exception:
    out["ducta"] = None
mods = {}
for name in sys.argv[1:]:
    try:
        mods[name] = importlib.util.find_spec(name) is not None
    except Exception:
        mods[name] = False
out["modules"] = mods
try:
    out["pyspark"] = version("pyspark")
except Exception:
    out["pyspark"] = None
print(json.dumps(out))
"""


def _run(cmd: List[str], timeout: int = 30) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


#: pip's launcher when the interpreter's path has spaces or is too long for a
#: shebang: ``#!/bin/sh`` and then ``'''exec' "/path/to/python" "$0" "$@"``.
_SH_TRAMPOLINE = re.compile(r"""^'''exec'\s+(?:"([^"]+)"|(\S+))""", re.MULTILINE)


def _is_python(path: Optional[str]) -> bool:
    return bool(path) and Path(str(path)).name.lower().startswith(("python", "pypy"))


def _ducta_python(ducta: Optional[str]) -> Optional[str]:
    """The interpreter behind the ``ducta`` command, from its shebang (POSIX).

    Only a Python is returned: the probe is Python code, and handed to another
    program (``/bin/sh``) it would run as that program's commands.
    """
    if not ducta:
        return None
    path = Path(ducta)
    # Windows: Scripts\ducta.exe sits next to python.exe in the environment.
    for candidate in (path.parent / "python.exe", path.parent.parent / "python.exe"):
        if candidate.is_file():
            return str(candidate)
    try:
        head = path.read_bytes()[:1024].decode("utf-8", "replace")
    except OSError:
        return None
    first = head.split("\n", 1)[0]
    if not first.startswith("#!"):
        return None
    parts = first[2:].strip().split()
    found: Optional[str] = None
    if parts and Path(parts[0]).name == "env":
        program = next((p for p in parts[1:] if not p.startswith("-")), None)
        found = shutil.which(program) if program else None
    elif parts and _is_python(parts[0]):
        found = parts[0]
    elif parts and Path(parts[0]).name in ("sh", "bash"):
        m = _SH_TRAMPOLINE.search(head)
        found = (m.group(1) or m.group(2)) if m else None
    return found if _is_python(found) else None


def _skill_ducta_version() -> Optional[str]:
    """``metadata.ducta-version`` from this skill's SKILL.md."""
    skill = Path(__file__).resolve().parent.parent / "SKILL.md"
    try:
        text = skill.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^\s*ducta-version:\s*[\"']?([\w.]+)", text, re.MULTILINE)
    return m.group(1) if m else None


def _java() -> Dict[str, Any]:
    java = shutil.which("java")
    info: Dict[str, Any] = {
        "found": bool(java),
        "path": java,
        "java_home": os.environ.get("JAVA_HOME"),
        "version": None,
        "major": None,
    }
    if java:
        done = _run([java, "-version"])
        text = (done.stderr or done.stdout) if done else ""
        m = re.search(r'version "([^"]+)"', text)
        if m:
            info["version"] = m.group(1)
            first = m.group(1).split(".")
            major = first[1] if first[0] == "1" and len(first) > 1 else first[0]
            info["major"] = int(major) if major.isdigit() else None
    return info


def _project(start: Path) -> Optional[str]:
    for folder in (start, *start.parents):
        if (folder / "ducta.yaml").is_file():
            return str(folder)
    return None


def check(project: Path) -> Dict[str, Any]:
    warnings: List[str] = []
    ducta_cmd = shutil.which("ducta")
    interpreter = _ducta_python(ducta_cmd) or sys.executable
    modules = sorted({m for mods in EXTRAS.values() for m in mods})
    probe: Dict[str, Any] = {}
    done = _run([interpreter, "-c", _PROBE, *modules], timeout=60)
    if done and done.returncode == 0:
        try:
            probe = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            probe = {}

    ducta_version = probe.get("ducta")
    expected = _skill_ducta_version()
    if not ducta_cmd:
        warnings.append(
            "The `ducta` command is not on PATH: install it (pip install ducta) or activate "
            "the environment it is installed in."
        )
    elif not ducta_version:
        warnings.append(f"`ducta` is on PATH but its Python ({interpreter}) cannot find it.")
    if ducta_version and expected and not ducta_version.startswith(expected):
        warnings.append(
            f"Ducta {ducta_version} is installed but this skill describes {expected}.x: "
            "trust `ducta <command> --help` and `ducta config schema` over the references."
        )

    found = probe.get("modules") or {}
    extras = {extra: all(found.get(m) for m in mods) for extra, mods in EXTRAS.items()}

    py = probe.get("python") or platform.python_version()
    if tuple(int(x) for x in re.findall(r"\d+", py)[:2]) < (3, 10):
        warnings.append(f"Ducta needs Python 3.10 or newer; its interpreter is {py}.")

    java = _java()
    if extras.get("spark"):
        if not java["found"]:
            warnings.append("PySpark is installed but no `java` is on PATH: Spark needs a JDK.")
        pyspark = probe.get("pyspark") or ""
        if pyspark.startswith("3.5") and (java["major"] or 0) >= 21:
            warnings.append(
                f"PySpark {pyspark} with Java {java['major']}: Arrow cannot run on JDK 21+. "
                "Set spark.sql.execution.arrow.pyspark.enabled: 'false' in settings.spark_config, "
                "or use JDK 17."
            )

    return {
        "os": f"{platform.system()} {platform.release()}",
        "python": {"version": py, "executable": probe.get("executable") or interpreter},
        "ducta": {
            "command": ducta_cmd,
            "version": ducta_version,
            "skill_expects": expected,
        },
        "extras": extras,
        "java": java,
        "spark_home": os.environ.get("SPARK_HOME"),
        "pyspark": probe.get("pyspark"),
        "project_root": _project(project.resolve()),
        "warnings": warnings,
        "ok": not warnings,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default=".", help="Where to look for ducta.yaml")
    args = parser.parse_args(argv)
    print(json.dumps(check(Path(args.project)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
