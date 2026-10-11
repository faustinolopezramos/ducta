import { useEffect, useState, type FormEvent } from "react";
import { IconCircleCheck, IconCircleX } from "@tabler/icons-react";
import {
  type AISettings as AISettingsData,
  useAIModels,
  useAISettings,
  useDeleteAIKey,
  useStoreAIKey,
  useTestAIConnection,
  useUpdateAISettings,
  type AIProviderInfo,
  type AISettingsUpdate,
} from "../../api/aiApi";
import { apiErrorMessage } from "../../api/mutations/errors";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { toastStore } from "../../hooks/useModalStack";
import { requiresPermission, usePermission } from "../../hooks/usePermission";
import "../../components/AI/AIDraftDialog.css";
import "./AISettings.css";

const HINT: Record<string, string> = {
  ollama: "Local · no key",
  lmstudio: "Local · no key",
  openai_compatible: "vLLM, llama.cpp, a gateway",
  openai: "API key",
  anthropic: "API key · Claude",
};

/** Anthropic's reasoning effort; "" keeps the model's default. */
const EFFORTS = ["", "low", "medium", "high", "xhigh", "max"];

/** Local first, then the endpoint you host, then the APIs. */
const ORDER = ["ollama", "lmstudio", "openai_compatible", "openai", "anthropic"];

/** "Ollama (local)" → "Ollama": the card's hint already says it is local. */
const providerName = (p: AIProviderInfo) => p.label.replace(/ \((local|Claude)\)$| endpoint$/, "");

/**
 * Settings → AI: the model that drafts and fixes pipelines. It belongs to the
 * server, not the project, and only an admin (`ai.configure`) changes it. A key
 * is written once and never shown again — only where it comes from, masked.
 */
export function AISettings() {
  const { data: settings, isLoading } = useAISettings();
  if (isLoading || !settings) return <p className="ai-dim">Loading…</p>;
  // Keyed on what was saved: a save (or another admin's) starts the form afresh.
  return <AISettingsForm key={`${settings.provider}|${settings.model}|${settings.base_url}`} settings={settings} />;
}

function AISettingsForm({ settings }: { settings: AISettingsData }) {
  const canConfigure = usePermission("ai.configure");
  const update = useUpdateAISettings();
  // An admin tests what is in the form, saved or not; anyone else, what is saved.
  const test = useTestAIConnection();
  const saved = useAIModels();
  const [provider, setProvider] = useState<string>(settings.provider ?? "ollama");
  const [model, setModel] = useState(settings.model ?? "");
  const [baseUrl, setBaseUrl] = useState(settings.base_url ?? "");
  const [effort, setEffort] = useState(settings.effort ?? "");
  const [attempts, setAttempts] = useState(String(settings.max_attempts ?? 3));

  const preset: AIProviderInfo | undefined = settings.providers.find((p) => p.name === provider);
  const changedProvider = provider !== settings.provider;
  const showsEndpoint = provider !== "anthropic";
  const showsEffort = provider === "anthropic";
  const attemptsValue = Math.min(10, Math.max(1, Number.parseInt(attempts, 10) || 3));
  const dirty =
    changedProvider ||
    model !== (settings.model ?? "") ||
    baseUrl !== (settings.base_url ?? "") ||
    (showsEffort && effort !== (settings.effort ?? "")) ||
    attemptsValue !== (settings.max_attempts ?? 3);
  const needsKey = Boolean(preset?.needs_key) || provider === "openai_compatible";

  const body = (): AISettingsUpdate => ({
    provider,
    model: model.trim() || null,
    base_url: showsEndpoint && baseUrl.trim() && baseUrl.trim() !== preset?.default_base_url ? baseUrl.trim() : null,
    ...(showsEffort ? { effort: effort || null } : {}),
    max_attempts: attemptsValue,
  });
  const result = canConfigure
    ? { data: test.data, error: test.error, isError: test.isError, busy: test.isPending }
    : { data: saved.data, error: saved.error, isError: saved.isError, busy: saved.isFetching };
  const runTest = () => (canConfigure ? test.mutate(body()) : void saved.refetch());
  const modelList = result.data?.models ?? [];
  const testedEndpoint = (showsEndpoint && baseUrl.trim()) || preset?.default_base_url || settings.endpoint;

  // A saved provider fills the model list on arrival: listing models costs nothing.
  useEffect(() => {
    if (settings.configured) runTest();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for what was saved
  }, []);

  const pick = (name: string) => {
    setProvider(name);
    const p = settings.providers.find((x) => x.name === name);
    if (name !== settings.provider) {
      setModel(p?.default_model ?? "");
      setBaseUrl(p?.default_base_url ?? "");
      setEffort("");
    } else {
      setModel(settings.model ?? "");
      setBaseUrl(settings.base_url ?? "");
      setEffort(settings.effort ?? "");
    }
    test.reset();
  };

  const save = (e: FormEvent) => {
    e.preventDefault();
    update.mutate(body(), { onSuccess: () => toastStore.getState().show("AI model saved", "success") });
  };

  return (
    <form className="ai-settings" onSubmit={save} noValidate>
      {!canConfigure && (
        <p className="ai-context" role="note">
          {requiresPermission("ai.configure")} to change these. Ask an admin.
        </p>
      )}

      <fieldset className="ai-settings__fieldset" disabled={!canConfigure}>
        <legend className="projects-modal__label">Provider</legend>
        <div className="ai-providers" role="radiogroup" aria-label="Provider">
          {[...settings.providers].sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name)).map((p) => (
            // The label wraps its radio and holds the provider's name; the rule cannot see text from an expression.
            // eslint-disable-next-line jsx-a11y/label-has-associated-control
            <label
              key={p.name}
              htmlFor={`ai-provider-${p.name}`}
              className={`ai-provider${p.name === provider ? " is-active" : ""}`}
            >
              <input
                type="radio"
                name="ai-provider"
                id={`ai-provider-${p.name}`}
                value={p.name}
                checked={p.name === provider}
                onChange={() => pick(p.name)}
              />
              <span>
                <b>{providerName(p)}</b>
                <small>{HINT[p.name] ?? (p.local ? "Local" : "API key")}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="ai-settings__grid">
        <div className="ai-settings__field">
          <label className="projects-modal__label" htmlFor="ai-model">
            Model
          </label>
          <div className="ai-settings__inline">
            <input
              id="ai-model"
              className="projects-modal__input"
              list="ai-model-options"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={provider === "ollama" ? "qwen2.5-coder:14b" : "model name"}
              disabled={!canConfigure}
              autoComplete="off"
            />
            <datalist id="ai-model-options">
              {modelList.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            <Button
              type="button"
              variant="secondary"
              loading={result.busy}
              disabled={!canConfigure && dirty}
              title={canConfigure ? "Tests what is in the form; nothing is saved" : undefined}
              onClick={runTest}
            >
              Test connection
            </Button>
          </div>
          {result.isError ? (
            <p className="projects-modal__hint dash-hint-error" role="alert">
              <IconCircleX size={13} aria-hidden="true" /> {apiErrorMessage(result.error, "Couldn’t reach the provider.")}
            </p>
          ) : result.data ? (
            <p className="projects-modal__hint" role="status">
              <IconCircleCheck size={13} className="ai-ok" aria-hidden="true" /> Connected to {testedEndpoint} —{" "}
              {modelList.length} model{modelList.length === 1 ? "" : "s"}
              {model.trim() && modelList.length > 0 && !modelList.includes(model.trim())
                ? `, but not “${model.trim()}”`
                : ""}
              .
            </p>
          ) : (
            <p className="projects-modal__hint">
              {provider === "ollama" || provider === "lmstudio"
                ? "A code model of 7B or more works best (e.g. qwen2.5-coder)."
                : "As the provider names it."}
            </p>
          )}
        </div>

        {showsEffort && (
          <div className="ai-settings__field">
            <label className="projects-modal__label" htmlFor="ai-effort">
              Effort
            </label>
            <select
              id="ai-effort"
              className="projects-modal__input"
              value={effort}
              onChange={(e) => setEffort(e.target.value)}
              disabled={!canConfigure}
            >
              {EFFORTS.map((e) => (
                <option key={e} value={e}>
                  {e || "Model default"}
                </option>
              ))}
            </select>
            <p className="projects-modal__hint">More effort: better drafts, slower and more tokens.</p>
          </div>
        )}

        <div className="ai-settings__field">
          <label className="projects-modal__label" htmlFor="ai-attempts">
            Attempts
          </label>
          <input
            id="ai-attempts"
            type="number"
            min={1}
            max={10}
            className="projects-modal__input"
            value={attempts}
            onChange={(e) => setAttempts(e.target.value)}
            disabled={!canConfigure}
          />
          <p className="projects-modal__hint">Times the model may fix what the validator finds (1–10).</p>
        </div>

        {showsEndpoint && (
          <div className="ai-settings__field">
            <label className="projects-modal__label" htmlFor="ai-endpoint">
              Endpoint
            </label>
            <input
              id="ai-endpoint"
              className="projects-modal__input ai-mono"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://localhost:8000/v1"
              disabled={!canConfigure}
              autoComplete="off"
            />
          </div>
        )}
      </div>

      {needsKey && <KeyBox provider={provider} canConfigure={canConfigure} pendingProvider={changedProvider} />}

      <div className="ai-settings__privacy">
        <b>What the model receives</b>
        <p>
          Dataset names, formats and descriptions, pipelines and nodes, source names, function signatures and one
          example of each. A fix also sends the files it may change and the run’s error. Never data rows,
          credentials or .env.
          {settings.is_local && !changedProvider ? " With this local model, nothing leaves the server." : ""}
        </p>
      </div>

      {update.isError && (
        <p className="dash-form-error" role="alert">
          {apiErrorMessage(update.error, "Couldn’t save.")}
        </p>
      )}
      {canConfigure && (
        <div className="ai-actions ai-settings__actions">
          <Button type="submit" variant="primary" loading={update.isPending} disabled={!dirty}>
            Save
          </Button>
        </div>
      )}
    </form>
  );
}

/** The provider's key: where it comes from (masked), or a field to keep one in the keychain. */
function KeyBox({
  provider,
  canConfigure,
  pendingProvider,
}: {
  provider: string;
  canConfigure: boolean;
  pendingProvider: boolean;
}) {
  const { data: settings } = useAISettings();
  const store = useStoreAIKey();
  const remove = useDeleteAIKey();
  const [replacing, setReplacing] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [key, setKey] = useState("");
  if (!settings) return null;
  const preset = settings.providers.find((p) => p.name === provider);
  const info = !pendingProvider ? settings.key : null;
  const envName = (!pendingProvider && settings.api_key_env) || preset?.api_key_env;
  const fromEnv = info?.source.startsWith("env:");
  const editing = canConfigure && (replacing || !info?.present);

  return (
    <div className="ai-settings__key">
      <p className="projects-modal__label">API key</p>
      {pendingProvider ? (
        <p className="projects-modal__hint">Save the provider first, then add its key.</p>
      ) : info?.present && !replacing ? (
        <div className="ai-settings__inline">
          <span className="ai-settings__keystate">
            <span className="ai-dot ai-dot--ok" aria-hidden="true" />
            {fromEnv ? `From ${info.source.slice(4)} in the server's environment` : "Stored in the server keychain"} ·{" "}
            <span className="ai-mono">{info.masked}</span>
          </span>
          {canConfigure && !fromEnv && (
            <>
              <Button type="button" variant="ghost" size="sm" onClick={() => setReplacing(true)}>
                Replace
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="ai-settings__remove"
                loading={remove.isPending}
                onClick={() => setConfirmRemove(true)}
              >
                Remove
              </Button>
            </>
          )}
        </div>
      ) : editing ? (
        <div className="ai-settings__inline">
          <label className="sr-only" htmlFor="ai-key">
            API key
          </label>
          <input
            id="ai-key"
            type="password"
            className="projects-modal__input ai-mono ai-settings__keyinput"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={provider === "anthropic" ? "sk-ant-…" : "sk-…"}
            autoComplete="off"
            disabled={!settings.keychain_available}
          />
          <Button
            type="button"
            variant="secondary"
            loading={store.isPending}
            disabled={!key.trim() || !settings.keychain_available}
            onClick={() =>
              store.mutate(
                { api_key: key, provider },
                {
                  onSuccess: () => {
                    setKey("");
                    setReplacing(false);
                    toastStore.getState().show("API key stored in the server keychain", "success");
                  },
                },
              )
            }
          >
            Store key
          </Button>
          {replacing && (
            <Button type="button" variant="ghost" size="sm" onClick={() => setReplacing(false)}>
              Cancel
            </Button>
          )}
        </div>
      ) : (
        <p className="projects-modal__hint">No key yet.</p>
      )}
      <p className="projects-modal__hint">
        {settings.keychain_available
          ? `${envName ? `${envName} in the server's environment takes precedence. ` : ""}The key is never shown again.`
          : `This server has no keychain${envName ? `: set ${envName} in its environment instead` : ""}.`}
      </p>
      <ConfirmDialog
        open={confirmRemove}
        title="Remove the API key?"
        description="It is deleted from the server keychain. Drafting stops working until a key is added again."
        confirmLabel="Remove key"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => remove.mutate({ provider }, { onSettled: () => setConfirmRemove(false) })}
        onCancel={() => setConfirmRemove(false)}
      />
    </div>
  );
}
