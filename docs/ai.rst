AI Pipeline Builder
===================

``ducta ai`` drafts a new pipeline from a description in plain language. You
choose the model: a **local** one (Ollama, LM Studio, vLLM, llama.cpp — nothing
leaves your machine) or a **remote** one behind an API key (Anthropic, OpenAI,
or any OpenAI-compatible endpoint).

- The draft is checked by the same validation the UI runs on unsaved edits, in
  every environment. Its problems go back to the model until it passes.
- A draft only **adds**: one new pipeline file, new Python modules and new
  catalog entries. Existing pipelines, code and datasets are never rewritten.
- Nothing is written until you accept the draft, and nothing is ever run or
  committed.

Install
-------

.. code-block:: bash

   pip install "ducta[api,ai]"

Choose a model
--------------

The choice belongs to the machine, not the project, so it is kept in
``~/.ducta/ai.toml`` (``DUCTA_HOME`` moves it) and never in ``ducta.yaml``.

.. code-block:: bash

   # Local: the server's best code model (the largest *coder*), or --model to choose
   ducta ai setup --provider ollama
   ducta ai setup --provider lmstudio --model qwen2.5-coder-14b-instruct
   ducta ai setup --provider openai_compatible --base-url http://gpu-box:8000/v1 --model my-model

   # Remote, with an API key
   ducta ai setup --provider anthropic            # claude-opus-5-5 by default
   ducta ai setup --provider openai --model <model>

   ducta ai doctor                                # configuration, key source, connection

.. list-table::
   :widths: 25 35 40
   :header-rows: 1

   * - Provider
     - Default endpoint
     - Key
   * - ``ollama``
     - ``http://localhost:11434/v1``
     - none
   * - ``lmstudio``
     - ``http://localhost:1234/v1``
     - none
   * - ``openai_compatible``
     - ``--base-url`` (required)
     - ``--api-key-env``, if it needs one
   * - ``openai``
     - ``https://api.openai.com/v1``
     - ``OPENAI_API_KEY``
   * - ``anthropic``
     - ``https://api.anthropic.com``
     - ``ANTHROPIC_API_KEY``

``DUCTA_AI_PROVIDER``, ``DUCTA_AI_MODEL`` and ``DUCTA_AI_BASE_URL`` override the
file for one shell. Other keys in ``ai.toml``: ``timeout_seconds`` (default 300
— raise it for a slow local model), ``max_attempts`` (default 3),
``context_tokens`` (Ollama's context window, default 16384) and, for Anthropic,
``effort`` (``low`` … ``max``; ``high`` when unset, on the models that take it).
Running ``ducta ai setup`` again, or saving *Settings → AI*, changes only what
it is given: the other keys keep their values. Switching provider drops the old
provider's model, URL, key variable and effort.

With Anthropic, the instructions and the project's context are sent with prompt
caching, so the second and later attempts of a draft, and its revisions, pay a
fraction for them. With OpenAI's reasoning models, which take no
``temperature``, the request is retried once without it.

API keys
~~~~~~~~

A key is read from the variable the provider names (``ANTHROPIC_API_KEY``,
``OPENAI_API_KEY`` or ``--api-key-env``) and, failing that, from the system
keychain (macOS Keychain, Windows Credential Locker, Secret Service):

.. code-block:: bash

   ducta ai login      # asks for the key, hidden, and keeps it in the keychain
   ducta ai logout

Ducta never writes a key to a file, and ``ducta ai doctor`` shows it masked.

A keychain key is bound to the endpoint it was stored for: kept for ``openai``
it is only sent to ``api.openai.com``. Pointing a provider at another URL
(a gateway) needs a key stored for that URL — ``ducta ai login`` after
``ducta ai setup --base-url …`` — or a variable named with ``--api-key-env``.

Draft a pipeline
----------------

.. code-block:: bash

   cd my_project
   ducta ai new "silver pipeline that averages G1, G2 and G3 per school from the cleaned students"

You get the draft as a diff, its validation problems if any, and a draft id.
The draft is kept in ``.ducta/ai/drafts/`` (ignored by git):

.. code-block:: bash

   ducta ai apply 20261010-172522      # review again, confirm, write
   ducta ai new "..." --write          # write right away once it validates
   ducta ai new "..." --output-format json

``apply`` refuses if any file the draft touches changed after it was made, and
validates the draft again against the project as it is now (another file may
have added a node or dataset of the same name since); ``--force`` writes it
anyway.

What a draft may add is checked too: a new catalog entry cannot point
(``path``, ``table``) at data an existing dataset already names, and one the
pipeline writes keeps its path inside the project — no absolute path, ``..``
or URI. A new module cannot take the name of a standard-library module, nor a
new top-level one the name of an installed package.
Then check and run it as any other pipeline: ``ducta config validate``, a run in
``dev``, and a commit of your own.

Fix a pipeline
--------------

``ducta ai fix`` drafts a fix for an existing pipeline: its validation problems,
the error a run failed with, or what you say is wrong. A fix may rewrite that
pipeline's file and the modules its nodes run — nothing else — and is reviewed
and applied like any draft.

.. code-block:: bash

   ducta ai fix silver.clean                                  # its validation problems
   ducta ai fix silver.clean --error-file failure.log         # a run's traceback
   ducta ai fix silver.clean --note "Tuition comes in cents"  # what you know
   ducta ai drafts                                            # every draft, newest first

A draft is judged against the project as it was: problems it already had
elsewhere do not block a draft, and a fix is good only when no error is left on
its pipeline. A fix is checked without running anything — run the pipeline in
``dev`` to confirm it.

Ask for changes
---------------

A draft that is almost right does not need to start over. ``revise`` sends the
model its own answer and what to change, and makes a new draft linked to the
first:

.. code-block:: bash

   ducta ai revise 20261010-172522 --note "group by school and year"

Propose a node's quality checks
-------------------------------

.. code-block:: bash

   ducta ai quality etl transform                    # the node's output, measured in dev
   ducta ai quality etl transform --note "order_id is the key" --env staging

Ducta reads the node's output in ``--env`` (up to 50,000 rows), measures it —
for each column its type, share of nulls, number of distinct values and, for
numbers, the minimum and maximum — and sends those figures, never a row or a
value of a text column. The model proposes the node's whole ``quality`` block
using the checks Ducta can prove (``schema``, ``row_count``, ``empty_dataset``,
``null_rate``, ``duplicates``, ``range``) and a gate. **Ducta then runs that
block on the data it measured**: a check that would fail today goes back to the
model with the reason, so the draft you review passes on the current data.

The model writes no file: Ducta puts the block under the node in the pipeline
file, keeping its comments and layout. When the output has not been written in
that environment yet, the draft says it was not checked against data — run the
pipeline first.

Document the project
--------------------

.. code-block:: bash

   ducta ai document

Proposes a one-line ``description`` for every dataset, pipeline and node that
has none, and lists in ``metadata.pii`` the columns that hold personal data
(names, emails, phones, addresses, ids). Only what is missing is added — an
existing description is never replaced, and no other key changes. Column names
come from a dataset's ``schema``, or the header of its local data in ``--env``.

Explain a failed run
--------------------

.. code-block:: bash

   ducta ai explain --error-file failure.log
   ducta start --pipeline etl --env dev 2>&1 | ducta ai explain --error-file -

Ducta diagnoses the error first — the kind of failure, the line of your code it
was raised on, or, when the error gives no line (a Spark error), the function
of the node that failed — and the model explains it in three parts: *what
happened*, *why*, *what to do*. Nothing is changed. In the web app, a failed
run's page has **Explain with AI**: it also knows what changed since the last
good run, and the explanation is kept with the run
(``.ducta/ai/explanations/``), so reading it again costs nothing.

Review a node
-------------

.. code-block:: bash

   ducta ai review etl load                     # Ducta's checks, then the model's view
   ducta ai review etl load --no-ai             # only Ducta's checks: no model, no data sent
   ducta ai review etl load --fail-on high      # exit 3 when something high is found (CI)

Two passes, both checked by Ducta. First what Ducta is sure of, without a
model: a retried node whose output is appended (a retry duplicates rows), runs
that come within 20% of the node's timeout (from the run certificates),
``collect()``/``toPandas()`` or row-by-row loops, files read or written inside
the function, a credential in the code, ``requires_dates`` the function cannot
receive, an output other nodes read with no checks, and the validator's
problems. Then the model reads the node's function (numbered), its effective
settings in ``--env``, how long its last runs took and those findings, and
adds what it sees. **Each of its findings must cite a line of the function —
quoting it as it is — or a setting the node has**; one that does not is
dropped, and the review says how many were. Findings already made by Ducta are
not repeated.

A review changes nothing; it is kept per node (``.ducta/ai/reviews/``). To act
on a finding, draft a fix: ``ducta ai fix PIPELINE --note "<the finding>"``.

In the UI
---------

* **Build with AI**, next to *New pipeline* on a project's pipelines, opens the
  dialog: describe the pipeline, watch each attempt (*Stop* ends it, *Run in
  background* closes the dialog and says when it is done), review the files and
  their diff, then *Apply*, *Ask for changes…* or *Discard* (which asks first).
  *Drafts (n)* lists the earlier ones.
* **Fix with AI** appears above the problems of a pipeline that has errors, and
  on a failed run (which sends its error along).
* **Explain with AI**, on a failed run, shows the explanation under the run's
  diagnosis; it is kept with the run (↻ asks again).
* **Propose with AI**, on a node's *Quality* tab, proposes its checks — measured
  in the environment you pick — through the same draft dialog.
* **Document with AI**, next to *Build with AI*, appears while some dataset,
  pipeline or node has no description.
* **Review**, a tab of a node's inspector, shows its last review: *Run checks*
  (Ducta's, at once, no model) or *Review with AI*. Each finding links to its
  line and has *Draft a fix*, which opens a fix draft with the finding as its
  note.
* **Settings → AI** chooses the server's provider and model, tests the
  connection and keeps an API key in the server's keychain. Everyone with
  ``ai.use`` sees it; only an admin (``ai.configure``) changes it.

Applying writes the files and opens the pipeline; it never commits or runs it.

From the API
------------

The UI uses the same builder through the server (see :doc:`server_api`):

.. list-table::
   :widths: 45 55
   :header-rows: 1

   * - Route
     - Does
   * - ``GET /api/ai/settings``
     - Provider, model, endpoint, whether it is local, and where the key comes
       from (masked). Needs ``ai.use``.
   * - ``PUT /api/ai/settings``
     - Choose the server's provider and model (``ai.configure``). Fields left
       out keep their value; ``null`` resets one. ``api_key_env`` may only be
       the provider's own variable or a ``DUCTA_AI_*`` one, and another
       endpoint for ``openai``/``anthropic`` needs its own key.
   * - ``PUT`` / ``DELETE /api/ai/key``
     - Keep or remove an API key in the server's keychain (``ai.configure``).
       The key is never returned.
   * - ``GET /api/ai/models``
     - What the configured provider serves; also a connection test.
   * - ``POST /api/ai/models/test``
     - The same for settings not saved yet (the body of ``PUT /api/ai/settings``;
       ``ai.configure``, since it reaches the endpoint given). Saves nothing.
   * - ``POST /api/projects/{id}/ai/jobs``
     - Start a draft: ``{"request": "..."}``; ``{"kind": "fix", "pipeline":
       "...", "note": "...", "execution_id": "..."}`` to fix a pipeline from a
       failed run; ``{"kind": "revise", "draft_id": "...", "note": "..."}`` to
       ask for changes; ``{"kind": "quality", "pipeline": "...", "node": "...",
       "env": "dev"}`` for a node's checks; ``{"kind": "docs"}`` for the
       descriptions; ``{"kind": "explain", "execution_id": "..."}`` to explain a
       failed run (the job then holds ``explanation``, and no draft). Answers
       ``202`` at once.
   * - ``POST /api/projects/{id}/ai/reviews/{pipeline}/{node}/checks``
     - Ducta's own checks of a node, at once and without a model.
   * - ``GET /api/projects/{id}/ai/reviews/{pipeline}/{node}``
     - The node's last review, or ``404``. A review with the model is a job:
       ``{"kind": "review", "pipeline": "...", "node": "...", "env": "dev"}``
       (the job then holds ``review``).
   * - ``GET /api/projects/{id}/ai/explanations/{execution_id}``
     - The kept explanation of a run, or ``404`` (``ai.use`` and
       ``execution.read``).
   * - ``GET /api/projects/{id}/ai/jobs/{job}``
     - Its attempts so far; ``draft_id`` once done. Seen by who started it
       and by admins. Jobs are kept in ``.ducta/ai/jobs/``, so any server
       worker answers.
   * - ``DELETE /api/projects/{id}/ai/jobs/{job}``
     - Stop it: it reads as ``cancelled`` at once, makes no further request
       to the model and saves no draft.
   * - ``GET /api/projects/{id}/ai/drafts[/{draft}]``
     - The drafts; one with its files, diff, problems and attempts.
   * - ``POST /api/projects/{id}/ai/drafts/{draft}/apply``
     - Write it (``pipeline.write``). ``409`` if a file changed since;
       ``400`` if it does not validate now, unless ``{"force": true}``.
   * - ``DELETE /api/projects/{id}/ai/drafts/{draft}``
     - Discard it.

On a server without a keychain (a Linux container, typically), set the
provider's variable — ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY`` — in the
server's environment instead.

What the model sees
-------------------

The configuration a reviewer would see in a pull request: dataset names,
formats, descriptions and declared schemas; pipelines and their nodes; the
*names* of ingestion sources; the signatures of the project's functions; one
existing pipeline file and one node function as examples of house style, with
any credential written in them (a quoted password or key, a URL's password, a
bearer token) masked.

Never data rows, connection settings, catalog paths or ``.env``. A fix also
sends the files it may change and, when given, the run's error — with a URL's
password, ``password=``/``token=``-style values and bearer tokens replaced by
``***``; the rest of the error goes as it is. The files a fix may change go
whole, since the model answers with whole files: one that holds a credential is
not sent to a remote provider at all (move the value to a variable, or use a
local model), and a pipeline whose files exceed 60,000 characters is refused.
With a remote provider, ``ducta ai new``, ``fix`` and the UI say where this —
configuration and code — is being sent before they send it.

Choosing a local model
~~~~~~~~~~~~~~~~~~~~~~

Writing YAML that validates and code that matches it needs a code model of
about 7B parameters or more (for example ``qwen2.5-coder:7b`` or ``:14b``). A
small general model such as ``llama3.2`` (3B) usually exhausts its attempts:
the draft is saved with its problems, but it will not validate. Without
``--model``, ``ducta ai setup`` picks the largest code model the server has, and
says so when it has none.

Where the code goes
~~~~~~~~~~~~~~~~~~~

New modules go where the project already keeps the code its nodes run: the
folder most ``run:`` references use — ``pipelines/`` in the projects
``ducta template`` creates, ``src/`` in others (and when there is none yet).

Exit codes
~~~~~~~~~~

``ducta ai`` exits ``0`` when it worked, ``2`` when the configuration or the
request is wrong (no provider, no key, no project), ``3`` when a draft does not
validate, and ``5`` when the model could not be reached or understood.
