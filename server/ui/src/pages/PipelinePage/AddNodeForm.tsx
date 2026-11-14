import type React from "react";
import { useMemo, useState } from "react";
import { IconPlus, IconX } from "@tabler/icons-react";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";
import { aliasFor, nodeNameError, runError } from "./canvasEdits";
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

export interface InputItem {
  dataset: string;
  alias?: string;
}

export interface NewNode {
  name: string;
  /** `module:function`; empty for a node configured rather than coded. */
  run: string;
  /** A dataset it reads, if any. */
  reads: string;
  /** A dataset it writes, if any — new ones are added to the catalog. */
  writes: string;
  /** Multiple inputs with alias parameter mapping. */
  inputsList?: InputItem[];
  /** Multiple outputs. */
  outputsList?: string[];
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
  const [inputsList, setInputsList] = useState<InputItem[]>(() => {
    if (initial?.inputsList && initial.inputsList.length > 0) {
      return initial.inputsList;
    }
    if (initial?.reads) {
      return [{ dataset: initial.reads, alias: aliasFor(initial.reads) }];
    }
    return [{ dataset: "", alias: "" }];
  });

  const [outputsList, setOutputsList] = useState<string[]>(() => {
    if (initial?.outputsList && initial.outputsList.length > 0) {
      return initial.outputsList;
    }
    if (initial?.writes) {
      return [initial.writes];
    }
    return [""];
  });

  const updateInput = (index: number, field: "dataset" | "alias", val: string) => {
    setInputsList((prev) => {
      const next = [...prev];
      const current = { ...next[index] };
      current[field] = val;
      if (field === "dataset" && !current.alias && val) {
        current.alias = aliasFor(val);
      }
      next[index] = current;
      return next;
    });
  };

  const addInputRow = () => {
    setInputsList((prev) => [...prev, { dataset: "", alias: "" }]);
  };

  const removeInputRow = (index: number) => {
    setInputsList((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : [{ dataset: "", alias: "" }]));
  };

  const updateOutput = (index: number, val: string) => {
    setOutputsList((prev) => {
      const next = [...prev];
      next[index] = val;
      return next;
    });
  };

  const addOutputRow = () => {
    setOutputsList((prev) => [...prev, ""]);
  };

  const removeOutputRow = (index: number) => {
    setOutputsList((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : [""]));
  };

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
  const submit = () => {
    if (!canAdd) return;
    const cleanInputs = inputsList.filter((i) => i.dataset.trim());
    const cleanOutputs = outputsList.filter((o) => o.trim());
    onAdd({
      name,
      run: template ? "" : node.run.trim(),
      reads: isSubpipeline ? "" : (cleanInputs[0]?.dataset ?? node.reads.trim()),
      writes: isSubpipeline ? "" : (cleanOutputs[0] ?? node.writes.trim()),
      inputsList: isSubpipeline ? [] : cleanInputs,
      outputsList: isSubpipeline ? [] : cleanOutputs,
      ...(template
        ? { template: template.name, with: Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== "")) }
        : {}),
    });
  };
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") submit();
    if (e.key === "Escape") onCancel();
  };

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
                label={`Inputs (${inputsList.filter((i) => i.dataset.trim()).length || inputsList.length})`}
                help="Datasets read by this node. Specify parameter alias if it differs from dataset name."
              >
                <div style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
                  {inputsList.map((inp, idx) => {
                    const elsewhere = writtenElsewhere?.(inp.dataset.trim());
                    return (
                      <div key={idx} style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                          <input
                            value={inp.dataset}
                            onChange={(e) => updateInput(idx, "dataset", e.target.value)}
                            placeholder="Dataset (e.g. bronze.orders)"
                            list="add-node-datasets"
                            onKeyDown={keys}
                            style={{ ...addInputStyle, flex: 2 }}
                            aria-label={`Input dataset ${idx + 1}`}
                          />
                          <input
                            value={inp.alias ?? ""}
                            onChange={(e) => updateInput(idx, "alias", e.target.value)}
                            placeholder="param alias"
                            onKeyDown={keys}
                            style={{ ...addInputStyle, flex: 1 }}
                            title="Parameter alias for this input"
                            aria-label={`Input parameter alias ${idx + 1}`}
                          />
                          {inputsList.length > 1 && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => removeInputRow(idx)}
                              aria-label={`Remove input ${idx + 1}`}
                            >
                              <IconX size={14} />
                            </Button>
                          )}
                        </div>
                        {elsewhere && (
                          <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>
                            Written by {elsewhere} (pipeline dependency)
                          </span>
                        )}
                      </div>
                    );
                  })}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={addInputRow}
                    leftIcon={<IconPlus size={12} />}
                    style={{ alignSelf: "flex-start", marginTop: "2px" }}
                  >
                    Add another input
                  </Button>
                </div>
              </Field>

              <Field
                label={`Outputs (${outputsList.filter((o) => o.trim()).length || outputsList.length})`}
                help="Datasets produced by this node. Uncatalogued datasets are automatically registered."
              >
                <div style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
                  {outputsList.map((out, idx) => {
                    const isNew = out.trim() && !datasets.includes(out.trim());
                    return (
                      <div key={idx} style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                          <input
                            value={out}
                            onChange={(e) => updateOutput(idx, e.target.value)}
                            placeholder="Dataset (e.g. silver.clean_data)"
                            list="add-node-datasets"
                            onKeyDown={keys}
                            style={{ ...addInputStyle, flex: 1 }}
                            aria-label={`Output dataset ${idx + 1}`}
                          />
                          {outputsList.length > 1 && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => removeOutputRow(idx)}
                              aria-label={`Remove output ${idx + 1}`}
                            >
                              <IconX size={14} />
                            </Button>
                          )}
                        </div>
                        {isNew && (
                          <span style={{ fontSize: "11px", color: "var(--primary)" }}>
                            New dataset — will be added to the catalog
                          </span>
                        )}
                      </div>
                    );
                  })}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={addOutputRow}
                    leftIcon={<IconPlus size={12} />}
                    style={{ alignSelf: "flex-start", marginTop: "2px" }}
                  >
                    Add another output
                  </Button>
                </div>
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
