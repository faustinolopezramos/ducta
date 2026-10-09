import { useState } from "react";
import { Button } from "../ui/Button";
import { Field } from "../ui/Field";

export interface RunOptions {
  scope: "pipeline" | "selected" | "from" | "until" | "stale";
  node: string | null;
  startDate?: string;
  endDate?: string;
  hyperparams?: Record<string, unknown>;
  sampleRows?: number;
  pauseAfter?: string;
  dryRun: boolean;
}

const SCOPES: { id: RunOptions["scope"]; label: string; needsNode?: boolean }[] = [
  { id: "pipeline", label: "The whole pipeline" },
  { id: "stale", label: "Only what changed since the last good run" },
  { id: "selected", label: "Only one node", needsNode: true },
  { id: "from", label: "From a node, and everything after it", needsNode: true },
  { id: "until", label: "Up to a node, and everything before it", needsNode: true },
];

/**
 * A run, said in full before it starts: what part of the pipeline, over which
 * dates, with which parameters, on a sample or for real, pausing where.
 */
export function RunOptionsDialog({
  pipeline,
  env,
  nodes,
  initialNode,
  onRun,
  onCancel,
}: {
  pipeline: string;
  env: string;
  nodes: string[];
  initialNode?: string | null;
  onRun: (options: RunOptions) => void;
  onCancel: () => void;
}) {
  const [scope, setScope] = useState<RunOptions["scope"]>("pipeline");
  const [node, setNode] = useState<string>(initialNode ?? nodes[0] ?? "");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [params, setParams] = useState("");
  const [sample, setSample] = useState("");
  const [pauseAfter, setPauseAfter] = useState("");
  const [dryRun, setDryRun] = useState(false);

  let paramsError: string | null = null;
  let hyperparams: Record<string, unknown> | undefined;
  if (params.trim()) {
    try {
      const v = JSON.parse(params);
      if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error();
      hyperparams = v;
    } catch {
      paramsError = 'A JSON object, e.g. {"threshold": 0.8}';
    }
  }
  const sampleRows = sample.trim() ? Number(sample) : undefined;
  const sampleError = sampleRows !== undefined && (!Number.isInteger(sampleRows) || sampleRows < 1) ? "A whole number of rows" : null;
  const dateError = startDate && endDate && startDate > endDate ? "The start is after the end" : null;
  const needsNode = SCOPES.find((s) => s.id === scope)?.needsNode;
  const ok = !paramsError && !sampleError && !dateError && (!needsNode || !!node);

  const submit = () =>
    ok &&
    onRun({
      scope,
      node: needsNode ? node : null,
      startDate: startDate || undefined,
      endDate: endDate || undefined,
      hyperparams,
      sampleRows,
      pauseAfter: pauseAfter || undefined,
      dryRun,
    });

  return (
    <div className="add-node-overlay" role="presentation" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="add-node-form run-options" role="dialog" aria-label={`Run ${pipeline} with options`}>
        <div className="add-node-title">Run {pipeline} in {env}</div>
        <div className="add-node-fields">
          <Field label="What to run">
            <select className="mono-input" value={scope} onChange={(e) => setScope(e.target.value as RunOptions["scope"])}>
              {SCOPES.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </Field>
          {needsNode && (
            <Field label="Node">
              <select className="mono-input" value={node} onChange={(e) => setNode(e.target.value)}>
                {nodes.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </Field>
          )}
          <div className="run-options__row">
            <Field label="From date" error={dateError ?? undefined}>
              <input className="mono-input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </Field>
            <Field label="To date">
              <input className="mono-input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </Field>
          </div>
          <Field label="Parameters" help="Hyperparameters for this run, as JSON — optional" error={paramsError ?? undefined}>
            <input className="mono-input" value={params} onChange={(e) => setParams(e.target.value)} placeholder='{"threshold": 0.8}' />
          </Field>
          <div className="run-options__row">
            <Field label="Sample rows" help="Read only this many rows of each input; write to scratch" error={sampleError ?? undefined}>
              <input className="mono-input" inputMode="numeric" value={sample} onChange={(e) => setSample(e.target.value)} placeholder="all" />
            </Field>
            <Field label="Pause after" help="A data breakpoint">
              <select className="mono-input" value={pauseAfter} onChange={(e) => setPauseAfter(e.target.value)}>
                <option value="">—</option>
                {nodes.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </Field>
          </div>
          <label className="run-options__check">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} /> Dry run — plan it, write nothing
          </label>
        </div>
        <div className="add-node-actions">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={!ok}>Run in {env}</Button>
        </div>
      </div>
    </div>
  );
}
