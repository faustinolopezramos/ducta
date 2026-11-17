import "./StreamingStatusPanel.css";
import { IconAlertTriangle, IconCircleCheck, IconCircleX } from "@tabler/icons-react";
import type { StreamPlan, StreamPlanIssue, StreamPlanNode } from "../../api/queries/streamPlan";
import { Checkpoint } from "./StreamNodeDetail";

/** `every 5 seconds · append`: how often a node fires and what it emits. */
export function planFires(node: StreamPlanNode): string {
  return [node.trigger, node.output_mode].filter(Boolean).join(" · ");
}

function Issues({ issues }: { issues: StreamPlanIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <ul className="stream-plan__issues">
      {issues.map((issue, i) => (
        <li key={i} className="stream-plan__issue" data-level={issue.level}>
          {issue.level === "error" ? (
            <IconCircleX size={13} stroke={2} aria-hidden="true" />
          ) : (
            <IconAlertTriangle size={13} stroke={2} aria-hidden="true" />
          )}
          <span>{issue.text}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * What one stream node would do when the stream starts: reads, transform, writes, how often
 * it fires, where it checkpoints, and anything that would stop it. Shown on the node while
 * no stream runs (the live card takes over once it does).
 *
 * `sentence` (default) is the node panel's two mono lines, which fit its short sheet; `grid`
 * is the labelled facts of the Config tab, which has the room.
 */
export function StreamPlanFacts({ node, variant = "sentence" }: { node: StreamPlanNode; variant?: "sentence" | "grid" }) {
  const grid = variant === "grid";
  const facts: [string, string | null][] = [
    ["Reads", node.source],
    ["Transform", node.transform ?? null],
    ["Writes", node.sink],
    ["Fires", planFires(node)],
    ["After", node.after.length ? node.after.join(", ") : null],
    ["Quality", node.quality ?? null],
    ["Quarantine", node.quarantine ?? null],
  ];
  const shown = facts.filter(([, v]) => v);
  const how = [
    node.transform ? `transform ${node.transform}` : null,
    planFires(node),
    node.after.length ? `after ${node.after.join(", ")}` : null,
    node.quality ? node.quality : null,
    node.quarantine ? `quarantine ${node.quarantine}` : null,
  ].filter(Boolean);
  return (
    <div className={`stream-detail stream-plan${grid ? " stream-detail--grid" : ""}`}>
      {grid ? (
        <dl className="stream-facts">
          {shown.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd title={v ?? undefined}>{v}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <>
          <div>
            reads <b>{node.source}</b> · writes <b>{node.sink}</b>
          </div>
          {how.length > 0 && <div>{how.join(" · ")}</div>}
        </>
      )}
      {node.checkpoint && <Checkpoint path={node.checkpoint} grid={grid} short />}
      <Issues issues={node.issues} />
    </div>
  );
}

/**
 * Every node of the plan on one line, ✓ or ✕ with its first problem: what the Start dialog
 * shows when the stream cannot start.
 */
export function StreamPlanList({ plan }: { plan: StreamPlan }) {
  return (
    <div className="stream-plan-list">
      <ul>
        {plan.nodes.map((node) => {
          const errors = node.issues.filter((i) => i.level === "error");
          const warnings = node.issues.filter((i) => i.level === "warning");
          const bad = errors.length > 0;
          return (
            <li key={node.name} className="stream-plan-list__row" data-bad={bad}>
              <span className="stream-plan-list__mark" aria-hidden="true">
                {bad ? <IconCircleX size={15} stroke={2} /> : <IconCircleCheck size={15} stroke={2} />}
              </span>
              <span className="stream-plan-list__body">
                <b>{node.name}</b>
                <span className="stream-plan-list__what">
                  {node.source} → {node.sink}
                </span>
                {errors.map((e, i) => (
                  <span key={`e${i}`} className="stream-plan-list__problem" data-level="error">
                    {e.text}
                  </span>
                ))}
                {warnings.map((w, i) => (
                  <span key={`w${i}`} className="stream-plan-list__problem" data-level="warning">
                    {w.text}
                  </span>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
      <Issues issues={plan.issues} />
    </div>
  );
}
