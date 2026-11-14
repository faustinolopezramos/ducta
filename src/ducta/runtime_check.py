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

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib import metadata
from typing import Any, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class Stack:
    """The versions that decide whether Ducta's Spark path can work."""

    python: Tuple[int, int]
    pyspark: Optional[str] = None
    pandas: Optional[str] = None
    delta: Optional[str] = None
    java: Optional[int] = None


def _major(version: Optional[str]) -> int:
    head = (version or "").split(".")[0]
    return int(head) if head.isdigit() else 0


def problems(stack: Stack) -> List[str]:
    """What will go wrong with this stack, one sentence each with the fix."""
    found: List[str] = []
    py = "{}.{}".format(*stack.python)
    spark = _major(stack.pyspark)

    if stack.pyspark and spark < 4 and stack.python >= (3, 14):
        found.append(
            f"PySpark {stack.pyspark} does not run on Python {py}: its function serializer "
            "fails (RecursionError). Install PySpark 4.2 (pip install 'pyspark>=4.2,<4.3') "
            "or use Python 3.13."
        )
    java = stack.java
    if stack.pyspark and java is None:
        found.append(
            "PySpark is installed but no Java was found (JAVA_HOME or PATH): Spark cannot "
            "start. Install a JDK 17 or 21."
        )
    elif stack.pyspark and java is not None and spark >= 4 and java < 17:
        found.append(
            f"PySpark {stack.pyspark} needs Java 17 or 21, and the `java` found is "
            f"{java}: Spark will not start. Point JAVA_HOME at a JDK 17 or 21."
        )
    elif stack.pyspark and java is not None and spark == 3 and java >= 21:
        found.append(
            f"PySpark {stack.pyspark} on Java {java}: Arrow conversions (toPandas, "
            "pandas nodes, vectorized scoring) can fail. Use Java 17, or PySpark 4."
        )
    if stack.pyspark and _major(stack.pandas) >= 3:
        found.append(
            f"pandas {stack.pandas} with PySpark: a missing text value reaches Spark as the "
            "string 'NaN', with no error. Ducta supports pandas 2: pip install 'pandas<3'."
        )
    if stack.pyspark and stack.delta and _major(stack.delta) != spark:
        found.append(
            f"delta-spark {stack.delta} is for Spark {_major(stack.delta)}.x but PySpark is "
            f"{stack.pyspark}: pip install 'ducta[delta]' installs the matching pair."
        )
    return found


ANSI_KEY = "spark.sql.ansi.enabled"
TIMEZONE_KEY = "spark.sql.session.timeZone"


def spark_config_problems(
    pyspark: Optional[str], spark_config: Optional[Mapping[str, Any]], local_zone: str = ""
) -> List[str]:
    """Spark defaults that change results between versions or machines, left unset."""
    if not pyspark:
        return []
    keys = {str(k) for k in (spark_config or {})}
    found: List[str] = []
    if _major(pyspark) >= 4 and ANSI_KEY not in keys:
        found.append(
            f"PySpark {pyspark} runs SQL in ANSI mode: an invalid CAST, a division by zero "
            "or an overflow stops the run where Spark 3.5 returned NULL. Set "
            f"'{ANSI_KEY}' in settings.spark_config: true to keep it, false for the "
            "Spark 3.5 behaviour."
        )
    if TIMEZONE_KEY not in keys:
        zone = f" ({local_zone})" if local_zone else ""
        found.append(
            f"The Spark session uses this machine's time zone{zone}: dates, timestamps and "
            f"date partitions can differ on another machine. Set '{TIMEZONE_KEY}' "
            "(e.g. UTC) in settings.spark_config."
        )
    return found


def local_zone() -> str:
    """This machine's time zone abbreviation (``CST``…), or "" when unknown."""
    try:
        return datetime.now().astimezone().tzname() or ""
    except (OSError, ValueError):
        return ""


def config_warnings(spark_config: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    """:func:`spark_config_problems` for the installed PySpark and this machine."""
    return tuple(spark_config_problems(_version("pyspark"), spark_config, local_zone()))


def _version(distribution: str) -> Optional[str]:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _java_major() -> Optional[int]:
    """The major version of the ``java`` Spark starts (JAVA_HOME first, then PATH)."""
    home = os.environ.get("JAVA_HOME")
    candidate = os.path.join(home, "bin", "java") if home else None
    java = candidate if candidate and os.path.isfile(candidate) else shutil.which("java")
    if not java:
        return None
    try:
        done = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'version "([^"]+)"', done.stderr or done.stdout or "")
    if not match:
        return None
    parts = match.group(1).split(".")
    major = parts[1] if parts[0] == "1" and len(parts) > 1 else parts[0]
    return int(major) if major.isdigit() else None


def detect() -> Stack:
    """The installed stack. Java is only looked for when PySpark is installed."""
    pyspark = _version("pyspark")
    return Stack(
        python=(sys.version_info.major, sys.version_info.minor),
        pyspark=pyspark,
        pandas=_version("pandas"),
        delta=_version("delta-spark"),
        java=_java_major() if pyspark else None,
    )


@lru_cache(maxsize=1)
def stack_warnings() -> Tuple[str, ...]:
    """:func:`problems` for this environment, computed once per process."""
    return tuple(problems(detect()))
