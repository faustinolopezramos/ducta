import type React from "react";
import { useMemo, useState } from "react";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";
import { nodeNameError, runError } from "./canvasEdits";
import type { NodeTemplate } from "../../api/queries";

const addInputStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  background: "var(--bg)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md)",
  padding: "7px 10px",
  fontSize: "var(--text-sm)",
  outline: "none",
  width: "100%",
};

export interface NewNode {
  name: string;
  /** `module:function`; empty for a node configured rather than coded. */
  run: string;
  /** A dataset it reads, if any. */
  reads: string;
  /** A dataset it writes, if any — new ones are added to the catalog. */
  writes: string;
  /** A node template it instantiates (`use:`) instead of running a function. */
  template?: string;
  /** The template's parameters (`with:`). */
  with?: Record<string, string>;
}

/**
 * A new node: its name, the function it runs, and optionally what it reads
 * and writes — enough to draw it connected. Suggestions come from the
 * project: functions no node runs yet, and the catalog.
 */
export function AddNodeForm({
  onAdd,
  onCancel,
  existingNames = [],
  initial,
  functions = [],
  datasets = [],
  templates = [],
  writtenElsewhere,
}: {
  onAdd: (node: NewNode) => void;
  onCancel: () => void;
  /** Every node name in the project: names are unique across pipelines. */
  existingNames?: string[];
  initial?: Partial<NewNode>;
  /** `module:function` of functions no node runs yet. */
  functions?: string[];
  datasets?: string[];
  /** The project's node templates; offered instead of a function. */
  templates?: NodeTemplate[];
  /** The pipeline that writes a dataset, when it is another one than this. */
  writtenElsewhere?: (dataset: string) => string | undefined;
}) {
  const [node, setNode] = useState<NewNode>({ name: "", run: "", reads: "", writes: "", ...initial });
  const template = templates.find((t) => t.name === node.template);
  // A subpipeline brings its own nodes and datasets: the instance has nothing to wire.
  const isSubpipeline = !!node.template?.startsWith("pipeline:");
  const params = template?.params ?? [];
  const values = node.with ?? {};
  const missingParam = params.find((p) => p.required && !values[p.name]?.trim());
  const set = (key: keyof NewNode) => (e: React.ChangeEvent<HTMLInputElement>) => setNode({ ...node, [key]: e.target.value });
  const taken = useMemo(() => new Set(existingNames), [existingNames]);
  const name = node.name.trim();
  const nameError = name ? nodeNameError(name, taken) : null;
  const fnError = template ? null : runError(node.run.trim());
  const canAdd = Boolean(name) && !nameError && !fnError && !missingParam;
  const submit = () =>
    canAdd &&
    onAdd({
      name,
      run: template ? "" : node.run.trim(),
      reads: isSubpipeline ? "" : node.reads.trim(),
      writes: isSubpipeline ? "" : node.writes.trim(),
      ...(template
        ? { template: template.name, with: Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== "")) }
        : {}),
    });
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") submit();
    if (e.key === "Escape") onCancel();
  };
  const newDataset = node.writes.trim() && !datasets.includes(node.writes.trim());

  return (
    <div
      className="add-node-overlay"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="add-node-form" role="dialog" aria-label="Add a node">
        <div className="add-node-title">Add node</div>
        <div className="add-node-fields">
          <Field label="Name" required error={nameError ?? undefined} help="Unique in the project, e.g. silver.clean_orders">
            {/* eslint-disable-next-line jsx-a11y/no-autofocus -- focus belongs in the popover the user just opened. */}
            <input value={node.name} onChange={set("name")} placeholder="silver.clean_orders" autoFocus onKeyDown={keys} style={addInputStyle} />
          </Field>
          {templates.length > 0 && (
            <Field label="From template" help={template?.description ?? "A reusable node from templates/nodes/ — or none, and write the function"}>
              <select
                value={node.template ?? ""}
                onChange={(e) => setNode({ ...node, template: e.target.value || undefined, with: {} })}
                style={addInputStyle}
              >
                <option value="">None — runs a function</option>
                <optgroup label="Node templates">
                  {templates.filter((t) => !t.error && !t.name.startsWith("pipeline:")).map((t) => (
                    <option key={t.name} value={t.name}>{t.name}</option>
                  ))}
                </optgroup>
                {templates.some((t) => t.name.startsWith("pipeline:")) && (
                  <optgroup label="Subpipelines — several nodes">
                    {templates.filter((t) => !t.error && t.name.startsWith("pipeline:")).map((t) => (
                      <option key={t.name} value={t.name}>{t.name.slice("pipeline:".length)}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </Field>
          )}
          {template ? (
            params.map((p) => (
              <Field
                key={p.name}
                label={p.name}
                required={p.required}
                help={p.required ? "Required by the template" : `Default: ${JSON.stringify(p.default)}`}
              >
                <input
                  value={values[p.name] ?? ""}
                  onChange={(e) => setNode({ ...node, with: { ...values, [p.name]: e.target.value } })}
                  onKeyDown={keys}
                  style={addInputStyle}
                />
              </Field>
            ))
          ) : (
            <Field label="Runs" error={fnError ?? undefined} help="module.path:function — leave empty for an ingest node">
              <input value={node.run} onChange={set("run")} placeholder="src.silver:clean_orders" list="add-node-functions" onKeyDown={keys} style={addInputStyle} />
            </Field>
          )}
          {!isSubpipeline && (
            <>
          <Field
            label="Reads"
            help={
              writtenElsewhere?.(node.reads.trim())
                ? `Written by ${writtenElsewhere(node.reads.trim())} — this pipeline will run after it`
                : "A dataset from the catalog (optional)"
            }
          >
            <input value={node.reads} onChange={set("reads")} placeholder="bronze.sales.orders" list="add-node-datasets" onKeyDown={keys} style={addInputStyle} />
          </Field>
          <Field label="Writes" help={newDataset ? "New dataset — it will be added to the catalog" : "A dataset it produces (optional)"}>
            <input value={node.writes} onChange={set("writes")} placeholder="silver.sales.orders_clean" list="add-node-datasets" onKeyDown={keys} style={addInputStyle} />
          </Field>
            </>
          )}
          <datalist id="add-node-functions">
            {functions.map((f) => <option key={f} value={f} />)}
          </datalist>
          <datalist id="add-node-datasets">
            {datasets.map((d) => <option key={d} value={d} />)}
          </datalist>
        </div>
        <div className="add-node-actions">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={!canAdd}>Add node</Button>
        </div>
      </div>
    </div>
  );
}
