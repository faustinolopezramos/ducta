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

The evidence one run accumulates, as an object instead of a naming convention.

The executor, the quality phases, the IO gate and the certificate builder all
communicate through five underscore-prefixed attributes stashed on the shared
``Context`` with ``setattr`` and read back with ``getattr``:

    _run_id  _run_node_details  _quality_results
    _input_fingerprints  _output_fingerprints  (_previous_input_fingerprints)

Nothing declares that protocol, nothing type-checks it, and a typo in any of the
six spellings degrades silently to "no evidence recorded" — which for a run
certificate means a certificate that is quietly missing the very thing it exists
to attest. Appends also came from parallel worker threads, each call site
re-implementing (or forgetting) its own locking.

:class:`RunLedger` names the contract and gives it one thread-safe
implementation. It is a *view over the same context attributes*, not a
replacement for them: ``ducta.gate`` writes fingerprints and the API reads
``_run_id`` directly, so both spellings must stay consistent while those layers
migrate. Core code should use the ledger; the attributes remain the wire format.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from loguru import logger  # type: ignore

#: The context attributes that make up the ledger's wire format.
RUN_ID_ATTR = "_run_id"
NODE_DETAILS_ATTR = "_run_node_details"
QUALITY_RESULTS_ATTR = "_quality_results"
INPUT_FINGERPRINTS_ATTR = "_input_fingerprints"
OUTPUT_FINGERPRINTS_ATTR = "_output_fingerprints"
PREVIOUS_INPUT_FINGERPRINTS_ATTR = "_previous_input_fingerprints"


class RunLedger:
    """Thread-safe record of what one pipeline run produced.

    Writes are safe from the worker threads the DAG coordinator runs nodes on.
    Every method is best-effort — bookkeeping must never be the reason a
    pipeline fails — but a swallowed failure is still *counted*: it logs at
    WARNING and flips :attr:`evidence_complete`, which the run certificate
    carries. Silently dropping a node outcome and then sealing a certificate
    that looks complete is the one failure this class exists to prevent.
    """

    def __init__(self, context: Any, run_id: Optional[str] = None) -> None:
        self._context = context
        # Reentrant on purpose. `_append` runs under this lock and its failure
        # path reaches `_note_failure`, which takes it again; the paths happen
        # not to overlap today only because the `except` sits outside the
        # `with`. That is a one-line refactor away from a deadlock on the
        # failure path — the path this bookkeeping exists to survive, and the
        # one least likely to be exercised before it ships.
        self._lock = threading.RLock()
        self._record_failures: List[str] = []
        if run_id is not None:
            self.run_id = run_id

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @classmethod
    def start(cls, context: Any, run_id: str) -> "RunLedger":
        """Begin a run: stamp the id and clear the previous run's evidence.

        Resetting matters because a single executor instance drives several
        pipelines in a chain; without it, one pipeline's node trace would leak
        into the next one's certificate.

        Goes through :func:`ledger_for` so the caller gets *the* ledger for this
        context, not a second one. Constructing directly here meant the facade
        held one instance while every component below it (`ledger_for`) held
        another, each with its own lock — so the thread-safety this class
        advertises was guarding two different doors to the same room.
        """
        ledger = ledger_for(context)
        ledger.reset()
        ledger.run_id = run_id
        return ledger

    def reset(self) -> None:
        """Clear every per-run collection, fingerprints included.

        Fingerprints are *written* by ``ducta.gate`` as inputs are read and
        outputs are written, but they describe one run, so they are cleared
        here like everything else. They used to survive a reset on the grounds
        that the IO layer owned them — which held for a single pipeline and
        broke for a chain: one executor drives every pipeline in it and
        ``ducta.gate`` accumulates into the same context dicts, so pipeline
        N+1's certificate claimed N's inputs and outputs as its own. That is
        the one thing a run certificate exists to say, and ``certify verify``
        passed on the wrong answer because the hash covers it just as happily.
        ``certify verify --reproduce`` then flagged outputs the reproduction
        never wrote as "diverged".

        ``_previous_input_fingerprints`` is deliberately left alone: it belongs
        to the *previous* successful run, is loaded by
        ``core.mlops_integration`` and read by ``gate.input``'s
        ``fingerprint_policy``, so clearing it here would disable that policy.
        """
        with self._lock:
            # One executor drives several pipelines in a chain, so a failure
            # recorded for pipeline N must not mark pipeline N+1's certificate
            # incomplete.
            self._record_failures.clear()
        self._set(NODE_DETAILS_ATTR, [])
        self._set(QUALITY_RESULTS_ATTR, [])
        self._set(INPUT_FINGERPRINTS_ATTR, {})
        self._set(OUTPUT_FINGERPRINTS_ATTR, {})

    # ── Run identity ─────────────────────────────────────────────────────────

    @property
    def run_id(self) -> Optional[str]:
        return self._get(RUN_ID_ATTR, None)

    @run_id.setter
    def run_id(self, value: str) -> None:
        self._set(RUN_ID_ATTR, value)

    # ── Node trace ───────────────────────────────────────────────────────────

    def record_node(
        self,
        name: str,
        status: str,
        duration_seconds: float = 0.0,
        outputs: Optional[List[str]] = None,
        error: Optional[str] = None,
        node_type: str = "batch",
    ) -> None:
        """Append one node's outcome. Safe to call from worker threads."""
        record = {
            "name": name,
            "type": node_type,
            "status": status,
            "duration_seconds": round(float(duration_seconds), 3),
            "outputs": list(outputs or []),
            "error": error,
        }
        self._append(NODE_DETAILS_ATTR, record, what=f"node trace for '{name}'")

    @property
    def node_details(self) -> List[Dict[str, Any]]:
        """The recorded node outcomes, as a snapshot copy."""
        with self._lock:
            return list(self._get(NODE_DETAILS_ATTR, []) or [])

    # ── Quality ──────────────────────────────────────────────────────────────

    def record_quality(self, entry: Dict[str, Any]) -> None:
        """Append one quality summary (a node+phase outcome)."""
        node = entry.get("node", "?")
        self._append(QUALITY_RESULTS_ATTR, entry, what=f"quality summary for '{node}'")

    @property
    def quality_results(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._get(QUALITY_RESULTS_ATTR, []) or [])

    # ── Fingerprints (written by ducta.gate as IO happens) ───────────────────

    @property
    def input_fingerprints(self) -> Dict[str, Any]:
        return dict(self._get(INPUT_FINGERPRINTS_ATTR, {}) or {})

    @property
    def output_fingerprints(self) -> Dict[str, Any]:
        return dict(self._get(OUTPUT_FINGERPRINTS_ATTR, {}) or {})

    @property
    def previous_input_fingerprints(self) -> Dict[str, Any]:
        """Fingerprints from the last successful run, when the policy loads them."""
        return dict(self._get(PREVIOUS_INPUT_FINGERPRINTS_ATTR, {}) or {})

    @previous_input_fingerprints.setter
    def previous_input_fingerprints(self, value: Dict[str, Any]) -> None:
        self._set(PREVIOUS_INPUT_FINGERPRINTS_ATTR, value)

    # ── Context access (dict- or attribute-shaped) ───────────────────────────

    def _get(self, attr: str, default: Any) -> Any:
        if isinstance(self._context, dict):
            return self._context.get(attr, default)
        return getattr(self._context, attr, default)

    # ── Evidence completeness ────────────────────────────────────────────────

    @property
    def evidence_complete(self) -> bool:
        """False once any write to this ledger has failed.

        Recording stays best-effort — bookkeeping must never be the reason a
        pipeline fails — but "best-effort" and "silent" are different things.
        A certificate assembled from a ledger that dropped a node outcome is
        missing exactly what it exists to attest, so the certificate says so
        rather than looking indistinguishable from a complete one.
        """
        with self._lock:
            return not self._record_failures

    @property
    def record_failures(self) -> List[str]:
        """Human-readable descriptions of what failed to record, if anything."""
        with self._lock:
            return list(self._record_failures)

    def _note_failure(self, what: str, exc: Exception) -> None:
        with self._lock:
            self._record_failures.append(f"{what}: {exc}")
        logger.warning(
            "Run evidence incomplete — could not record {what}: {exc}. The run "
            "certificate will be marked evidence_complete=false.",
            what=what,
            exc=exc,
        )

    # ── Context access (dict- or attribute-shaped) ───────────────────────────

    def _write(self, attr: str, value: Any) -> None:
        """Write one attribute, leaving failure reporting to the caller."""
        if isinstance(self._context, dict):
            self._context[attr] = value
        else:
            setattr(self._context, attr, value)

    def _set(self, attr: str, value: Any) -> None:
        try:
            self._write(attr, value)
        except Exception as e:  # noqa: BLE001 — bookkeeping must never break a run
            self._note_failure(f"ledger field '{attr}'", e)

    def _append(self, attr: str, record: Dict[str, Any], *, what: str) -> None:
        try:
            with self._lock:
                bucket = self._get(attr, None)
                if bucket is None:
                    bucket = []
                    # `_write`, not `_set`: a failure here belongs to what the
                    # caller was recording ("node trace for 'a'"), which is the
                    # useful thing to read back out of `evidence_gaps` — not the
                    # attribute name the caller never mentioned.
                    self._write(attr, bucket)
                if isinstance(bucket, list):
                    bucket.append(record)
                else:
                    # The wire format is a plain context attribute, so anything
                    # can land in it. Appending used to silently no-op here.
                    raise TypeError(
                        f"ledger field '{attr}' holds {type(bucket).__name__}, not list"
                    )
        except Exception as e:  # noqa: BLE001
            self._note_failure(what, e)


#: Serializes ledger *creation* across every context — not the ledger's own
#: per-instance lock, which only protects that one instance's collections.
#: Without this, two threads racing to call ledger_for() on the same
#: context before either had cached one could each construct and setattr
#: their own RunLedger, so the isolation each instance's lock promises
#: never actually applied to both callers.
_ledger_creation_lock = threading.Lock()


def ledger_for(context: Any) -> RunLedger:
    """Return the run's ledger, creating (and caching) one if absent.

    Components deep in the execution path receive only the context, so this is
    how they reach the ledger without every constructor growing an argument.
    """
    existing = getattr(context, "run_ledger", None)
    if isinstance(existing, RunLedger):
        return existing

    with _ledger_creation_lock:
        # Re-check: another thread may have created and cached one while
        # this one waited for the lock (double-checked locking, same
        # pattern as storage/base.py's get_storage_backend()).
        existing = getattr(context, "run_ledger", None)
        if isinstance(existing, RunLedger):
            return existing

        ledger = RunLedger(context)
        try:
            setattr(context, "run_ledger", ledger)
        except Exception:  # noqa: BLE001 — a read-only context still gets a working ledger
            pass
        return ledger


__all__ = ["RunLedger", "ledger_for"]
