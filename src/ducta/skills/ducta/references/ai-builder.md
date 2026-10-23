# `ducta ai`: drafting pipelines with a model

Ducta can draft a new pipeline, or a fix for one, with a local model (Ollama, LM
Studio, vLLM…) or a remote one (Anthropic, OpenAI, any OpenAI-compatible endpoint).
A draft is validated, shown as a diff, and written only when accepted; nothing is run
or committed. Needs `pip install "ducta[api,ai]"`.

## Set up the model (per machine: `~/.ducta/ai.toml`)

```bash
ducta ai setup --provider ollama --model qwen2.5-coder:14b      # local
ducta ai setup --provider anthropic                             # claude-opus-5-5 by default
ducta ai setup --provider openai_compatible --base-url http://gpu:8000/v1 --model my-model
ducta ai login            # stores an API key in the system keychain (hidden prompt)
ducta ai doctor           # shows provider, endpoint, key source (masked), and lists models
```

Running `setup` again changes only what is passed. Keys come from the provider's
variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `--api-key-env NAME`) or the
keychain. A key only goes to its own endpoint: with `--base-url` pointing elsewhere,
the provider's variable is not used — set `--api-key-env NAME` or `ducta ai login`. `ducta ai login`
needs a terminal: ask the user to run it, and never ask for the key in the chat.

Local models: use a code model of ~7B+ (`qwen2.5-coder:7b`/`:14b`); 3B models rarely
produce a valid draft. For Ollama, raise `context_tokens` in `ai.toml` if the request
"fills the context window".

## Draft, review, apply

```bash
ducta ai new "silver pipeline that deduplicates orders and computes daily revenue"
ducta ai fix silver.clean                             # its validation problems
ducta ai fix silver.clean --error-file failure.log    # a failed run's traceback
ducta ai fix silver.clean --note "amounts come in cents"
ducta ai extend silver.clean "one row per customer, latest order wins"   # new nodes; existing ones untouched
ducta ai revise DRAFT_ID --note "group by store too"  # ask for changes
ducta ai drafts                                       # every draft, newest first
ducta ai apply DRAFT_ID                               # review, confirm, write
ducta ai quality etl transform --env dev              # a node's checks, proven on its data
ducta ai document                                     # missing descriptions and metadata.pii
ducta ai explain --error-file failure.log             # why a run failed; changes nothing
ducta ai review etl load [--no-ai] [--fail-on high]   # a node's code and settings reviewed
ducta ai review etl [--no-ai]                         # the whole pipeline, plus ideas for new nodes
```

`quality` sends column statistics only (never rows), and Ducta runs the proposed checks
on the measured data before the draft is shown: it passes on today's data. `quality` and
`document` drafts only add — a node's `quality` block, or a missing `description` /
`metadata.pii` — and keep the file's comments.

Drafts are kept in `.ducta/ai/drafts/`. A `new` draft only adds (one pipeline file, new
modules, new catalog entries); a `fix` may rewrite that pipeline's file and the modules
its nodes run; an `extend` only adds to them — Ducta refuses (also at `apply`, even
forced) a draft that changes an existing node, key, function or import. To grow a
pipeline, prefer `extend` over a `fix` with a note. A pipeline review's ideas are the
model's, unchecked: each is a request for `extend`. `apply` refuses if a file changed since, and re-validates against the
current project (`--force` overrides; only if the user asks). After applying: validate
every environment, run in `dev`, and let the user commit.

With a remote provider the project's configuration and code are sent to it (never data
rows, `.env` or connection settings); credentials written in settings (an ingest's
`options`, `spark_config`) go as `***`. A fix — or a revision of one — whose files
contain a credential (a quoted or unquoted password or key, one inside a connection
string such as `jdbc:…;password=…`, a private key, a JWT) is refused for remote providers.
The code a `new`, `fix` or `extend` draft adds is reviewed (commands, network, file or
table I/O, `collect()`); it is a net for the obvious, not a sandbox. Say where the
request goes before running it.

For several pipelines at once, designed first and built after, use Ducta Architect;
for failed and late runs, Ducta Sentinel — see [agents](agents.md).

## In the web app

**Review pipeline** and **Add nodes with AI** (at the top of a pipeline), **Build with AI** (next to *New pipeline*), **Fix with AI** (on a pipeline's problems
and on a failed run), **Explain with AI** (on a failed run), **Propose with AI** (a node's
*Quality* tab), the node's **Review** tab, **Document with AI** (while something has no description), and
**Settings → AI** (admins choose the model and key).

## Common problems

| Symptom | Fix |
|---|---|
| "No AI provider is configured" | `ducta ai setup --provider …` |
| "needs an API key" | set the provider's variable, or `ducta ai login` |
| "Cannot reach … Is the local server running" | start it (`ollama serve`) or fix `--base-url` |
| "does not serve model" | `ducta ai doctor` lists the models; `ollama pull NAME` |
| "fills Ollama's context window" / "does not fit the model's context window" | raise `context_tokens` in `~/.ducta/ai.toml` |
| draft "still invalid after N attempts" | a bigger model, a more precise request, or `ducta ai revise` |
| "The project does not validate now" | fix the project first (`ducta ai fix PIPELINE` can help) |
