import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";
import { groupKey } from "../../components/Pipeline/canvasGroups";

const NAME = /^[A-Za-z_][\w-]*$/;

/**
 * "Make a subpipeline from these nodes": they move, as they are, into
 * `templates/pipelines/<name>.yaml`, and one `use: pipeline:<name>` node takes
 * their place — the pipeline that runs is the same.
 */
export function ExtractSubpipelineDialog({
  from,
  nodes,
  busy,
  error,
  onExtract,
  onCancel,
}: {
  /** The node it was started from: its namespace's nodes are picked to begin with. */
  from: string;
  /** Every node written in the pipeline. */
  nodes: string[];
  busy?: boolean;
  error?: string | null;
  onExtract: (template: string, nodes: string[]) => void;
  onCancel: () => void;
}) {
  const ns = groupKey(from);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(nodes.filter((n) => (ns ? groupKey(n) === ns : n === from))));
  const [name, setName] = useState((ns ?? from).replace(/[^\w-]/g, "_"));
  const nameError = name && !NAME.test(name) ? "Letters, digits, '_' and '-'" : null;
  const ok = !!name && !nameError && picked.size > 0;
  return (
    <div className="add-node-overlay" role="presentation" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="add-node-form" role="dialog" aria-label="Make a subpipeline">
        <div className="add-node-title">Make a subpipeline</div>
        <div className="add-node-fields">
          <Field label="Name" required error={nameError ?? undefined} help={`Written to templates/pipelines/${name || "…"}.yaml`}>
            <input className="mono-input" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <fieldset className="subpipeline__nodes">
            <legend>Nodes it takes</legend>
            {nodes.map((n) => (
              <label key={n}>
                <input
                  type="checkbox"
                  checked={picked.has(n)}
                  onChange={(e) => {
                    const next = new Set(picked);
                    if (e.target.checked) next.add(n);
                    else next.delete(n);
                    setPicked(next);
                  }}
                />{" "}
                <span className="mono">{n}</span>
              </label>
            ))}
          </fieldset>
          {error && <p className="add-node-error" role="alert">{error}</p>}
        </div>
        <div className="add-node-actions">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" size="sm" disabled={!ok} loading={busy} onClick={() => onExtract(name, nodes.filter((n) => picked.has(n)))}>
            Make subpipeline ({picked.size})
          </Button>
        </div>
      </div>
    </div>
  );
}
