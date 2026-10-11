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
keychain; a keychain key is only sent to the endpoint it was stored for. `ducta ai login`
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
ducta ai revise DRAFT_ID --note "group by store too"  # ask for changes
ducta ai drafts                                       # every draft, newest first
ducta ai apply DRAFT_ID                               # review, confirm, write
ducta ai quality etl transform --env dev              # a node's checks, proven on its data
ducta ai document                                     # missing descriptions and metadata.pii
ducta ai explain --error-file failure.log             # why a run failed; changes nothing
ducta ai review etl load [--no-ai] [--fail-on high]   # a node's code and settings reviewed
```

`quality` sends column statistics only (never rows), and Ducta runs the proposed checks
on the measured data before the draft is shown: it passes on today's data. `quality` and
`document` drafts only add — a node's `quality` block, or a missing `description` /
`metadata.pii` — and keep the file's comments.

Drafts are kept in `.ducta/ai/drafts/`. A `new` draft only adds (one pipeline file, new
modules, new catalog entries); a `fix` may rewrite that pipeline's file and the modules
its nodes run. `apply` refuses if a file changed since, and re-validates against the
current project (`--force` overrides; only if the user asks). After applying: validate
every environment, run in `dev`, and let the user commit.

With a remote provider the project's configuration and code are sent to it (never data
rows, `.env` or connection settings). A fix whose files contain a credential is refused
for remote providers. Say where the request goes before running it.

## In the web app

**Build with AI** (next to *New pipeline*), **Fix with AI** (on a pipeline's problems
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
| "fills Ollama's context window" | raise `context_tokens` in `~/.ducta/ai.toml` |
| draft "still invalid after N attempts" | a bigger model, a more precise request, or `ducta ai revise` |
| "The project does not validate now" | fix the project first (`ducta ai fix PIPELINE` can help) |
