import { Link } from "react-router-dom";
import { useExecutionList, useProjectMetrics } from "../../../api/queries";
import { useSourceStore } from "../../../store/workspace";
import { Sparkline } from "../../ui/Sparkline";
import type { Execution } from "../../../types";
import { StatusBadge } from "../../ui/StatusBadge";
import { Skeleton } from "../../ui/Skeleton";
import { formatDuration } from "../../../utils/formatDuration";
import { formatRelative } from "../../../utils/timeLabels";
import { routes } from "../../../utils/routes";

/**
 * The node's own runs (run on their own, from the canvas or the editor),
 * newest first, each a link to its run. Whole-pipeline runs are one click away.
 */
export function NodeRuns({
  nodeName,
  projectId,
  pipelineId,
}: {
  nodeName: string;
  projectId?: string;
  pipelineId: string;
}) {
  const { data, isLoading } = useExecutionList({ node_name: nodeName, limit: 15 });
  const runs: Execution[] = data?.executions ?? [];
  const env = useSourceStore((s) => s.activeEnv);
  const { data: metrics } = useProjectMetrics(projectId ?? "", env || "base");
  const trend = metrics?.nodes.find((n) => n.node === nodeName);

  return (
    <section className="focus-col focus-runs" aria-label="Runs of this node">
      {trend && trend.trend.length > 0 && (
        <div className="node-runs__trend">
          <span className="focus-col-label">In pipeline runs, last {trend.trend.length}</span>
          <Sparkline points={trend.trend} label={`${nodeName}: duration of its last ${trend.trend.length} runs`} width={150} />
          <span className="node-runs__stats">
            p50 {trend.p50_seconds != null ? formatDuration(trend.p50_seconds) : "—"} · p95{" "}
            {trend.p95_seconds != null ? formatDuration(trend.p95_seconds) : "—"}
            {trend.failures > 0 ? ` · ${trend.failures} failed` : ""}
          </span>
        </div>
      )}
      <h4 className="focus-col-label">Runs of this node</h4>
      {isLoading ? (
        <Skeleton variant="block" height="96px" />
      ) : runs.length === 0 ? (
        <p className="focus-empty">Never run on its own. “Run node” runs it with its inputs as they are now.</p>
      ) : (
        <ol className="focus-run-list">
          {runs.map((run) => {
            const label = (
              <>
                <StatusBadge status={run.status} size="sm" />
                <span className="focus-run-when">{formatRelative(run.started_at) ?? "—"}</span>
                <span className="focus-run-meta">
                  {run.env}
                  {run.duration_seconds != null ? ` · ${formatDuration(run.duration_seconds)}` : ""}
                </span>
              </>
            );
            return (
              <li key={run.id}>
                {projectId ? (
                  <Link className="focus-run" to={routes.run(projectId, run.id)} title={run.error_message ?? run.id}>
                    {label}
                  </Link>
                ) : (
                  <span className="focus-run">{label}</span>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {projectId && (
        <Link className="focus-run-all" to={`${routes.runs(projectId)}?pipeline=${encodeURIComponent(pipelineId)}`}>
          All runs of {pipelineId} →
        </Link>
      )}
    </section>
  );
}
