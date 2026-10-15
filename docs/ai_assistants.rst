AI Assistants (Agent Skill)
===========================

Ducta ships an **agent skill**: instructions, references and checks that let an AI
coding assistant install, configure, run and debug Ducta with you — creating a
project, adding a source or a pipeline, reading validation problems and fixing
them, diagnosing a failed run.

The skill uses the open `Agent Skills <https://agentskills.io>`_ format (a folder
with a ``SKILL.md``), so the same files work in Claude Code, Codex, Gemini CLI,
GitHub Copilot and the other assistants that read it. It is different from
:doc:`ai`, which drafts pipelines from inside Ducta with a model you configure.

Install it
----------

From inside a project:

.. code-block:: bash

   ducta skill install                      # .agents/skills/ and .claude/skills/
   ducta skill install --target copilot     # one assistant (repeat --target for more)
   ducta skill install --global             # in your home folder, for every project
   ducta skill install --agents-md          # also point AGENTS.md at it

.. list-table::
   :widths: 18 32 30 20
   :header-rows: 1

   * - ``--target``
     - Assistant
     - In the project
     - With ``--global``
   * - ``agents`` (default)
     - Codex, Gemini CLI, GitHub Copilot and others that share it
     - ``.agents/skills/``
     - ``~/.agents/skills/``
   * - ``claude`` (default)
     - Claude Code
     - ``.claude/skills/``
     - ``~/.claude/skills/``
   * - ``codex``
     - Codex (same folder as ``agents``)
     - ``.agents/skills/``
     - ``~/.agents/skills/``
   * - ``gemini``
     - Gemini CLI
     - ``.gemini/skills/``
     - ``~/.gemini/skills/``
   * - ``copilot``
     - GitHub Copilot (VS Code, CLI, cloud agent)
     - ``.github/skills/``
     - ``~/.copilot/skills/``

Run it anywhere inside the project: it installs next to ``ducta.yaml``. Outside a
project it warns and installs in the current folder (``--global`` is usually what
you want there). ``--path DIR`` installs into any other skills folder. Committing the project folders
shares the skill with your team. Installing again does nothing when the version is
the same; a different version needs ``--force``, and a folder named ``ducta`` that is
not Ducta's skill is never replaced. Some assistants still need skills switched on in
their settings — check your assistant's documentation.

GitHub Copilot reads ``.github/skills``, ``.claude/skills`` *and*
``.agents/skills``, and Gemini CLI reads ``.agents/skills`` as well as its own:
with the default install they find the skill twice. If yours lists Ducta twice,
install only the folder it needs (``--target agents``, plus ``--target claude``
only if someone uses Claude Code).

**Assistants without skill support** read ``AGENTS.md``: ``--agents-md`` adds a short
Ducta section there (between ``<!-- ducta-skill:start -->`` and ``<!-- ducta-skill:end -->``, so it is updated in
place and the rest of the file is kept) that points to the installed skill.

**claude.ai and the Skills API** take the skill as a zip:

.. code-block:: bash

   ducta skill export --zip ducta-skill.zip
   ducta skill path                         # where the packaged skill is

Use it
------

Restart the assistant after installing: skills are read when it starts. Then ask
for what you need in your own words — the assistant loads the skill by itself when
the task is about Ducta:

- *"Validate my project and fix the errors."*
- *"Add an ingestion from our SQL Server, table dbo.customers."*
- *"My run fails with an Arrow error — help."*
- *"Add a gold node with revenue per day from the cleaned data."*
- *"In prod, stop the run if the cleaned orders have null ids."*

If it does not pick the skill up, name it: *"use the ducta skill"* works in every
assistant, and Claude Code also accepts ``/ducta``.

What to expect, in order:

1. It checks the environment (``scripts/check_env.py``) and warns when the installed
   Ducta and the skill are different versions.
2. It reads the project's state with
   ``ducta config validate --env dev --output-format json``.
3. It proposes the smallest change, asks before writing files, and validates again
   until the project is clean.
4. If you paste a password or token, it tells you to put it in ``.env`` or an
   environment variable instead, and does not write it anywhere.

**Try it.** Create ``ducta template --template medallion_basic --project-name shop``,
misspell ``outputs`` as ``outptus`` on the ``transform`` node of ``pipelines/etl.yaml``,
install the skill
and ask *"my pipeline does not validate, fix it"*.

What it contains
----------------

.. code-block:: text

   ducta/
   ├── SKILL.md                 # when to use it, first steps, golden rules, workflows
   ├── references/              # installation, project format, pipelines, catalog,
   │                            # ingestion, execution, quality, mlops, streaming,
   │                            # server & UI, databricks, ai builder, best practices,
   │                            # troubleshooting, and the full CLI (generated)
   ├── scripts/check_env.py     # Python, Ducta, extras, Java — as JSON, read-only
   └── assets/examples/sales/   # a small valid project to copy patterns from

The assistant reads only ``SKILL.md`` at first and opens a reference when the task
needs it.

What it tells the assistant to do — and not do
-----------------------------------------------

- Check the environment and the project's state before changing anything:
  ``python3 scripts/check_env.py`` and
  ``ducta config validate --env dev --output-format json``.
- Trust the installed CLI over its own notes: ``ducta config schema`` and
  ``--help`` when the versions differ.
- Make the smallest change, ask before writing files, and validate again.
- Never commit, run in a protected environment (``prod``), delete data or pass
  ``--force`` unless you ask; never write or ask for credentials — they go in
  environment variables or ``.env``.
- Say that ``ducta config validate`` imports the project's Python code before running
  it on code it has not read.

Machine-readable validation
---------------------------

``ducta config validate --output-format json`` prints one JSON document — useful for
the skill, for CI and for any script:

.. code-block:: json

   {"ok": false, "env": "dev",
    "pipelines": {},
    "config_error": [
      {"severity": "error", "code": "unknown_key", "source": "config",
       "message": "...unknown key 'outptus' — did you mean 'outputs'?",
       "file": "pipelines/etl.yaml", "line": 21, "node": null, "pipeline": null,
       "fix": {"label": "Replace 'outptus' with 'outputs'", "replace": ["outptus", "outputs"]}}]}

``config_error`` holds what stops the project from loading (an unknown key, a dataset
missing from the catalog…). Once it loads, preflight's problems appear per pipeline,
``"pipelines": {"etl": {"ok": false, "problems": [...]}}``.

The exit codes are unchanged: ``0`` valid, ``2`` the project does not load
(``config_error``), ``3`` problems found by preflight.

Keeping it current
------------------

The skill is versioned with Ducta (``metadata.ducta-version`` in ``SKILL.md``). After
upgrading Ducta, run ``ducta skill install --force`` to update the copies you
installed. Ducta's own tests check that every command and flag the skill names
exists, that its CLI reference is generated from the real parser, and that its
example project validates.
