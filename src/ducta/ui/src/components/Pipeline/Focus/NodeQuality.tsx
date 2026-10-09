import { useMemo, useState } from "react";
import { IconFlask, IconPlus, IconTrash } from "@tabler/icons-react";
import { useNodeQuality, useTryChecks, type TriedCheck } from "../../../api/queries";
import { useQualityChecks, useQualitySummary } from "../../../api/qualityApi";
import { apiErrorMessage } from "../../../api/mutations/errors";
import { PermittedButton } from "../../ui/PermittedButton";
import { Sparkline } from "../../ui/Sparkline";
import { paramToText, textToParam } from "./checkParams";
import { FailingRows } from "../../Quality/FailingRows";

/** Checks whose failures are rows that can be shown. */
const ROW_CHECKS = new Set(["null_rate", "range", "duplicates", "prediction_contract", "business_rules"]);

type Draft = { name: string; fields: Record<string, string> }[];

const toDraft = (checks: Record<string, Record<string, unknown> | null> | undefined, catalog: Map<string, any>): Draft =>
  Object.entries(checks ?? {}).map(([name, params]) => ({
    name,
    fields: Object.fromEntries(
      Object.entries(params ?? {}).map(([k, v]) => [k, paramToText(v, catalog.get(name)?.params?.[k])]),
    ),
  }));

/**
 * The node's quality block, edited as checks with typed fields: add one from
 * the catalog, try the draft on the data the node wrote — before saving —
 * then save it into the pipeline file. The score's recent trend sits on top.
 */
export function NodeQuality({
  projectId,
  pipeline,
  node,
  env,
  onSave,
}: {
  projectId: string;
  pipeline: string;
  node: string;
  env: string;
  /** Write the new quality block (the canvas's undoable `set`). */
  onSave?: (quality: Record<string, unknown> | null) => void;
}) {
  const { data, isLoading } = useNodeQuality(projectId, pipeline, node);
  const { data: catalogList } = useQualityChecks();
  const { data: summary } = useQualitySummary(env, pipeline, projectId);
  const tryChecks = useTryChecks(projectId);
  const catalog = useMemo(() => new Map((catalogList ?? []).map((c) => [c.name, c])), [catalogList]);

  const [draft, setDraft] = useState<Draft | null>(null);
  const [adding, setAdding] = useState("");
  const [dataset, setDataset] = useState<string | null>(null);
  const [showing, setShowing] = useState<string | null>(null);
  const current = draft ?? toDraft(data?.quality?.checks ?? undefined, catalog);
  const dirty = draft !== null;
  const target = dataset ?? data?.outputs[0] ?? null;
  const trend = summary?.find((q) => q.dataset === target)?.trend ?? [];

  // Typed values; the first field that does not parse, if any.
  let error: string | null = null;
  const checks: Record<string, Record<string, unknown>> = {};
  for (const c of current) {
    const params: Record<string, unknown> = {};
    for (const [k, text] of Object.entries(c.fields)) {
      try {
        const v = textToParam(text, catalog.get(c.name)?.params?.[k]);
        if (v !== undefined) params[k] = v;
      } catch (e) {
        error ??= `${c.name}.${k} ${(e as Error).message}`;
      }
    }
    checks[c.name] = params;
  }
  const results = new Map<string, TriedCheck>((tryChecks.data?.results ?? []).map((r) => [r.check_name, r]));

  const edit = (next: Draft) => {
    setDraft(next);
    tryChecks.reset();
  };
  const setField = (i: number, k: string, v: string) =>
    edit(current.map((c, j) => (j === i ? { ...c, fields: { ...c.fields, [k]: v } } : c)));

  if (isLoading) return <p className="focus-empty">Loading checks…</p>;
  if (data?.uses_template) {
    return <p className="focus-empty">Its checks come from the template “{data.uses_template}” — edit them there.</p>;
  }

  return (
    <section className="focus-col node-quality" aria-label="Quality checks of this node">
      {trend.length > 0 && (
        <div className="node-quality__trend">
          <span className="focus-col-label">Score, last {trend.length} runs</span>
          <Sparkline
            label={`Quality score trend of ${target}`}
            points={trend.map((s) => ({ seconds: s ?? 0, status: s != null && s >= 1 ? "success" : "failed" }))}
            width={140}
          />
        </div>
      )}
      {current.length === 0 && <p className="focus-empty">No checks yet — add one, try it on the data, save.</p>}
      <ol className="node-quality__list">
        {current.map((c, i) => {
          const spec = catalog.get(c.name);
          const keys = [...new Set([...Object.keys(spec?.params ?? {}), ...Object.keys(c.fields)])];
          const r = results.get(c.name);
          return (
            <li
              key={`${c.name}-${i}`}
              className="node-quality__check"
              data-result={r ? (r.not_tried ? "untried" : r.passed ? "pass" : "fail") : undefined}
            >
              <header className="node-quality__head">
                <span className="mono">{c.name}</span>
                {r && (
                  <span className="node-quality__result" title={r.not_tried ? r.message : undefined}>
                    {r.not_tried ? "— not tried here" : r.passed ? "✓ passes" : "✕ fails"}
                  </span>
                )}
                <button type="button" className="node-quality__remove" aria-label={`Remove ${c.name}`} onClick={() => edit(current.filter((_, j) => j !== i))}>
                  <IconTrash size={13} />
                </button>
              </header>
              {spec?.description && <p className="node-quality__desc">{spec.description}</p>}
              <div className="node-quality__fields">
                {keys.map((k) => (
                  <label key={k} className="node-quality__field" title={spec?.params?.[k]?.description}>
                    <span>{k}</span>
                    {spec?.params?.[k]?.enum ? (
                      <select value={c.fields[k] ?? ""} onChange={(e) => setField(i, k, e.target.value)}>
                        <option value="">—</option>
                        {spec.params[k].enum!.map((v) => (
                          <option key={String(v)} value={String(v)}>{String(v)}</option>
                        ))}
                      </select>
                    ) : (
                      <input value={c.fields[k] ?? ""} onChange={(e) => setField(i, k, e.target.value)} placeholder={String(spec?.params?.[k]?.type ?? "")} />
                    )}
                  </label>
                ))}
              </div>
              {r && r.passed === false && r.message && <p className="node-quality__msg">{r.message}</p>}
              {r && r.passed === false && ROW_CHECKS.has(c.name) && target && (
                showing === c.name ? (
                  <FailingRows projectId={projectId} dataset={target} env={env} check={c.name} params={checks[c.name] ?? {}} />
                ) : (
                  <button type="button" className="node-quality__btn" onClick={() => setShowing(c.name)}>Show failing rows</button>
                )
              )}
              {r?.not_tried && <p className="node-quality__desc">{r.message}</p>}
            </li>
          );
        })}
      </ol>

      <div className="node-quality__add">
        <select value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="Check to add">
          <option value="">Add a check…</option>
          {(catalogList ?? [])
            .filter((c) => !current.some((d) => d.name === c.name))
            .map((c) => (
              <option key={c.name} value={c.name}>{c.name}</option>
            ))}
        </select>
        <button
          type="button"
          className="node-quality__btn"
          disabled={!adding}
          onClick={() => {
            edit([...current, { name: adding, fields: {} }]);
            setAdding("");
          }}
        >
          <IconPlus size={13} aria-hidden="true" /> Add
        </button>
      </div>

      {error && <p className="node-quality__msg" role="alert">{error}</p>}

      <div className="node-tests__actions">
        {(data?.outputs.length ?? 0) > 1 && (
          <select value={target ?? ""} onChange={(e) => setDataset(e.target.value)} aria-label="Dataset to try the checks on">
            {data!.outputs.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        )}
        <PermittedButton
          permission="quality.run"
          variant="secondary"
          size="sm"
          leftIcon={<IconFlask size={13} />}
          disabled={!target || !!error || current.length === 0}
          loading={tryChecks.isPending}
          title={`Run these checks on ${target ?? "the output"} as it is in ${env} — nothing is saved`}
          onClick={() => target && tryChecks.mutate({ dataset: target, env, checks })}
        >
          Try on {env} data
        </PermittedButton>
        {onSave && (
          <PermittedButton
            permission="pipeline.write"
            variant="primary"
            size="sm"
            disabled={!dirty || !!error}
            onClick={() => {
              const block = current.length ? { ...(data?.quality ?? {}), checks } : null;
              onSave(block);
              setDraft(null);
            }}
          >
            Save checks
          </PermittedButton>
        )}
      </div>
      {tryChecks.data && (
        <p className={`node-tests__summary${tryChecks.data.passed ? " is-ok" : " is-bad"}`} role="status">
          {tryChecks.data.passed ? "All checks pass" : `${tryChecks.data.results.filter((r) => r.passed === false).length} failing`} on{" "}
          {tryChecks.data.sampled_rows.toLocaleString()} rows
          {tryChecks.data.total_rows && tryChecks.data.total_rows > tryChecks.data.sampled_rows ? ` of ${tryChecks.data.total_rows.toLocaleString()}` : ""}
        </p>
      )}
      {tryChecks.error && <p className="node-quality__msg" role="alert">{apiErrorMessage(tryChecks.error)}</p>}
    </section>
  );
}
