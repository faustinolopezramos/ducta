import type React from "react";
import { useMemo, useState } from "react";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";

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

export function AddNodeForm({
  onAdd,
  onCancel,
  existingNames = [],
}: {
  onAdd: (name: string, module: string) => void;
  onCancel: () => void;
  /** Node names already registered anywhere in the workspace (node identity
   *  is global, not per-pipeline/project) — used to catch a typo that would
   *  otherwise silently overwrite an unrelated existing node via the same
   *  upsert endpoint, instead of creating a new one. */
  existingNames?: string[];
}) {
  const [name, setName] = useState("");
  const [mod, setMod] = useState("");
  const trimmedName = name.trim();
  const trimmedModule = mod.trim();
  const duplicate = useMemo(
    () => new Set(existingNames).has(trimmedName),
    [existingNames, trimmedName]
  );
  const nameError =
    trimmedName && !/^[A-Za-z_][A-Za-z0-9_-]*$/.test(trimmedName)
      ? "Must start with a letter or _, using only letters, numbers, - or _."
      : duplicate
        ? `A node named "${trimmedName}" already exists.`
        : undefined;
  const canAdd = Boolean(trimmedName && trimmedModule && !nameError);
  return (
    <div
      className="add-node-overlay"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="add-node-form">
        <div className="add-node-title">Add Node</div>
        <div className="add-node-fields">
          <Field label="Node name" required error={nameError} help="Start with a letter or _, using only letters, numbers, - or _.">
            {/* eslint-disable-next-line jsx-a11y/no-autofocus -- focus belongs in the popover the user just opened. */}
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="extract" autoFocus
              onKeyDown={(e) => { if (e.key === "Enter" && canAdd) onAdd(trimmedName, trimmedModule); if (e.key === "Escape") onCancel(); }}
              style={addInputStyle} />
          </Field>
          <Field label="Module path" required help="Python module path (e.g., nodes.extract).">
            <input value={mod} onChange={(e) => setMod(e.target.value)} placeholder="nodes.extract"
              onKeyDown={(e) => { if (e.key === "Enter" && canAdd) onAdd(trimmedName, trimmedModule); if (e.key === "Escape") onCancel(); }}
              style={addInputStyle} />
          </Field>
        </div>
        <div className="add-node-actions">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={() => onAdd(trimmedName, trimmedModule)} disabled={!canAdd}>Add Node</Button>
        </div>
      </div>
    </div>
  );
}
