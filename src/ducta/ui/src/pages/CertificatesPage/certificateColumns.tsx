import type { DataTableColumn } from "../../components/ui/DataTable";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { formatDuration, formatTime } from "../ExecutionHistoryPage/helpers";
import type { Execution } from "../../types/execution";

export type CertificateListItem = Execution & { project_id?: string };

export const certificateColumns: DataTableColumn<CertificateListItem>[] = [
  {
    key: "status",
    header: "Status",
    sortable: true,
    cell: (ex) => <StatusBadge status={ex.status} size="sm" />,
  },
  { key: "pipeline_name", header: "Pipeline", mono: true, sortable: true },
  { key: "project_id", header: "Project", mono: true, sortable: true, cell: (ex) => ex.project_id ?? "—" },
  { key: "env", header: "Env", mono: true, sortable: true },
  { key: "started_at", header: "Started", mono: true, sortable: true, cell: (ex) => formatTime(ex.started_at) },
  {
    key: "duration_seconds",
    header: "Duration",
    align: "right",
    mono: true,
    sortable: true,
    cell: (ex) => formatDuration(ex.duration_seconds),
  },
  {
    key: "certificate_run_id",
    header: "Certificate",
    mono: true,
    cell: (ex) => (ex.certificate_run_id ? ex.certificate_run_id.slice(0, 8) : "—"),
  },
];
