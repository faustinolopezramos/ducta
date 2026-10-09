import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";

const NAME = /^[A-Za-z_][\w-]*$/;

/**
 * "Make a template from this node": a name for `templates/nodes/<name>.yaml`
 * and which of the node's keys become parameters. The node keeps its wiring
 * (inputs, outputs) and `use`s the template; nothing else changes meaning.
 */
export function ExtractTemplateDialog({
  node,
  busy,
  error,
  onExtract,
  onCancel,
}: {
  node: string;
  busy?: boolean;
  error?: string | null;
  onExtract: (template: string, params: string[]) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(node.split(".").pop()?.replace(/[^\w-]/g, "_") ?? "");
  const [params, setParams] = useState("");
  const nameError = name && !NAME.test(name) ? "Letters, digits, '_' and '-'" : null;
  const keys = params.split(",").map((k) => k.trim()).filter(Boolean);
  const submit = () => name && !nameError && onExtract(name, keys);
  return (
    <div className="add-node-overlay" role="presentation" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="add-node-form" role="dialog" aria-label="Make a template from this node">
        <div className="add-node-title">Make a template from {node}</div>
        <div className="add-node-fields">
          <Field label="Template name" required error={nameError ?? undefined} help={`Written to templates/nodes/${name || "…"}.yaml`}>
            {/* eslint-disable-next-line jsx-a11y/no-autofocus -- focus belongs in the dialog the user just opened. */}
            <input className="mono-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus onKeyDown={(e) => e.key === "Enter" && submit()} />
          </Field>
          <Field label="Parameters" help="Node keys that differ per use, comma-separated (e.g. run, timeout_seconds) — optional">
            <input className="mono-input" value={params} onChange={(e) => setParams(e.target.value)} placeholder="run" onKeyDown={(e) => e.key === "Enter" && submit()} />
          </Field>
          {error && <p className="add-node-error" role="alert">{error}</p>}
        </div>
        <div className="add-node-actions">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={!name || !!nameError} loading={busy}>Make template</Button>
        </div>
      </div>
    </div>
  );
}
