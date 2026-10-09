import { useNavigate } from "react-router-dom";
import { IconFileCertificate } from "@tabler/icons-react";
import { PageContainer } from "../../components/ui/PageContainer";
import { PageHeader } from "../../components/ui/PageHeader";
import { DataTable } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { useExecutionList } from "../../api/queries";
import { useProjectName } from "../../hooks/useProjects";
import { certificateColumns, type CertificateListItem } from "./certificateColumns";

const FETCH_LIMIT = 200;

/**
 * Every terminating run's proof, in one place. A certificate is 1:1 with the
 * execution that produced it, so this reuses the same execution list the
 * History page draws from (already workspace-wide, already carries
 * `certificate_run_id` + `project_id`) rather than a separate aggregation —
 * filtered down to runs that actually emitted one.
 */
export function CertificatesPage() {
  const navigate = useNavigate();
  const projectName = useProjectName();
  const { data, isLoading, error } = useExecutionList({ limit: FETCH_LIMIT });
  const rows: CertificateListItem[] = (data?.executions ?? []).filter(
    (ex: CertificateListItem) => !!ex.certificate_run_id
  );

  return (
    <PageContainer>
      <PageHeader
        title="Certificates"
        description="The proof artifact every terminating run emits — what ran, against which data, with what result."
      />

      <DataTable<CertificateListItem>
        columns={certificateColumns(projectName)}
        rows={rows}
        rowKey={(ex) => ex.certificate_run_id!}
        minWidth={720}
        stickyHeader
        loading={isLoading}
        error={error ? "Failed to load certificates." : undefined}
        onRowClick={(ex) => navigate(`/workspace/certificates/${ex.project_id ?? "."}/${ex.certificate_run_id}`)}
        rowClassName={(ex) =>
          ex.status === "failed"
            ? "tui-table__row--accent-danger"
            : ex.status === "running"
            ? "tui-table__row--accent-info"
            : undefined
        }
        empty={
          <EmptyState
            icon={IconFileCertificate}
            title="No certificates yet"
            description="Run a pipeline to completion to see its Run Certificate here."
          />
        }
      />
    </PageContainer>
  );
}
