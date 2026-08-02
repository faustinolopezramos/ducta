import type React from "react";
import {
  IconDatabase,
  IconSettings2,
  IconBrain,
  IconCloud,
  IconTool,
} from "@tabler/icons-react";

interface PipelineNode {
  id: string;
  name?: string;
  type?: string;
  module?: string;
  fn?: string;
  inputs?: { id: string; name: string; format?: string }[];
  outputs?: { id: string; name: string; format?: string }[];
  dependencies?: string[];
  [key: string]: any;
}

interface NodeCardProps {
  node: PipelineNode;
  selected: boolean;
  dimmed: boolean;
  /** Direction of this node relative to the selected one when the lens is active. */
  lensDir?: "up" | "down" | null;
  /** Distance from the selected node (1 = direct). */
  lensDepth?: number;
  execState?: string;
  onClick: () => void;
}

const typeIcons: Record<string, React.ComponentType<any>> = {
  source: IconDatabase,
  transform: IconSettings2,
  ml: IconBrain,
  sink: IconCloud,
  custom: IconTool,
};

export function NodeCard({ node, selected, dimmed, lensDir, lensDepth, execState, onClick }: NodeCardProps) {
  const Icon = typeIcons[node.type ?? ""] ?? IconTool;
  const hasInputs = node.inputs && node.inputs.length > 0;
  const hasOutputs = node.outputs && node.outputs.length > 0;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={
        `Node ${node.name ?? node.id}${execState ? `, ${execState}` : ""}` +
        `, ${node.inputs?.length ?? 0} input(s), ${node.outputs?.length ?? 0} output(s)`
      }
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      className={`node-card ${selected ? "selected" : ""} ${dimmed ? "dag-dimmed" : ""} ${lensDir ? `lens-${lensDir}` : ""} ${execState ? `status-${execState}` : ""}`}
      data-type={node.type}
    >
      {lensDir && lensDepth != null && (
        <span className={`lens-tag lens-tag-${lensDir}`} aria-label={lensDir === "up" ? `Dependency, ${lensDepth} away` : `Consumer, ${lensDepth} away`}>
          {lensDir === "up" ? "↑" : "↓"}{lensDepth}
        </span>
      )}
      <div className="node-card-main">
        <div className="node-card-icon">
          <Icon size={16} stroke={1.5} />
        </div>
        <div className="node-card-info">
          <span className="node-card-name">{node.name || node.id}</span>
          <span className="node-card-type">{node.type}</span>
        </div>
        {/* A status pill would eat most of a 200px card and truncate the node
          * name to nothing — the one thing the canvas has to show. The dot
          * carries status here (with the card's own status tint and border);
          * the spelled-out status lives in NodeDetailSidebar and the label. */}
        {execState && (
          <span className={`node-card-status status-dot-${execState}`} title={execState} />
        )}
      </div>

      {hasInputs && <PortRail ports={node.inputs!} side="in" />}
      {hasOutputs && <PortRail ports={node.outputs!} side="out" />}
    </div>
  );
}

/**
 * Typed connectors on the card's edge — inputs across the top, outputs across
 * the bottom. The offsets match `portOffset` in utils/dagLayout.ts, so an edge
 * lands exactly on its dot.
 */
function PortRail({ ports, side }: { ports: NonNullable<PipelineNode["inputs"]>; side: "in" | "out" }) {
  return (
    <>
      {ports.map((port, i) => (
        <span
          key={port.id ?? `${side}-${i}`}
          className={`node-port node-port-${side}`}
          style={{ left: `${((i + 1) / (ports.length + 1)) * 100}%` }}
          title={`${side === "in" ? "Input" : "Output"}: ${port.name}${port.format ? ` (${port.format})` : ""}`}
          // The counts are already in the card's aria-label; the dots are visual.
          aria-hidden="true"
        >
          <span className="port-dot" />
          {port.format && <span className="port-chip">{port.format}</span>}
        </span>
      ))}
    </>
  );
}
