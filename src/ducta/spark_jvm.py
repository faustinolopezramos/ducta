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

from typing import Any, Optional


def spark_major(spark_or_version: Any) -> int:
    """The Spark major version of a session (or a version string); 0 when unknown."""
    version = (
        spark_or_version
        if isinstance(spark_or_version, str)
        else getattr(spark_or_version, "version", "")
    )
    head = str(version).strip().split(".")[0]
    return int(head) if head.isdigit() else 0


def scala_suffix(spark_or_version: Any) -> str:
    """The Scala build of Spark's own Maven packages: 2.13 from Spark 4, 2.12 before."""
    return "2.13" if spark_major(spark_or_version) >= 4 else "2.12"


def jvm(spark: Any) -> Optional[Any]:
    """The py4j gateway to the driver's JVM, for a SparkSession or a SparkContext."""
    try:
        handle = getattr(spark, "_jvm", None)
        if handle is None and hasattr(spark, "sparkContext"):
            handle = getattr(spark.sparkContext, "_jvm", None)
        return handle
    except Exception:  # noqa: BLE001 — Spark Connect raises on sparkContext
        return None


def jvm_has_class(spark: Any, class_name: str) -> bool:
    """Whether a Java class (``com.databricks.spark.xml.DefaultSource``) can be loaded.

    A class, not a package: py4j answers *any* dotted name with a ``JavaPackage``, so
    walking ``_jvm.com.databricks.spark.xml`` is truthy whether spark-xml is there or
    not. The context class loader is the one ``spark.jars.packages`` adds to.
    """
    handle = jvm(spark)
    if handle is None:
        return False
    try:
        loader = handle.java.lang.Thread.currentThread().getContextClassLoader()
        handle.java.lang.Class.forName(class_name, False, loader)
        return True
    except Exception:  # noqa: BLE001 — py4j raises Py4JJavaError (ClassNotFoundException)
        return False


def hadoop_configuration(spark: Any) -> Optional[Any]:
    """The session's Hadoop ``Configuration`` (to open any Hadoop filesystem)."""
    try:
        return spark.sparkContext._jsc.hadoopConfiguration()
    except Exception:  # noqa: BLE001 — no JVM (Spark Connect)
        return None


def java_version(spark: Any) -> Optional[str]:
    """``java.specification.version`` of the JVM the session runs on (``"17"``, ``"1.8"``)."""
    handle = jvm(spark)
    if handle is None:
        return None
    try:
        return str(handle.java.lang.System.getProperty("java.specification.version"))
    except Exception:  # noqa: BLE001
        return None


def schema_tree(df: Any) -> str:
    """``printSchema()``'s text, without printing it; ``""`` when it cannot be had."""
    tree = getattr(getattr(df, "schema", None), "treeString", None)
    if callable(tree):  # public from Spark 4
        try:
            return str(tree())
        except Exception:  # noqa: BLE001
            pass
    try:
        return str(df._jdf.schema().treeString())
    except Exception:  # noqa: BLE001
        return ""
