import { useState } from "react";
import { Link } from "react-router-dom";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import type { ExperimentRun, RunTable, RunTableRow } from "../../api/mlopsApi";
import { formatDate } from "../../utils/formatDate";
import { routes } from "../../utils/routes";
import { CertificateState, RunStatusLabel } from "./RunBits";
import { columnLabel, isMetricColumn, isParamColumn, rowToRun } from "./runTable";
import "./MLOps.css";

const metricText = (value: unknown) =>
  typeof value === "number" ? value.toFixed(4) : value == null ? "—" : String(value);

/** The hyperparameters whose value is not the same in every run: the ones that explain a
 *  difference in the metrics. With fewer than two runs nothing differs, so all are shown. */
function varyingParams(table: RunTable, params: string[]): string[] {
  if (table.rows.length < 2) return params;
  return params.filter(
    (key) => new Set(table.rows.map((row) => JSON.stringify(row[key] ?? null))).size > 1
  );
}

function ModelCell({ row }: Readonly<{ row: RunTableRow }>) {
  if (!row.model_name) return <span>—</span>;
  return (
    <span className="mlops-nowrap" title={row.model_stage ? `Stage: ${row.model_stage}` : undefined}>
      {row.model_name} v{row.model_version}
    </span>
  );
}

function columnsFor({
  table,
  selection,
  onToggle,
  onOpen,
  project,
  params,
}: {
  table: RunTable;
  selection: ReadonlyMap<string, ExperimentRun>;
  onToggle: (row: RunTableRow) => void;
  onOpen: (row: RunTableRow) => void;
  project?: string;
  /** The hyperparameter columns to show. */
  params: string[];
}): DataTableColumn<RunTableRow>[] {
  const present = new Set(table.columns);
  const metrics = table.columns.filter(isMetricColumn);

  const columns: DataTableColumn<RunTableRow>[] = [
    {
      key: "compare",
      header: "",
      headerLabel: "Select for comparison",
      width: "32px",
      cell: (row) => (
        <input
          type="checkbox"
          checked={selection.has(row.run_id)}
          onChange={() => onToggle(row)}
          aria-label={`Select run ${row.run_name ?? row.run_id} for comparison`}
          style={{ cursor: "pointer" }}
        />
      ),
    },
    {
      key: "run_name",
      header: "Run",
      sortable: true,
      sortValue: (row) => row.run_name ?? row.run_id,
      cell: (row) => (
        <button
          type="button"
          className="mlops-run-link mlops-nowrap"
          title="Open run details"
          onClick={() => onOpen(row)}
        >
          {row.run_name ?? row.run_id.slice(0, 8)}
        </button>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      cell: (row) => <RunStatusLabel status={row.status} />,
    },
    {
      key: "started_at",
      header: "Started",
      sortable: true,
      cell: (row) => (
        <span className="mlops-nowrap">{formatDate(row.started_at ?? undefined)}</span>
      ),
    },
  ];

  for (const key of metrics) {
    columns.push({
      key,
      header: columnLabel(key),
      headerLabel: `Metric ${columnLabel(key)}`,
      sortable: true,
      sortValue: (row) => row[key] as number | null | undefined,
      mono: true,
      align: "right",
      cell: (row) => metricText(row[key]),
    });
  }

  for (const key of params) {
    columns.push({
      key,
      header: columnLabel(key),
      headerLabel: `Hyperparameter ${columnLabel(key)}`,
      sortable: true,
      sortValue: (row) => row[key] as string | number | null | undefined,
      mono: true,
      align: "right",
      cell: (row) => (row[key] == null ? "—" : String(row[key])),
    });
  }
  if (present.has("model_name")) {
    columns.push({
      key: "model_name",
      header: "Model",
      sortable: true,
      sortValue: (row) => row.model_name,
      cell: (row) => <ModelCell row={row} />,
    });
  }
  columns.push({
    key: "certificate_ok",
    header: "Certificate",
    sortable: true,
    sortValue: (row) => (row.certificate_id ? (row.certificate_ok ? 2 : 1) : 0),
    cell: (row) =>
      row.certificate_id ? (
        <Link to={routes.certificate(project || ".", row.certificate_id)}>
          <CertificateState id={row.certificate_id} ok={row.certificate_ok} />
        </Link>
      ) : (
        <CertificateState id={null} />
      ),
  });
  return columns;
}

/** Every run of the pipeline in one table: hyperparameters and final metrics side by side,
 *  the model each registered, and whether its certificate is intact. */
export function RunTableView({
  table,
  selection,
  onToggle,
  onOpen,
  project,
}: {
  table: RunTable;
  selection: ReadonlyMap<string, ExperimentRun>;
  onToggle: (run: ExperimentRun) => void;
  onOpen: (row: RunTableRow) => void;
  project?: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const allParams = table.columns.filter(isParamColumn);
  const varying = varyingParams(table, allParams);
  const shown = showAll ? allParams : varying;
  const hidden = allParams.length - shown.length;

  const columns = columnsFor({
    table,
    selection,
    onToggle: (row) => onToggle(rowToRun(row)),
    onOpen,
    project,
    params: shown,
  });
  return (
    <>
      {(hidden > 0 || showAll) && (
        <p className="mlops-runtable-note">
          {showAll
            ? "Showing every hyperparameter. "
            : `Showing the hyperparameters that differ between runs; ${hidden} that are the same in every run are hidden. `}
          <button type="button" className="mlops-run-link" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Only the ones that differ" : "Show all"}
          </button>
        </p>
      )}
      <DataTable<RunTableRow>
        density="compact"
        stickyHeader
        columns={columns}
        rows={table.rows}
        rowKey={(row) => row.run_id}
        empty={<span>No runs found.</span>}
      />
    </>
  );
}
