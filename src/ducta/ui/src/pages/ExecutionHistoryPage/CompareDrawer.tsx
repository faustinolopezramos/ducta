import type { ReactNode } from "react";
import { colors, styles } from "../../theme/tokens";
import { SlidePanel } from "../../components/ui/SlidePanel";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type { Execution } from "../../types";
import { formatDuration, formatTime } from "./helpers";

type ComparableExecution = Execution & {
  project_id?: string;
  node_name?: string;
};

interface FieldRow {
  label: string;
  render: (ex: ComparableExecution) => ReactNode;
}

const FIELDS: FieldRow[] = [
  { label: "Status", render: (ex) => <StatusBadge status={ex.status} size="sm" /> },
  { label: "Pipeline", render: (ex) => ex.pipeline_name },
  { label: "Node", render: (ex) => ex.node_name ?? "—" },
  { label: "Project", render: (ex) => ex.project_id ?? "—" },
  { label: "Env", render: (ex) => ex.env },
  { label: "Started", render: (ex) => formatTime(ex.started_at) },
  { label: "Finished", render: (ex) => formatTime(ex.finished_at) },
  { label: "Duration", render: (ex) => formatDuration(ex.duration_seconds) },
  { label: "Exit code", render: (ex) => (ex.exit_code != null ? String(ex.exit_code) : "—") },
  { label: "Model version", render: (ex) => ex.model_version ?? "—" },
  {
    label: "Error",
    render: (ex) =>
      ex.error_message ? (
        <span style={{ color: colors.danger, whiteSpace: "pre-wrap" }}>{ex.error_message}</span>
      ) : (
        "—"
      ),
  },
];

/** Side-by-side comparison of 2+ selected executions — a wide SlidePanel
 *  (same component LogsDrawer uses) with one column per execution instead of
 *  the usual one row per record, since that's the shape a comparison needs. */
export function CompareDrawer({
  executions,
  onClose,
}: Readonly<{ executions: ComparableExecution[]; onClose: () => void }>) {
  const width = Math.min(320 + executions.length * 200, 1100);

  return (
    <SlidePanel
      onClose={onClose}
      width={width}
      title={
        <span style={{ ...styles.fontMono, fontSize: 12, fontWeight: 600, color: colors.text }}>
          Compare {executions.length} executions
        </span>
      }
    >
      <div style={{ overflow: "auto", flex: 1 }}>
        <table className="tui-table tui-table--comfortable" style={{ minWidth: "100%" }}>
          <thead>
            <tr>
              <th className="tui-table__th" style={{ width: 140 }}>
                <span className="sr-only">Field</span>
              </th>
              {executions.map((ex) => (
                <th key={ex.id} className="tui-table__th" style={{ fontFamily: "var(--font-mono)" }}>
                  {ex.id.slice(0, 8)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {FIELDS.map((field) => (
              <tr key={field.label} className="tui-table__row">
                <td className="tui-table__td" style={{ fontWeight: 600, color: colors.text }}>
                  {field.label}
                </td>
                {executions.map((ex) => (
                  <td key={ex.id} className="tui-table__td tui-table__td--mono">
                    {field.render(ex)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SlidePanel>
  );
}
