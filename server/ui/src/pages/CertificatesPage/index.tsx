import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconFileCertificate, IconSearch, IconX } from "@tabler/icons-react";
import { PageContainer } from "../../components/ui/PageContainer";
import { PageHeader } from "../../components/ui/PageHeader";
import { DataTable } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { useExecutionList } from "../../api/queries";
import { useProjectList, useProjectName } from "../../hooks/useProjects";
import { FilterMenu } from "../ExecutionHistoryPage/FilterMenu";
import "../ExecutionHistoryPage/FilterBar.css";
import "./CertificateDetail.css";
import { certificateColumns, type CertificateListItem } from "./certificateColumns";

const FETCH_LIMIT = 200;

/**
 * Every terminating run's proof, in one place. A certificate is 1:1 with the
 * execution that produced it, so this reuses the same execution list the
 * History page draws from (already workspace-wide, already carries
 * `certificate_run_id` + `project_id`) rather than a separate aggregation —
 * filtered down to runs that actually emitted one.
 */
export function CertificatesPage({ projectId }: { projectId?: string } = {}) {
  const navigate = useNavigate();
  const projectName = useProjectName();
  const { data, isLoading, error } = useExecutionList({ limit: FETCH_LIMIT });
  const all: CertificateListItem[] = useMemo(
    () => (data?.executions ?? []).filter((ex: CertificateListItem) => !!ex.certificate_run_id),
    [data],
  );
  // Workspace-wide, so it can get long: narrow it by text, project and
  // environment, in the same controls the Runs page uses.
  const { projects } = useProjectList();
  const [q, setQ] = useState("");
  // Under a project (/p/:id/certificates) the list is that project's; the rail
  // led to a workspace-wide page that dropped the project from the breadcrumb.
  const [pickedProject, setProject] = useState<string | undefined>();
  const project = projectId ?? pickedProject;
  const [env, setEnv] = useState<string | undefined>();
  const envs = useMemo(() => [...new Set(all.map((ex) => ex.env).filter(Boolean) as string[])].sort(), [all]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return all.filter(
      (ex) =>
        (!project || ex.project_id === project) &&
        (!env || ex.env === env) &&
        (!needle || `${ex.pipeline_name} ${ex.certificate_run_id} ${ex.id}`.toLowerCase().includes(needle)),
    );
  }, [all, q, project, env]);
  const filtering = Boolean(q || pickedProject || env);

  return (
    <PageContainer>
      <PageHeader
        title="Certificates"
        description={
          projectId
            ? "This project's runs, each with its proof: what ran, against which data, with what result."
            : "The proof artifact every terminating run emits — what ran, against which data, with what result."
        }
      />

      <div className="run-filters" role="search" aria-label="Filter certificates">
        <label className="run-filters__search">
          <IconSearch size={13} aria-hidden="true" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search pipeline or certificate…"
            aria-label="Search certificates"
          />
        </label>
        {!projectId && projects.length > 1 && (
          <FilterMenu
            label="Project"
            options={projects.map((p) => ({ value: p.id, label: p.name }))}
            selected={project ? [project] : []}
            onChange={([p]) => setProject(p)}
          />
        )}
        {envs.length > 0 && (
          <FilterMenu
            label="Environment"
            options={envs.map((e) => ({ value: e, label: e }))}
            selected={env ? [env] : []}
            onChange={([e]) => setEnv(e)}
          />
        )}
        {filtering && (
          <button
            type="button"
            className="run-filters__clear"
            onClick={() => {
              setQ("");
              setProject(undefined);
              setEnv(undefined);
            }}
          >
            <IconX size={12} aria-hidden="true" /> Clear filters
          </button>
        )}
      </div>

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
          filtering ? (
            <EmptyState icon={IconSearch} title="No certificates match" description="Change or clear the filters." />
          ) : (
            <EmptyState
              icon={IconFileCertificate}
              title="No certificates yet"
              description="Run a pipeline to completion to see its Run Certificate here."
            />
          )
        }
      />
    </PageContainer>
  );
}
