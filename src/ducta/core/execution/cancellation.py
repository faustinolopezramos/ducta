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

Cancelling a node that ran out of time — for real.

A Python thread cannot be killed, so a timed-out node used to keep running,
and keep writing, after the run had been marked failed. Cancellation now works
at the two places where a node's work actually happens:

* **Spark.** Every job a node submits carries a tag unique to the node *and*
  the run (``ducta-<run>-<node>``). Cancelling the node cancels those jobs on
  the cluster, which also unblocks the node's thread — it gets an exception
  from the action it was waiting on.
* **Writes.** Every dataset write first checks whether its node was cancelled
  and refuses with :class:`NodeCancelledError`, so pure-Python work that
  outlives its timeout still cannot land output.

What neither can stop is a long pure-Python computation that never touches
Spark or a writer; ``run_in_process: true`` runs such a node in its own
process, which *can* be terminated.
"""

from __future__ import annotations

import threading
from typing import Any, Optional, Set

from loguru import logger

from ducta.core.errors import NodeCancelledError
from ducta.core.execution_context import node_id_var

_ATTR = "_ducta_cancellation"


class _Registry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cancelled: Set[str] = set()


def _registry(context: Any) -> _Registry:
    reg = getattr(context, _ATTR, None)
    if reg is None:
        reg = _Registry()
        try:
            setattr(context, _ATTR, reg)
        except (AttributeError, TypeError):
            pass
    return reg


def job_tag(context: Any, node: str) -> str:
    """Tag for a node's Spark jobs. Includes the run's identity: in the API
    server several runs share one SparkContext, and cancelling node ``load`` of
    one run must not cancel ``load`` of another."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in node)
    return f"ducta-{id(context):x}-{safe}"


def _spark(context: Any) -> Optional[Any]:
    try:
        return getattr(context, "spark", None)
    except Exception:  # noqa: BLE001 — no Spark is a normal state for pandas nodes
        return None


def tag_current_thread(context: Any, node: str) -> None:
    """Label the Spark jobs this thread submits as belonging to ``node``.

    Job tags are thread-local (PySpark pins Python threads to JVM threads), and
    pool threads are reused across nodes, so any tag left by the previous node
    is cleared first.
    """
    spark = _spark(context)
    if spark is None:
        return
    tag = job_tag(context, node)
    try:
        sc = spark.sparkContext
        sc.clearJobTags()
        sc.addJobTag(tag)
    except Exception:  # noqa: BLE001 — Spark Connect has no SparkContext
        try:
            spark.clearTags()
            spark.addTag(tag)
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not tag Spark jobs for node '{}': {}", node, e)


def untag_current_thread(context: Any) -> None:
    spark = _spark(context)
    if spark is None:
        return
    try:
        spark.sparkContext.clearJobTags()
    except Exception:  # noqa: BLE001
        try:
            spark.clearTags()
        except Exception:  # noqa: BLE001
            pass


def cancel_node(context: Any, node: str) -> None:
    """Refuse the node's further writes and cancel its running Spark jobs."""
    reg = _registry(context)
    with reg.lock:
        reg.cancelled.add(node)
    spark = _spark(context)
    if spark is None:
        return
    tag = job_tag(context, node)
    try:
        spark.sparkContext.cancelJobsWithTag(tag)
        logger.warning("Cancelled Spark jobs of timed-out node '{}'", node)
    except Exception:  # noqa: BLE001
        try:
            spark.interruptTag(tag)
            logger.warning("Interrupted Spark operations of timed-out node '{}'", node)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not cancel Spark jobs of node '{}': {}", node, e)


def is_cancelled(context: Any, node: str) -> bool:
    reg = getattr(context, _ATTR, None)
    if reg is None:
        return False
    with reg.lock:
        return node in reg.cancelled


def ensure_not_cancelled(context: Any, node: Optional[str] = None) -> None:
    """Raise :class:`NodeCancelledError` if the calling node was cancelled.

    Called before every dataset write. ``node`` defaults to the node the
    current thread is executing.
    """
    node = node or node_id_var.get()
    if node and is_cancelled(context, node):
        raise NodeCancelledError(node)
