import type { Problem } from "../../api/queries/problems";
import { routes } from "../../utils/routes";
import { formatRelative } from "../../utils/timeLabels";
import type { Execution } from "../../types";
import { isStuckQueued, namesCovered, type RunLike } from "../../utils/dashboardStats";

const FAILED = new Set(["failed", "gate_blocked", "timeout", "cancelled"]);

/** One thing that needs attention, and where to go about it. */
export interface Attention {
  key: string;
  tone: "danger" | "warning";
  text: string;
  to: string;
}

/**
 * What needs attention in a project, most urgent first: configuration errors,
 * pipelines whose latest run failed, and pipelines whose code or inputs changed
 * since their last good run.
 */
export function attentionItems(
  projectId: string,
  problems: Problem[],
  runs: (Pick<Execution, "id" | "pipeline_name" | "status" | "started_at"> & Partial<Pick<Execution, "node_name" | "node_names">>)[],
  stale: { node: string; pipeline?: string | null; state: string }[],
  now: number = Date.now(),
): Attention[] {
  const out: Attention[] = [];

  const errors = problems.filter((p) => p.severity === "error");
  if (errors.length > 0) {
    const first = errors[0];
    out.push({
      key: "problems",
      tone: "danger",
      text: errors.length === 1 ? first.message : `${errors.length} configuration errors — ${first.message}`,
      to: first.file ? routes.code(projectId, first.file, first.line ?? undefined) : routes.pipelines(projectId),
    });
  }

  // The latest run of each pipeline (runs come newest first), unless a newer
  // successful run re-ran it — a node run is recorded under the node's name.
  const latest = new Map<string, (typeof runs)[number]>();
  const fixed = new Set<string>();
  const fixedWhenLatest = new Set<string>();
  for (const r of runs) {
    if (!latest.has(r.pipeline_name)) {
      latest.set(r.pipeline_name, r);
      if (fixed.has(r.pipeline_name)) fixedWhenLatest.add(r.pipeline_name);
    }
    if (r.status === "success") for (const name of namesCovered(r)) fixed.add(name);
  }
  for (const r of latest.values()) {
    if (!FAILED.has(String(r.status)) || fixedWhenLatest.has(r.pipeline_name)) continue;
    out.push({
      key: `run:${r.id}`,
      tone: "danger",
      text: `${r.pipeline_name} ${r.status === "gate_blocked" ? "was blocked by a quality gate" : String(r.status)} ${formatRelative(r.started_at) ?? ""}`.trim(),
      to: routes.run(projectId, r.id),
    });
  }

  // Runs wedged in the queue, one line per pipeline: they never start on their own.
  const stuckByPipeline = new Map<string, number>();
  for (const r of runs) if (isStuckQueued(r as RunLike, now)) stuckByPipeline.set(r.pipeline_name, (stuckByPipeline.get(r.pipeline_name) ?? 0) + 1);
  for (const [pipeline, count] of stuckByPipeline) {
    out.push({
      key: `stuck:${pipeline}`,
      tone: "warning",
      text: `${count} run${count === 1 ? "" : "s"} of ${pipeline} stuck in the queue`,
      to: routes.runs(projectId, { pipeline }),
    });
  }

  const staleByPipeline = new Map<string, number>();
  for (const n of stale) if (n.state === "stale" && n.pipeline) staleByPipeline.set(n.pipeline, (staleByPipeline.get(n.pipeline) ?? 0) + 1);
  for (const [pipeline, count] of staleByPipeline) {
    out.push({
      key: `stale:${pipeline}`,
      tone: "warning",
      text: `${pipeline}: ${count} node${count === 1 ? "" : "s"} changed since the last good run`,
      to: routes.pipeline(projectId, pipeline),
    });
  }
  return out;
}
