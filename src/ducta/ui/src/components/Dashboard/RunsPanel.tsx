import { Link } from "react-router-dom";
import { IconCircleCheck } from "@tabler/icons-react";
import type { AttentionItem, RunLike } from "../../utils/dashboardStats";
import { formatRelative } from "../../utils/timeLabels";

/** Rows shown before the rest are left to the History page. */
const MAX_ROWS = 6;

interface RunsPanelProps {
  active: RunLike[];
  attention: AttentionItem[];
  /** Display name for a project id, falling back to the id itself. */
  projectName: (id: string | null | undefined) => string | null;
  loading?: boolean;
}

/**
 * What needs a look: failures first, then what is running. A single plain
 * list under one small label — no panel, no border box. When nothing needs a
 * look, one quiet line says so rather than leaving the section blank, which on
 * first load reads as unfinished rather than as good news.
 */
export function RunsPanel({ active, attention, projectName, loading = false }: RunsPanelProps) {
  if (loading) return null;

  const rows = [
    ...attention.map((item) => ({
      run: item.run,
      meta: [
        item.run.status === "gate_blocked" ? "gate blocked" : "failed",
        formatRelative(item.run.started_at ?? item.run.finished_at),
        item.failures > 1 ? `${item.failures}× in 24h` : null,
      ]
        .filter(Boolean)
        .join(" · "),
    })),
    ...active.map((run) => ({ run, meta: run.status === "pending" ? "queued" : "running" })),
  ].slice(0, MAX_ROWS);

  const overflow = attention.length + active.length - rows.length;

  return (
    <section className="dash-attention-section" aria-labelledby="dash-attention-title">
      <h2 id="dash-attention-title" className="dash-section-title">
        Needs attention
      </h2>

      {rows.length === 0 ? (
        <p className="dash-all-clear">
          <IconCircleCheck size={15} stroke={1.8} aria-hidden="true" />
          Nothing failed or running right now.
        </p>
      ) : (
        <ul className="dash-attention">
          {rows.map(({ run, meta }) => (
            <li key={run.id}>
              <Link
                to={`/workspace/executions?run=${encodeURIComponent(run.id)}`}
                className="dash-attention-row"
                data-status={run.status}
              >
                <span className="dash-dot" aria-hidden="true" />
                <span className="dash-attention-name">
                  {projectName(run.project_id) && (
                    <span className="dash-attention-project">{projectName(run.project_id)} / </span>
                  )}
                  {run.pipeline_name}
                </span>
                <span className="dash-attention-meta">{meta}</span>
              </Link>
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
