import type React from "react";
import {
  IconDatabase,
  IconSettings2,
  IconBrain,
  IconCloud,
  IconTool,
  IconShieldHalf,
} from "@tabler/icons-react";
import {
  compactDuration,
  humanizeGate,
  medallionLayer,
  qualitySummary,
  type ZoomTier,
} from "../../utils/nodePresentation";
import type { DagCanvasItem } from "./types";

interface NodeCardProps {
  node: DagCanvasItem;
  selected: boolean;
  dimmed: boolean;
  /** Direction of this node relative to the selected one when the lens is active. */
  lensDir?: "up" | "down" | null;
  /** Distance from the selected node (1 = direct). */
  lensDepth?: number;
  execState?: string;
  /** Semantic-zoom tier: how much of the card is legible at this zoom. */
  tier?: ZoomTier;
  onClick: () => void;
}

const typeIcons: Record<string, React.ComponentType<any>> = {
  source: IconDatabase,
  transform: IconSettings2,
  ml: IconBrain,
  sink: IconCloud,
  custom: IconTool,
};

/**
 * A node on the canvas: a function, and what only a function knows.
 *
 * The datasets are deliberately *not* here — they live on the edges, where they
 * can be clicked and where their real format comes from the registry. That
 * leaves the card lighter than before rather than heavier: an eyebrow, a name,
 * how it is addressed, whether a gate guards what comes after it, and how long
 * it last took.
 */
export function NodeCard({
  node,
  selected,
  dimmed,
  lensDir,
  lensDepth,
  execState,
  tier = "detail",
  onClick,
}: NodeCardProps) {
  const Icon = typeIcons[node.type ?? ""] ?? IconTool;

  const inputs = node.inputs ?? [];
  const outputs = node.outputs ?? [];
  // The layer a node writes into says where it sits in the pipeline, which is a
  // better eyebrow than the inferred node type. Falls back to the type when the
  // datasets follow no medallion convention.
  const layer = medallionLayer(outputs.map((o) => o.name));
  const quality = qualitySummary(node.quality);
  const duration = compactDuration(node.lastDuration);
  const name = node.name || node.id;

  const label =
    `Node ${name}${execState ? `, ${execState}` : ""}` +
    `, reads ${inputs.length}, writes ${outputs.length}` +
    (quality?.gate ? `, gate ${humanizeGate(quality.gate)}` : "");

  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={label}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      className={[
        "node-card",
        `node-card--${tier}`,
        selected ? "selected" : "",
        dimmed ? "dag-dimmed" : "",
        lensDir ? `lens-${lensDir}` : "",
        execState ? `status-${execState}` : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-type={node.type}
      data-layer={layer ?? undefined}
    >
      {/* The layer, as a rule across the top. Carries the same information as
          the eyebrow text, so it still reads at `shape` zoom where text does not. */}
      <span className="node-card-layerbar" aria-hidden="true" />

      {lensDir && lensDepth != null && tier !== "shape" && (
        <span
          className={`lens-tag lens-tag-${lensDir}`}
          aria-label={
            lensDir === "up" ? `Dependency, ${lensDepth} away` : `Consumer, ${lensDepth} away`
          }
        >
          {lensDir === "up" ? "↑" : "↓"}
          {lensDepth}
        </span>
      )}

      <div className="node-card-body">
        {tier !== "shape" && (
          <div className="node-card-head">
            <span className="node-card-eyebrow">
              <Icon size={13} stroke={1.6} className="node-card-eyebrow-icon" />
              {layer ? layer.toUpperCase() : (node.type ?? "node")}
            </span>
            <span className="node-card-run">
              {execState && (
                <span
                  className={`node-card-status status-dot-${execState}`}
                  title={execState}
                  aria-hidden="true"
                />
              )}
              {duration && <span className="node-card-duration">{duration}</span>}
            </span>
          </div>
        )}

        <div className="node-card-title">
          <span className="node-card-name">{name}</span>
          {tier === "shape" && execState && (
            <span
              className={`node-card-status status-dot-${execState}`}
              title={execState}
              aria-hidden="true"
            />
          )}
        </div>

        {tier === "detail" && (node.module || node.fn) && (
          <div className="node-card-fn">
            {[node.module, node.fn].filter(Boolean).join(" · ")}
          </div>
        )}

        {/* A gate decides whether anything downstream runs at all, which is
            worth reading off the graph instead of opening a panel. */}
        {tier !== "shape" && quality && (
          <div className="node-card-foot">
            {quality.gate && (
              <span
                className="node-card-gate"
                title={`Quality gate: ${humanizeGate(quality.gate)}`}
              >
                <IconShieldHalf size={11} stroke={1.8} aria-hidden="true" />
                {tier === "detail" ? `gate · ${humanizeGate(quality.gate)}` : "gate"}
              </span>
            )}
            {tier === "detail" && quality.count > 0 && (
              <span className="node-card-checks">
                {quality.count} {quality.isSanity ? "sanity" : "quality"}{" "}
                {quality.count === 1 ? "check" : "checks"}
              </span>
            )}
          </div>
        )}
      </div>

      {inputs.length > 0 && <PortRail ports={inputs} side="in" />}
      {outputs.length > 0 && <PortRail ports={outputs} side="out" />}
    </div>
  );
}

/**
 * The connectors the edges land on — inputs across the top, outputs across the
 * bottom. Offsets match `portOffset` in utils/dagLayout.ts and the handle
 * positions in DuctaNode; all three have to agree or an edge arrives next to
 * its dot instead of on it.
 */
function PortRail({
  ports,
  side,
}: {
  ports: NonNullable<DagCanvasItem["inputs"]>;
  side: "in" | "out";
}) {
  return (
    <>
      {ports.map((port, i) => (
        <span
          key={port.id ?? `${side}-${i}`}
          className={`node-port node-port-${side}`}
          style={{ left: `${((i + 1) / (ports.length + 1)) * 100}%` }}
          aria-hidden="true"
        >
          <span className="port-dot" />
        </span>
      ))}
    </>
  );
}
