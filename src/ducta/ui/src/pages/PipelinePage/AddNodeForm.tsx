import type React from "react";
import { useState } from "react";
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

export function AddNodeForm({ onAdd, onCancel }: { onAdd: (name: string, module: string) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [mod, setMod] = useState("");
  const trimmedName = name.trim();
  const trimmedModule = mod.trim();
  const nameError =
    trimmedName && !/^[A-Za-z_][A-Za-z0-9_-]*$/.test(trimmedName)
      ? "Must start with a letter or _, using only letters, numbers, - or _."
      : undefined;
  const canAdd = Boolean(trimmedName && trimmedModule && !nameError);
  return (
    <div className="add-node-overlay" onClick={onCancel}>
      <div className="add-node-form" onClick={(e) => e.stopPropagation()}>
        <div className="add-node-title">Add Node</div>
        <div className="add-node-fields">
          <Field label="Node name" required error={nameError} help="Start with a letter or _, using only letters, numbers, - or _.">
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
