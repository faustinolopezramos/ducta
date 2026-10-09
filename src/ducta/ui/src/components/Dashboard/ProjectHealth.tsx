import { Link } from "react-router-dom";
import { useProjectMetrics } from "../../api/queries";
import { Skeleton, Sparkline, StatusBadge } from "../ui";
import { formatDuration } from "../../utils/formatDuration";
import { formatRelative } from "../../utils/timeLabels";
import { routes } from "../../utils/routes";

const FRESHNESS: Record<string, { label: string; tone: string }> = {
  ok: { label: "fresh", tone: "ok" },
  late: { label: "late", tone: "bad" },
  no_sla: { label: "no SLA", tone: "muted" },
  unknown: { label: "SLA unreadable", tone: "warn" },
};

/**
 * Each pipeline at a glance over the last 30 days: how often it succeeds, how
 * long it takes (p50/p95, and the trend), and whether it is as fresh as its
 * `metadata.sla` asks.
 */
export function ProjectHealth({ projectId, env }: { projectId: string; env: string }) {
  const { data, isLoading } = useProjectMetrics(projectId, env);
  if (isLoading) return <Skeleton variant="block" height="120px" />;
  if (!data || data.pipelines.length === 0) return null;
  return (
    <section className="project-health" aria-label={`Pipeline health in ${env}`}>
      <h2 className="project-health__h">Last {data.days} days in {env}</h2>
      <table className="project-health__table">
        <thead>
          <tr>
            <th scope="col">Pipeline</th>
            <th scope="col">Last run</th>
            <th scope="col">Success</th>
            <th scope="col">p50 / p95</th>
            <th scope="col">Trend</th>
            <th scope="col">Freshness</th>
          </tr>
        </thead>
        <tbody>
          {data.pipelines.map((p) => {
            const f = FRESHNESS[p.freshness] ?? FRESHNESS.unknown;
            return (
              <tr key={p.pipeline}>
                <th scope="row"><Link to={routes.pipeline(projectId, p.pipeline)} className="mono">{p.pipeline}</Link></th>
                <td>{p.last_status ? <><StatusBadge status={p.last_status} size="sm" variant="dot" /> {formatRelative(p.last_run_at)}</> : "never"}</td>
                <td>{p.success_rate != null ? `${Math.round(p.success_rate * 100)}% of ${p.runs}` : "—"}</td>
                <td className="mono">{p.p50_seconds != null ? `${formatDuration(p.p50_seconds)} / ${formatDuration(p.p95_seconds ?? 0)}` : "—"}</td>
                <td><Sparkline points={p.trend} label={`${p.pipeline}: last ${p.trend.length} runs`} /></td>
                <td>
                  <span className={`project-health__fresh tone-${f.tone}`} title={p.sla ? `SLA: ${p.sla}` : "Set metadata.sla on the pipeline"}>
                    {f.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
