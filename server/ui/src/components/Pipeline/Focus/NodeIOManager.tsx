import { useState, useId } from "react";
import { IconPlus, IconX, IconCheck } from "@tabler/icons-react";
import { Button } from "../../ui/Button";
import { DatasetRef, type DatasetRefItem } from "./parts";
import { aliasFor } from "../../../pages/PipelinePage/canvasEdits";

interface NodeInputsSectionProps {
  inputs: DatasetRefItem[];
  onSelectDataset: (name: string) => void;
  onDisconnect?: (dataset: string) => void;
  onAddInput?: (dataset: string, alias?: string) => void;
  availableDatasets?: string[];
  disabled?: boolean;
}

export function NodeInputsSection({
  inputs,
  onSelectDataset,
  onDisconnect,
  onAddInput,
  availableDatasets = [],
  disabled = false,
}: NodeInputsSectionProps) {
  const [isAdding, setIsAdding] = useState(false);
  const [selectedDs, setSelectedDs] = useState("");
  const [alias, setAlias] = useState("");
  const datalistId = useId();

  const handleSelectDs = (val: string) => {
    setSelectedDs(val);
    if (!alias) {
      setAlias(aliasFor(val));
    }
  };

  const handleAdd = () => {
    const ds = selectedDs.trim();
    if (!ds || !onAddInput) return;
    onAddInput(ds, alias.trim() || undefined);
    setSelectedDs("");
    setAlias("");
    setIsAdding(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAdd();
    }
    if (e.key === "Escape") {
      setIsAdding(false);
    }
  };

  const readNames = new Set(inputs.map((i) => i.name));
  const suggestions = availableDatasets.filter((d) => !readNames.has(d));

  return (
    <section className="focus-col focus-col--in node-io-section">
      <div className="node-io-header">
        <h4 className="focus-col-label">
          Reads
          {inputs.length > 0 && (
            <span className="inspector-section-count">{inputs.length}</span>
          )}
        </h4>
        {onAddInput && !disabled && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsAdding(!isAdding)}
            leftIcon={<IconPlus size={12} />}
            aria-label="Add input dataset"
          >
            Add
          </Button>
        )}
      </div>

      {isAdding && (
        <div className="node-io-add-form" role="region" aria-label="Add input">
          <input
            type="text"
            className="node-io-input"
            placeholder="Dataset name..."
            value={selectedDs}
            onChange={(e) => handleSelectDs(e.target.value)}
            onKeyDown={handleKeyDown}
            list={datalistId}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
          />
          <datalist id={datalistId}>
            {suggestions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>

          <input
            type="text"
            className="node-io-input"
            placeholder="Parameter alias (optional)..."
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            onKeyDown={handleKeyDown}
            title="The Python function parameter name this dataset is passed to"
          />

          <div className="node-io-add-actions">
            <Button
              variant="primary"
              size="sm"
              disabled={!selectedDs.trim()}
              onClick={handleAdd}
              leftIcon={<IconCheck size={12} />}
            >
              Connect
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setIsAdding(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="focus-col-items">
        {inputs.length > 0 ? (
          inputs.map((io) => (
            <div key={io.id ?? io.name} className="focus-io-editable">
              <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
                <DatasetRef item={io} onSelect={onSelectDataset} />
                {io.alias && (
                  <span
                    style={{
                      fontSize: "10px",
                      color: "var(--text-dim)",
                      fontFamily: "var(--font-mono)",
                      paddingLeft: "16px",
                      marginTop: "-2px",
                      marginBottom: "2px",
                    }}
                  >
                    param: <code>{io.alias}</code>
                  </span>
                )}
              </div>
              {onDisconnect && !disabled && (
                <button
                  type="button"
                  className="focus-io-remove"
                  aria-label={`Stop reading ${io.name}`}
                  title={`Stop reading ${io.name} (undoable)`}
                  onClick={() => onDisconnect(io.name)}
                >
                  <IconX size={12} />
                </button>
              )}
            </div>
          ))
        ) : (
          <p className="focus-empty">No inputs declared.</p>
        )}
      </div>
    </section>
  );
}

interface NodeOutputsSectionProps {
  outputs: DatasetRefItem[];
  onSelectDataset: (name: string) => void;
  onRemoveOutput?: (dataset: string) => void;
  onAddOutput?: (dataset: string, meta?: Record<string, unknown>) => void;
  nodeName: string;
  disabled?: boolean;
}

export function NodeOutputsSection({
  outputs,
  onSelectDataset,
  onRemoveOutput,
  onAddOutput,
  nodeName,
  disabled = false,
}: NodeOutputsSectionProps) {
  const [isAdding, setIsAdding] = useState(false);
  const [newDsName, setNewDsName] = useState("");
  const [format, setFormat] = useState("parquet");

  const handleOpenAdd = () => {
    if (!newDsName) {
      const base = nodeName.replace(/[^A-Za-z0-9_.]/g, "_");
      setNewDsName(`silver.${base}`);
    }
    setIsAdding(true);
  };

  const handleAdd = () => {
    const ds = newDsName.trim();
    if (!ds || !onAddOutput) return;
    onAddOutput(ds, { format });
    setNewDsName("");
    setIsAdding(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAdd();
    }
    if (e.key === "Escape") {
      setIsAdding(false);
    }
  };

  return (
    <section className="focus-col focus-col--out node-io-section">
      <div className="node-io-header">
        <h4 className="focus-col-label">
          Writes
          {outputs.length > 0 && (
            <span className="inspector-section-count">{outputs.length}</span>
          )}
        </h4>
        {onAddOutput && !disabled && (
          <Button
            variant="ghost"
            size="sm"
            onClick={isAdding ? () => setIsAdding(false) : handleOpenAdd}
            leftIcon={<IconPlus size={12} />}
            aria-label="Add output dataset"
          >
            Add
          </Button>
        )}
      </div>

      {isAdding && (
        <div className="node-io-add-form" role="region" aria-label="Add output">
          <input
            type="text"
            className="node-io-input"
            placeholder="Dataset name (e.g. silver.clean_data)..."
            value={newDsName}
            onChange={(e) => setNewDsName(e.target.value)}
            onKeyDown={handleKeyDown}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
          />

          <select
            className="node-io-input"
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            aria-label="Dataset format"
          >
            <option value="parquet">Parquet</option>
            <option value="delta">Delta Table</option>
            <option value="csv">CSV</option>
            <option value="duckdb">DuckDB</option>
            <option value="jsonl">JSON Lines</option>
          </select>

          <div className="node-io-add-actions">
            <Button
              variant="primary"
              size="sm"
              disabled={!newDsName.trim()}
              onClick={handleAdd}
              leftIcon={<IconCheck size={12} />}
            >
              Add Output
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setIsAdding(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="focus-col-items">
        {outputs.length > 0 ? (
          outputs.map((io) => (
            <div key={io.id ?? io.name} className="focus-io-editable">
              <DatasetRef item={io} onSelect={onSelectDataset} />
              {onRemoveOutput && !disabled && (
                <button
                  type="button"
                  className="focus-io-remove"
                  aria-label={`Remove output ${io.name}`}
                  title={`Remove output ${io.name} (undoable)`}
                  onClick={() => onRemoveOutput(io.name)}
                >
                  <IconX size={12} />
                </button>
              )}
            </div>
          ))
        ) : (
          <p className="focus-empty">No outputs declared.</p>
        )}
      </div>
    </section>
  );
}
