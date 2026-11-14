import type { ExperimentRun, RunTableRow } from "../../api/mlopsApi";

const PARAM = "param_";
const METRIC = "metric_";

export const isParamColumn = (key: string) => key.startsWith(PARAM);
export const isMetricColumn = (key: string) => key.startsWith(METRIC);

/** A column's header: a hyperparameter or a metric by its own name. */
export function columnLabel(key: string): string {
  if (isParamColumn(key)) return key.slice(PARAM.length);
  if (isMetricColumn(key)) return key.slice(METRIC.length);
  return key;
}

/** The table as CSV (RFC 4180): every column, whatever the screen hides. */
export function runTableToCsv(columns: string[], rows: RunTableRow[]): string {
  const cell = (value: unknown): string => {
    if (value == null) return "";
    const text = String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = [columns.join(",")];
  for (const row of rows) lines.push(columns.map((c) => cell(row[c])).join(","));
  return `${lines.join("\r\n")}\r\n`;
}

/** A table row as the run shape the compare dialog reads: its hyperparameters and
 *  final metrics. Tags and Ducta's own parameters are not in the table. */
export function rowToRun(row: RunTableRow, experimentId = ""): ExperimentRun {
  const parameters: Record<string, unknown> = {};
  const metrics: ExperimentRun["metrics"] = {};
  for (const [key, value] of Object.entries(row)) {
    if (isParamColumn(key) && value != null) parameters[columnLabel(key)] = value;
    if (isMetricColumn(key) && typeof value === "number") {
      metrics[columnLabel(key)] = [{ key: columnLabel(key), value }];
    }
  }
  return {
    run_id: row.run_id,
    experiment_id: experimentId,
    name: row.run_name ?? undefined,
    status: row.status,
    created_at: row.started_at ?? undefined,
    duration_seconds: row.duration_seconds,
    parameters,
    metrics,
    tags: {},
  };
}

/** Save text as a file in the browser. */
export function downloadText(filename: string, text: string, type = "text/csv"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
