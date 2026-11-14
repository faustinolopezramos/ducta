import { useState } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { IconArrowRight, IconCheck, IconLink } from "@tabler/icons-react";
import { aliasFor } from "../../pages/PipelinePage/canvasEdits";

export interface ConnectionModalProps {
  open: boolean;
  onClose: () => void;
  sourceNode: string;
  targetNode: string;
  availableOutputs: string[];
  targetInputs?: string[];
  onConnect: (dataset: string, alias?: string) => void;
  onConnectAll?: (datasets: string[]) => void;
}

export function ConnectionModal({
  open,
  onClose,
  sourceNode,
  targetNode,
  availableOutputs,
  targetInputs = [],
  onConnect,
  onConnectAll,
}: ConnectionModalProps) {
  const [selectedOutput, setSelectedOutput] = useState<string>(availableOutputs[0] ?? "");
  const [alias, setAlias] = useState<string>(() => (availableOutputs[0] ? aliasFor(availableOutputs[0]) : ""));

  const handleSelectOutput = (ds: string) => {
    setSelectedOutput(ds);
    setAlias(aliasFor(ds));
  };

  const handleConnectSingle = () => {
    if (!selectedOutput) return;
    onConnect(selectedOutput, alias.trim() || undefined);
    onClose();
  };

  const handleConnectAll = () => {
    if (onConnectAll) {
      onConnectAll(availableOutputs);
      onClose();
    }
  };

  if (!open) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Connect Nodes"
      width={520}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "16px", padding: "8px 0" }}>
        <p style={{ margin: 0, fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
          Choose which output from <strong>{sourceNode}</strong> connects to <strong>{targetNode}</strong>.
        </p>

        {/* Visual wiring flow preview */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "var(--surface-secondary, rgba(0, 0, 0, 0.03))",
            padding: "10px 14px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            fontSize: "var(--text-xs)",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", textTransform: "uppercase" }}>Source</span>
            <span style={{ fontWeight: 600, color: "var(--text)" }}>{sourceNode}</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--primary)" }}>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                background: "color-mix(in srgb, var(--primary) 10%, transparent)",
                padding: "2px 6px",
                borderRadius: "4px",
              }}
            >
              {selectedOutput || "select output"}
            </span>
            <IconArrowRight size={14} />
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", textTransform: "uppercase" }}>Target</span>
            <span style={{ fontWeight: 600, color: "var(--text)" }}>{targetNode}</span>
            {alias && (
              <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                param: <code>{alias}</code>
              </span>
            )}
          </div>
        </div>

        {/* Output selection list */}
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <label
            htmlFor="connection-output-select"
            style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text)" }}
          >
            Source Output ({availableOutputs.length})
          </label>
          <div
            id="connection-output-select"
            role="radiogroup"
            aria-label="Select source output"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "6px",
              maxHeight: "150px",
              overflowY: "auto",
            }}
          >
            {availableOutputs.map((ds) => {
              const isSelected = ds === selectedOutput;
              return (
                <button
                  key={ds}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  onClick={() => handleSelectOutput(ds)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "8px 12px",
                    borderRadius: "var(--radius-sm)",
                    border: `1px solid ${isSelected ? "var(--primary)" : "var(--border)"}`,
                    background: isSelected
                      ? "color-mix(in srgb, var(--primary) 8%, transparent)"
                      : "var(--surface)",
                    cursor: "pointer",
                    textAlign: "left",
                    color: "var(--text)",
                    fontSize: "var(--text-xs)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  <span>{ds}</span>
                  {isSelected && <IconCheck size={14} style={{ color: "var(--primary)" }} />}
                </button>
              );
            })}
          </div>
        </div>

        {/* Parameter alias input */}
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <label
            htmlFor="connection-alias-input"
            style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text)" }}
          >
            Target Function Parameter Alias
          </label>
          <input
            id="connection-alias-input"
            type="text"
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="e.g. clean_df"
            style={{
              fontFamily: "var(--font-mono)",
              background: "var(--bg)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              padding: "7px 10px",
              fontSize: "var(--text-xs)",
              outline: "none",
            }}
          />
          <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>
            The Python function argument name this dataset will bind to in <code>{targetNode}</code>.
          </span>
        </div>

        {targetInputs.length > 0 && (
          <div style={{ fontSize: "11px", color: "var(--text-dim)" }}>
            Already reading: {targetInputs.join(", ")}
          </div>
        )}

        {/* Action buttons */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: "8px",
            marginTop: "8px",
            paddingTop: "12px",
            borderTop: "1px solid var(--border)",
          }}
        >
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          {availableOutputs.length > 1 && onConnectAll && (
            <Button variant="secondary" size="sm" onClick={handleConnectAll}>
              Connect all ({availableOutputs.length})
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            onClick={handleConnectSingle}
            disabled={!selectedOutput}
            leftIcon={<IconLink size={14} />}
          >
            Connect
          </Button>
        </div>
      </div>
    </Modal>
  );
}
