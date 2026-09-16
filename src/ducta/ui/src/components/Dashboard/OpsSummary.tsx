import { Link } from "react-router-dom";
import type { PipelineSchedule } from "../../api/schedulesApi";
import { formatRelative, formatUtc } from "../../utils/timeLabels";

interface OpsSummaryProps {
  activeCount: number;
  failedLast24h: number;
  next: PipelineSchedule | null;
  loading?: boolean;
}

/**
 * The workspace as three numbers, read before anything else on the page. No
 * card, no border box around each — a hairline under the whole row is the only
 * chrome. A number takes colour only when it is worth interrupting someone
 * over: the running count while something is live, the failed count while
 * anything failed today.
 */
export function OpsSummary({ activeCount, failedLast24h, next, loading = false }: OpsSummaryProps) {
  return (
    <dl className="dash-stats" aria-label="Workspace at a glance">
      <div className="dash-stat">
        <dt className="dash-stat-label">
          {activeCount > 0 && <span className="dash-stat-pulse" aria-hidden="true" />}
          Running
        </dt>
        <dd className="dash-stat-value" data-tone={activeCount > 0 ? "active" : undefined}>
          {loading ? "–" : activeCount}
        </dd>
      </div>

      <div className="dash-stat">
        <dt className="dash-stat-label">Failed · 24h</dt>
        <dd className="dash-stat-value" data-tone={!loading && failedLast24h > 0 ? "danger" : undefined}>
          {loading ? "–" : failedLast24h}
        </dd>
      </div>

      <div className="dash-stat">
        <dt className="dash-stat-label">Next run</dt>
        {next ? (
          <dd className="dash-stat-value dash-stat-value--time" title={formatUtc(next.next_run_at)}>
            {formatRelative(next.next_run_at)}
            <span className="dash-stat-sub">{next.pipeline_name}</span>
          </dd>
        ) : (
          <dd className="dash-stat-value dash-stat-value--time">
            <Link to="/workspace/schedules" className="dash-stat-empty">
              none scheduled
            </Link>
          </dd>
        )}
      </div>
    </dl>
  );
}
