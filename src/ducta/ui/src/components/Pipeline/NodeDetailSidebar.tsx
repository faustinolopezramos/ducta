import type React from "react";
import { IconX, IconEdit, IconPlayerPlay } from "@tabler/icons-react";
import { useNodeCode } from "../../api/queries";
import { Button, StatusBadge } from "../ui";

interface PipelineNode {
  id: string;
  name?: string;
  type?: string;
  module?: string;
  fn?: string;
  inputs?: { id: string; name: string; format?: string }[];
  outputs?: { id: string; name: string; format?: string }[];
}

export interface LineageEntry {
  id: string;
  name: string;
  depth: number;
}

interface NodeDetailSidebarProps {
  node: PipelineNode;
  projectId: string;
  pipelineId: string;
  activeEnv: string;
  runningNodeId: string | null;
  lineage?: { upstream: LineageEntry[]; downstream: LineageEntry[] } | null;
  onSelectNode?: (id: string) => void;
  onClose: () => void;
  onRunNode: (node: PipelineNode) => void;
  onEditCode: (code: string) => void;
}

const sectionLabel: React.CSSProperties = {
  fontSize: "var(--text-xs)",
  fontWeight: "var(--weight-semibold)",
  color: "var(--text-muted)",
  textTransform: "uppercase",
  letterSpacing: "var(--tracking-wider)",
  margin: "0 0 var(--space-2) 0",
};

const ioCard: React.CSSProperties = {
  padding: "var(--space-2) var(--space-3)",
  backgroundColor: "var(--surface)",
  borderRadius: "var(--radius-sm)",
  fontSize: "var(--text-sm)",
  border: "1px solid var(--border)",
};

function IoList({ label, items }: { label: string; items: NonNullable<PipelineNode["inputs"]> }) {
  return (
    <section>
      <p style={sectionLabel}>
        {label} ({items.length})
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        {items.map((it) => (
          <div key={it.id} style={ioCard}>
            <div style={{ fontWeight: "var(--weight-medium)", color: "var(--text)" }}>{it.name}</div>
            {it.format && (
              <div style={{ color: "var(--text-muted)", fontSize: "var(--text-xs)", fontFamily: "var(--font-mono)" }}>
                {it.format}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function LineageRows({
  entries,
  dir,
  onSelectNode,
}: {
  entries: LineageEntry[];
  dir: "up" | "down";
  onSelectNode?: (id: string) => void;
}) {
  return (
    <div className="lineage-list">
      {entries.map((entry) => (
        <button
          key={entry.id}
          className="lineage-row"
          onClick={() => onSelectNode?.(entry.id)}
          title={dir === "up" ? "Dependency — click to select" : "Consumer — click to select"}
        >
          <span className={`lineage-dot lineage-dot-${dir}`} />
          <span className="lineage-name">{entry.name}</span>
          <span className={`lineage-depth lineage-depth-${dir}`}>
            {dir === "up" ? "↑" : "↓"}{entry.depth}
          </span>
        </button>
      ))}
    </div>
  );
}

export function NodeDetailSidebar({
  node,
  runningNodeId,
  lineage,
  onSelectNode,
  onClose,
  onRunNode,
  onEditCode,
}: NodeDetailSidebarProps) {
  const { data: nodeCodeData } = useNodeCode(node.id);
  const isRunningThis = runningNodeId === node.id;

  return (
      <aside
        aria-label={`Node detail: ${node.name || node.id}`}
        className="node-detail-panel"
        data-no-pan
      >
        <header className="node-detail-header">
          <div className="node-detail-title-group">
            <h3 className="node-detail-title">{node.name || node.id}</h3>
            <p className="node-detail-id">{node.id}</p>
          </div>
          <button className="node-detail-close" onClick={onClose} aria-label="Close panel">
            <IconX size={16} />
          </button>
        </header>

        <div className="node-detail-body">
          <section>
            <p style={sectionLabel}>Details</p>
            <dl className="node-detail-grid">
              <dt>Type</dt>
              <dd><StatusBadge status="idle" size="sm" label={node.type || "\u2014"} variant="subtle" /></dd>
              <dt>Module</dt>
              <dd className="node-detail-mono">{node.module || "\u2014"}</dd>
              <dt>Function</dt>
              <dd className="node-detail-mono">{node.fn || "\u2014"}</dd>
            </dl>
          </section>

          {lineage && (lineage.upstream.length > 0 || lineage.downstream.length > 0) && (
            <section>
              <p style={sectionLabel}>
                Lineage · {lineage.upstream.length} upstream / {lineage.downstream.length} downstream
              </p>
              {lineage.upstream.length > 0 && (
                <LineageRows entries={lineage.upstream} dir="up" onSelectNode={onSelectNode} />
              )}
              {lineage.downstream.length > 0 && (
                <LineageRows entries={lineage.downstream} dir="down" onSelectNode={onSelectNode} />
              )}
            </section>
          )}

          {node.inputs && node.inputs.length > 0 && <IoList label="Inputs" items={node.inputs} />}
          {node.outputs && node.outputs.length > 0 && <IoList label="Outputs" items={node.outputs} />}

          <div className="node-detail-actions">
            {nodeCodeData?.code && (
              <Button variant="secondary" fullWidth onClick={() => onEditCode(nodeCodeData.code)} leftIcon={<IconEdit size={15} />}>
                Edit Code
              </Button>
            )}
            <Button
              variant="primary"
              fullWidth
              disabled={isRunningThis}
              loading={isRunningThis}
              onClick={() => onRunNode(node)}
              leftIcon={<IconPlayerPlay size={15} />}
            >
              {isRunningThis ? "Running\u2026" : "Run Node"}
            </Button>
          </div>
        </div>
      </aside>
  );
}
