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
  /** Ports along the top and bottom (vertical) or down the left and right (horizontal). */
  orientation?: "vertical" | "horizontal";
  /** Show the layer swatch. Off in the strata view, where the band already says it. */
  showLayer?: boolean;
  /** Upstream context from another pipeline of the chain: quieter, still clickable. */
  context?: boolean;
  onClick: () => void;
}

const FAILED = new Set(["failed", "error"]);

/**
 * A node on the canvas, reduced to what you scan a graph for: which function,
 * and how it went.
 *
 * Everything else a node knows — how it is addressed, its checks and gate, the
 * datasets it reads and writes — lives in the focus panel that opens when the
 * card is selected, and the datasets stay on the edges. The card keeps one fact:
 * that the run failed, that it is running, or how long it last took.
 */
export function NodeCard({
  node,
  selected,
  dimmed,
  lensDir,
  lensDepth,
  execState,
  tier = "detail",
  orientation = "vertical",
  showLayer = true,
  context = false,
  onClick,
}: NodeCardProps) {
  const inputs = node.inputs ?? [];
  const outputs = node.outputs ?? [];
  const layer = medallionLayer(outputs.map((o) => o.name));
  const quality = qualitySummary(node.quality);
  const name = node.name || node.id;

  const failed = execState ? FAILED.has(execState) : false;
  const fact = failed
    ? "failed"
    : execState === "running"
      ? "running"
      : compactDuration(node.lastDuration);

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
        context ? "node-card--context" : "",
        lensDir ? `lens-${lensDir}` : "",
        execState ? `status-${execState}` : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-type={node.type}
      data-layer={layer ?? undefined}
      data-orientation={orientation}
    >
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
        <div className="node-card-title">
          {showLayer && layer && tier !== "shape" && (
            <span className="node-card-swatch" aria-hidden="true" />
          )}
          <span className="node-card-name">{name}</span>
          <span className="node-card-run">
            {execState && (
              <span
                className={`node-card-status status-dot-${execState}`}
                title={execState}
                aria-hidden="true"
              />
            )}
            {tier === "detail" && fact && (
              <span className={`node-card-fact${failed ? " node-card-fact--failed" : ""}`}>
                {fact}
              </span>
            )}
          </span>
        </div>
      </div>

      {inputs.length > 0 && <PortRail ports={inputs} side="in" orientation={orientation} />}
      {outputs.length > 0 && <PortRail ports={outputs} side="out" orientation={orientation} />}
    </div>
  );
}

/**
 * The connectors the edges land on — inputs where the flow enters the card,
 * outputs where it leaves. Offsets match `portOffset` in utils/dagLayout.ts and
 * the handle positions in DuctaNode; all three have to agree or an edge arrives
 * next to its dot instead of on it.
 */
function PortRail({
  ports,
  side,
  orientation,
}: {
  ports: NonNullable<DagCanvasItem["inputs"]>;
  side: "in" | "out";
  orientation: "vertical" | "horizontal";
}) {
  const across = orientation === "horizontal" ? "top" : "left";
  return (
    <>
      {ports.map((port, i) => (
        <span
          key={port.id ?? `${side}-${i}`}
          className={`node-port node-port-${side}`}
          style={{ [across]: `${((i + 1) / (ports.length + 1)) * 100}%` }}
          aria-hidden="true"
        >
          <span className="port-dot" />
        </span>
      ))}
    </>
  );
}
