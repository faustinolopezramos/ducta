Run Certificates
=================

Every pipeline run that terminates — success or failure — writes a
**Run Certificate**: a self-hashed, optionally signed JSON record of what ran,
against which data, with what result. This tutorial covers what a certificate
actually proves, how to configure and inspect one, and the mistakes that make
a certificate say less than it looks like it says.

Where it lives
---------------

.. code-block:: text

   .ducta/runs/<environment>/<run_id>/certificate.json

One file per run, scoped by environment so a ``dev`` run and a ``prod`` run
with the same pipeline never collide.

Anatomy of a certificate
-------------------------

A trimmed real certificate, from a batch ingestion run:

.. code-block:: json

   {
     "schema_version": "1.2",
     "run_id": "f9fb815596a74bf2a66d6cf3570b5493",
     "pipeline": "bronze.ingestion",
     "environment_name": "base",
     "status": "success",
     "config_fingerprint": "sha256:aa6f58fe...",
     "environment": {
       "python_version": "3.13.14",
       "git_commit": "b7f0e91",
       "git_dirty": false,
       "pip_packages": { "...": "..." }
     },
     "nodes": [
       { "name": "bronze.ingest_student", "type": "ingestion",
         "status": "success", "duration_seconds": 2.69,
         "outputs": ["bronze.education.student"] }
     ],
     "outputs": {
       "bronze.education.student": {
         "row_count": 395,
         "schema_hash": "sha256:b04ea2c3...",
         "engine": "spark",
         "algorithm": "xxhash64-multiset/v2",
         "mode": "exact",
         "content_hash": "sha256:...",
         "fingerprint": "sha256:..."
       }
     },
     "quality": [
       { "node": "bronze.ingest_student", "phase": "sanity",
         "passed": true, "score": 1.0, "errors": 0, "warnings": 0 }
     ],
     "evidence_complete": true,
     "evidence_gaps": [],
     "certificate_hash": "sha256:3f9dfe0f...",
     "signature": "hmac-sha256:e89b7169...",
     "key_id": "614db60e"
   }

The fields that matter most when you're deciding how much to trust a given
certificate:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - What it tells you
   * - ``config_fingerprint``
     - Hash over the five config documents (global config, pipelines,
       nodes, input, output). Changes the instant *any* of them changes —
       lets you confirm "this ran with the config I think it did" without
       diffing YAML by hand.
   * - ``inputs`` / ``outputs``
     - Per-dataset fingerprints: ``row_count``, ``schema_hash``,
       ``algorithm``, ``mode``, ``content_hash``. This is the part that
       actually proves something about the *data*, not just that a node ran.
   * - ``evidence_complete`` / ``evidence_gaps``
     - ``False`` (plus a reason) when the run's ledger failed to record
       something it was asked to. The certificate still gets written — a
       partial record beats none — but it says so, instead of looking
       identical to a complete one.
   * - ``certificate_hash``
     - SHA-256 over every field above. Detects corruption.
   * - ``signature`` / ``key_id``
     - Present only when a signing key was configured. Turns "not
       corrupted" into "produced by whoever holds the key" — see below.

Three levels of proof — don't conflate them
---------------------------------------------

A certificate can back up three different claims, and they require
different things from you:

.. list-table::
   :header-rows: 1
   :widths: 20 35 45

   * - Level
     - What it proves
     - What it needs
   * - ``certificate_hash``
     - The file hasn't been corrupted or hand-edited since it was written
       (a truncated copy, a bad merge).
     - Nothing — always present, computed with no secret.
   * - ``signature``
     - The certificate was produced by someone holding the signing key —
       *attribution*, and what makes it tamper-**evident** rather than just
       tamper-detectable.
     - ``DUCTA_CERTIFICATE_KEY`` set at run time. Without it, anyone who
       edits the JSON can recompute ``certificate_hash`` themselves and
       ``verify`` still passes.
   * - ``--reproduce``
     - The pipeline is genuinely reproducible: run it again today and every
       output's fingerprint still matches what the certificate claims.
     - The pipeline still runnable against the same (or an equivalent)
       input, and a fingerprint ``algorithm`` that hasn't changed since the
       certificate was written (see *Comparing certificates* below).

The source is blunt about the first point, and it's worth repeating exactly:

    ``certificate_hash`` is a keyless SHA-256 over every other field... It is
    not by itself evidence against a motivated editor, who can recompute the
    hash over their own content and pass verification.

**If a certificate needs to hold up as evidence — an audit, a dispute, "prove
this ran the way we said it did" — set the signing key.** An unsigned
certificate is a checksum against accidents, not a claim you can defend
against someone who edited it on purpose.

Configuring certification
---------------------------

In ``config/global_config.{yaml,toml}``:

.. code-block:: yaml

   enable_run_certificate: true          # on by default
   run_certificate_dir: ".ducta/runs"    # default

   enable_data_fingerprinting: true
   fingerprint_mode: "exact"             # exact | sample | schema

Signing key, as an environment variable (preferred over a config value —
see below):

.. code-block:: bash

   export DUCTA_CERTIFICATE_KEY="a-long-random-secret"

The code also accepts the historical mixed-case name
``Ducta_CERTIFICATE_KEY``; use the all-caps form above for anything you
write yourself. A key can also live at
``global_config.certificate_signing_key``, but Ducta logs a warning if you
do — a key in a config file is usually committed to version control, and a
short, human-chosen value is brute-forceable from the certificate's public
``key_id``. Prefer the environment variable.

Fingerprint modes: what "exact" is buying you
------------------------------------------------

``fingerprint_mode`` controls how thoroughly each dataset is hashed, and the
difference is not cosmetic:

.. list-table::
   :header-rows: 1
   :widths: 15 35 50

   * - Mode
     - How it hashes
     - What it misses
   * - ``exact`` (default)
     - Order-independent digest over **every row** (Spark: ``xxhash64`` per
       row, aggregated by count/sum/bit_xor). A single changed cell
       anywhere — first row or last — changes the fingerprint. Insensitive
       to row reordering or repartitioning.
     - Nothing, short of a hash collision.
   * - ``sample``
     - Hashes only the first *N* rows (head-only).
     - A change to any row outside the sampled window is invisible. On a
       large table this is most of it.
   * - ``schema``
     - Hashes column names and types only.
     - Every row. Two datasets with the same schema and completely
       different content fingerprint identically.

The legacy aliases ``fast`` and ``full`` still parse — they map to
``sample`` and ``exact`` respectively — but write ``exact``/``sample``/
``schema`` explicitly in new configs. ``fast`` in particular reads like
"the quick version of exact" and is actually "hash only the first 100
rows"; a project that sets it without realizing what it maps to ends up
with certificates that look complete and aren't.

``sample``/``schema`` are legitimate choices when a full scan is too
expensive for a given project's data volume — that's a real trade-off, not
a mistake — but make it a deliberate one, and know that ``ducta certify
show`` and ``ducta certify verify`` both flag a non-``exact`` mode
explicitly for exactly this reason (see below).

The CLI, end to end
----------------------

.. code-block:: bash

   ducta certify list  [--env base] [--dir .ducta/runs]
   ducta certify show    --run-id <id-or-prefix> [--json]
   ducta certify verify  --run-id <id-or-prefix> [--reproduce] [--start-date ...] [--end-date ...]
   ducta certify diff    <run_a> <run_b>

``--run-id`` accepts a unique prefix — you don't need to paste the full
UUID.

``list`` — every run recorded here
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   $ ducta certify list --env base

    Run ID        Pipeline    Status      Env    Started   Duration  Quality     Signed
    ────────────────────────────────────────────────────────────────────────────────────
    f9fb815596a7  bronze.ing  ✓ success   base   3h ago    2.9s      2/2 passed  🔏

``show`` — inspect one run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   $ ducta certify show --run-id f9fb8155

   ╭─────────────────────────── Run Certificate ───────────────────────────╮
   │ Run ID              f9fb815596a74bf2a66d6cf3570b5493                  │
   │ Pipeline            bronze.ingestion                                  │
   │ Status              ✓ success                                        │
   │ Signed              🔏 yes (key 614db60e)                             │
   ╰─────────────────────────────────────────────────────────────────────╯
                                    Datasets
    Key                          I/O      Rows   Schema hash        Fingerprint
    ─────────────────────────────────────────────────────────────────────────
    bronze.education.student     output   395    b04ea2c3296853c6…  exact

The ``Fingerprint`` column and the ``Signed``/``Evidence`` rows in the
summary panel are visible without ``--json`` — that matters. A
``sample``-mode fingerprint or an unsigned certificate used to be
indistinguishable from an ``exact``, fully attested one unless you passed
``--json`` and read the raw fields yourself. Now the pretty view says so
directly: a non-``exact`` mode prints in yellow (e.g. ``sample (100
rows)``), and an unsigned certificate reads *"no — hash only, not
tamper-evident"* rather than a bare *"no"*.

``verify`` — the tamper check
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   $ ducta certify verify --run-id f9fb8155
   ✓ Certificate f9fb815596a7... verified: hash matches and signature valid [signature: valid]

If any input or output was fingerprinted in ``sample`` or ``schema`` mode,
``verify`` also warns explicitly — this is the command people run
specifically to decide whether to trust a certificate, so the warning
belongs here, not only in the JSON:

.. code-block:: text

   $ ducta certify verify --run-id 19a88fcb
   ✓ Certificate 19a88fcb7fac... verified: hash matches and signature valid [signature: valid]
   ⚠ fingerprint mode is not 'exact' for: bronze.education.student (sample) —
     a change outside what was hashed would not be detected

``verify --reproduce`` — the strong claim
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Re-runs the pipeline for real and compares every recorded output's
fingerprint against a fresh one:

.. code-block:: bash

   ducta certify verify --run-id f9fb8155 --reproduce \
     --start-date 2026-01-01 --end-date 2026-01-31

Two outcomes beyond plain match/mismatch are worth knowing:

* If the original run was blocked by a quality gate, ``--reproduce`` says so
  and stops — comparing against outputs that were never written would be
  comparing against nothing.
* If the certificate was written by a different fingerprint algorithm (most
  often: before a Ducta upgrade), the comparison reports **not comparable**
  for that dataset rather than claiming the data changed. See the next
  section for why that distinction is deliberate.

``diff`` — compare two runs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   ducta certify diff <run_a> <run_b>

Compares config fingerprint, pipeline/environment/status, every output's
fingerprint, and every quality verdict. A real example — diffing a run
written with ``fingerprint_mode: sample`` against one of the same pipeline
written with ``fingerprint_mode: exact``:

.. code-block:: text

   $ ducta certify diff 19a88fcb7fac f9fb815596a7

     bronze.education.student   not comparable
       (algorithm differs: spark-head/v2 vs xxhash64-multiset/v2)

   ⚠ Certificates differ — see mismatches above

This is not a false alarm about the data — it's Ducta refusing to guess.
Two fingerprints only mean something relative to the algorithm that
produced them, so comparing across an algorithm change reports **"we
cannot tell"**, a genuinely different answer from **"the data changed"**.
Reporting the latter when only the measurement changed would be a false
alarm on every certificate written before a Ducta upgrade — exactly the
kind of noise that teaches people to stop reading the one signal this
system exists to give them.

Programmatic use
--------------------

Everything above is also a public, stable API:

.. code-block:: python

   from pathlib import Path
   from ducta import verify_certificate, load_certificate, build_certificate

   cert = load_certificate(Path(".ducta/runs/base/f9fb8155.../certificate.json"))
   result = verify_certificate(Path("...certificate.json"), signing_key=key)
   print(result.ok, result.reason, result.signature)

Useful for CI: verify (and optionally ``--reproduce``, via the CLI) every
certificate a pipeline run produces before promoting an artifact, without
writing custom parsing against the JSON schema yourself.

Checklist before you rely on a certificate
----------------------------------------------

- **Signing key set?** Check the ``Signed`` row in ``certify show``, or run
  ``certify verify`` and read the ``[signature: ...]`` suffix. ``present (no
  key)`` means the certificate is signed but *you* have no way to check it
  right now — get the key before treating it as verified.
- **Fingerprint mode?** ``certify show`` and ``certify verify`` both flag
  anything other than ``exact`` now. Know why a project chose ``sample`` or
  ``schema`` before trusting the certificate's data claim at face value.
- **``evidence_complete``?** If ``false``, read ``evidence_gaps`` — the
  certificate is telling you it couldn't record something, not hiding it.
- **Comparing two certificates?** Use ``certify diff``, not a manual JSON
  diff — it already knows when two fingerprints aren't comparable and won't
  report a false "changed."

See also
------------

- :doc:`mlops` — experiment tracking and the model registry, which
  certificates link to via ``mlops_run_id``.
- `core/README.md <https://github.com/faustinolopezramos/ducta/blob/main/src/ducta/core/README.md>`_
  — the certificate module in the context of the execution engine as a
  whole.
