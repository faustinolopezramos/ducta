import { Link } from "react-router-dom";
import { IconCircleCheck } from "@tabler/icons-react";
import { isStuckQueued, type AttentionItem, type RunLike } from "../../utils/dashboardStats";
import { formatRelative } from "../../utils/timeLabels";
import { statusMetaFor } from "../ui/statusMeta";
import { routes } from "../../utils/routes";

/** Rows shown before the rest are left to the History page. */
const MAX_ROWS = 6;

interface RunsPanelProps {
  active: RunLike[];
  attention: AttentionItem[];
  /** Display name for a project id, falling back to the id itself. */
  projectName: (id: string | null | undefined) => string | null;
  loading?: boolean;
  /** Cancels a group of runs stuck in the queue; without it the group has no button. */
  onCancelStuck?: (ids: string[]) => void;
}

interface Row {
  key: string;
  run: RunLike;
  meta: string;
  to: string;
  status: string;
  /** Runs this row stands for when it groups a pipeline's stuck queue. */
  stuckIds?: string[];
}

/**
 * What needs a look: failures first, then what is running. A single plain
 * list under one small label — no panel, no border box. When nothing needs a
 * look, one quiet line says so rather than leaving the section blank, which on
 * first load reads as unfinished rather than as good news.
 */
export function RunsPanel({ active, attention, projectName, loading = false, onCancelStuck }: RunsPanelProps) {
  if (loading) return null;

  const historyLink = (run: RunLike) => `/workspace/executions?run=${encodeURIComponent(run.id)}`;

  // Stuck runs of one pipeline read as one problem, not as N identical rows.
  const stuckGroups = new Map<string, RunLike[]>();
  for (const run of active) {
    if (!isStuckQueued(run)) continue;
    const key = `${run.project_id ?? ""}/${run.pipeline_name}`;
    stuckGroups.set(key, [...(stuckGroups.get(key) ?? []), run]);
  }

  const rows: Row[] = [
    ...attention.map((item) => ({
      key: item.run.id,
      run: item.run,
      to: historyLink(item.run),
      status: item.run.status,
      meta: [
        (statusMetaFor(item.run.status)?.label ?? "Failed").toLowerCase(),
        formatRelative(item.run.started_at ?? item.run.finished_at),
        item.failures > 1 ? `${item.failures}× in 24h` : null,
      ]
        .filter(Boolean)
        .join(" · "),
    })),
    ...[...stuckGroups].map(([key, runs]) => {
      const oldest = runs[runs.length - 1];
      const first = runs[0];
      return {
        key: `stuck:${key}`,
        run: first,
        to: first.project_id ? routes.runs(first.project_id, { pipeline: first.pipeline_name }) : historyLink(first),
        status: "stuck",
        meta: `${runs.length > 1 ? `${runs.length} runs ` : ""}stuck in queue · since ${formatRelative(oldest.started_at ?? oldest.finished_at)}`,
        stuckIds: runs.map((r) => r.id),
      };
    }),
    ...active
      .filter((run) => !isStuckQueued(run))
      .map((run) => {
        const since = formatRelative(run.started_at ?? run.finished_at);
        return {
          key: run.id,
          run,
          to: historyLink(run),
          status: run.status,
          meta: run.status === "pending" ? `queued · ${since}` : `running · started ${since}`,
        };
      }),
  ];
  const shown = rows.slice(0, MAX_ROWS);
  const overflow = rows.length - shown.length;

  return (
    <section className="dash-attention-section" aria-labelledby="dash-attention-title">
      <h2 id="dash-attention-title" className="dash-section-title">
        Needs attention
      </h2>

      {shown.length === 0 ? (
        <p className="dash-all-clear">
          <IconCircleCheck size={15} stroke={1.8} aria-hidden="true" />
          Nothing failed or running right now.
        </p>
      ) : (
        <ul className="dash-attention">
          {shown.map(({ key, run, meta, to, status, stuckIds }) => (
            <li key={key} className="dash-attention-item">
              <Link to={to} className="dash-attention-row" data-status={status}>
                <span className="dash-dot" aria-hidden="true" />
                <span className="dash-attention-name">
                  {projectName(run.project_id) && (
                    <span className="dash-attention-project">{projectName(run.project_id)} / </span>
                  )}
                  {run.pipeline_name}
                </span>
                <span className="dash-attention-meta">{meta}</span>
              </Link>
              {stuckIds && onCancelStuck && (
                <button type="button" className="dash-attention-action" onClick={() => onCancelStuck(stuckIds)}>
                  {stuckIds.length > 1 ? "Cancel all" : "Cancel"}
                </button>
              )}
            </li>
          ))}
          {overflow > 0 && (
            <li className="dash-attention-more">
              <Link to="/workspace/executions">{overflow} more in History →</Link>
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
