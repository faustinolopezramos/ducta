import { IconMessageCircle } from "@tabler/icons-react";
import {
  compactDuration,
  humanizeGate,
  medallionLayer,
  qualitySummary,
  type ZoomTier,
} from "../../utils/nodePresentation";
import { formatRate } from "../../utils/streaming";
import type { DagCanvasItem, StreamNodeBadge } from "./types";

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
  /** Enter on the selected card: open it (its code). */
  onOpen?: () => void;
  /** A streaming node while its stream runs: the dot and the fact come from the live query. */
  stream?: StreamNodeBadge;
  /** Design axis — what validation says about the node's configuration and code. */
  design?: "error" | "warning";
  /** Freshness — its code (or something upstream) changed since the last good run. */
  freshness?: "stale" | "never";
  /** Open comment threads on it. */
  comments?: number;
}

const FAILED = new Set(["failed", "error"]);

/** The dot of a live stream node: its query's state, or what deserves a look about it. */
function streamDot(stream: StreamNodeBadge): string {
  if (stream.state === "failed") return "failed";
  if (stream.state !== "active") return stream.state; // skipped · stopped
  return stream.health ?? "active";
}

/** The one fact a live stream node shows: its throughput, or why there is none. */
function streamFact(stream: StreamNodeBadge): string {
  if (stream.state === "failed") return "failed";
  if (stream.state === "skipped") return "skipped";
  if (stream.state !== "active") return "stopped";
  if (stream.health === "stalled") return "stalled";
  if (stream.health === "idle") return "idle";
  return formatRate(stream.rate);
}

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
  onOpen,
  design,
  stream,
  freshness,
  comments = 0,
}: NodeCardProps) {
  const inputs = node.inputs ?? [];
  const outputs = node.outputs ?? [];
  const layer = medallionLayer(outputs.map((o) => o.name));
  const quality = qualitySummary(node.quality);
  const name = node.name || node.id;

  // A live stream query outranks the run's own state: the run is "running" for as long
  // as the stream lives, which says nothing about whether this node is healthy.
  const live = stream ? streamDot(stream) : null;
  const dotState = live ?? execState;
  const failed = live ? live === "failed" : execState ? FAILED.has(execState) : false;
  const fact = stream
    ? streamFact(stream)
    : failed
      ? "failed"
      : execState === "running"
        ? "running"
        : compactDuration(node.lastDuration);

  const label =
    `Node ${name}${dotState ? `, ${stream ? `stream ${dotState}` : dotState}` : ""}` +
    (design ? `, has ${design === "error" ? "errors" : "warnings"}` : "") +
    (freshness === "stale" ? ", stale since its last good run" : "") +
    (comments > 0 ? `, ${comments} open comment${comments === 1 ? "" : "s"}` : "") +
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
        if (e.key === "Enter" && selected && onOpen) {
          e.preventDefault();
          onOpen();
        } else if (e.key === "Enter" || e.key === " ") {
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
        dotState ? `status-${dotState}` : "",
        design ? `design-${design}` : "",
        freshness ? `fresh-${freshness}` : "",
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
          {design && (
            <span className={`node-card-design node-card-design--${design}`} aria-hidden="true" title={design === "error" ? "Has errors — see Problems" : "Has warnings — see Problems"}>
              {design === "error" ? "✕" : "⚠"}
            </span>
          )}
          {freshness === "stale" && tier !== "shape" && (
            <span className="node-card-stale" aria-hidden="true" title="Changed since its last successful run">◐</span>
          )}
          {comments > 0 && tier !== "shape" && (
            <span className="node-card-comments" aria-hidden="true" title={`${comments} open comment${comments === 1 ? "" : "s"}`}>
              <IconMessageCircle size={11} stroke={2} />{comments}
            </span>
          )}
          <span className="node-card-run">
            {dotState && (
              <span
                className={`node-card-status status-dot-${dotState}`}
                title={stream?.error ?? (stream ? `stream ${dotState}` : dotState)}
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
