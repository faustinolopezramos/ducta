import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { PageContainer } from "../../components/ui/PageContainer";
import type { SectionHeader } from "../../components/App/SectionTabs";
import { useExecutionList, type ExecutionListFilters } from "../../api/queries";
import { useBulkCancelExecutions } from "../../api/mutations";
import type { Execution } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { IconPlayerStop, IconClockHour4, IconSearch, IconArrowsLeftRight } from "@tabler/icons-react";
import { CertificateModal } from "../../components/Execution/CertificateModal";
import { QueueIndicator } from "./QueueIndicator";
import { FilterBar } from "./FilterBar";
import { useProjectName } from "../../hooks/useProjects";
import { LogsDrawer } from "./LogsDrawer";
import { CompareDrawer } from "./CompareDrawer";
import { PipelineHealthStrip } from "./PipelineHealthStrip";
import { DataTable } from "../../components/ui/DataTable";
import {
  executionColumns,
  isActiveExecution,
  computeSweepStats,
  ExecutionRowDetail,
  type ExecutionListItem,
} from "./executionColumns";

// ─────────────────────────────────────────────
// EXECUTION HISTORY PAGE — /workspace/executions
// ─────────────────────────────────────────────

const PAGE_SIZE = 50;

/** `projectId`: under a project, its runs — the filter starts there and stays editable. */
export function ExecutionHistoryPage({ projectId, header }: { projectId?: string; header?: SectionHeader } = {}) {
  const projectName = useProjectName();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("run");
  const selectExecution = (id: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (id) next.set("run", id);
    else next.delete("run");
    setSearchParams(next, { replace: true });
  };

  // `?pipeline=` — linked from a pipeline or a node — narrows to that pipeline.
  const [filters, setFilters] = useState<ExecutionListFilters>(() => ({
    ...(projectId ? { project_id: projectId } : {}),
    ...(searchParams.get("pipeline") ? { pipeline_name: searchParams.get("pipeline")! } : {}),
  }));
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(() => new Set());
  const [certModal, setCertModal] = useState<{ projectId: string; runId: string } | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[] | null>(null);

  // A new filter/search invalidates whatever page depth was reached before —
  // start the incremental load over rather than asking for e.g. 200 rows of
  // a now-different result set. Adjusted during render (not in an effect):
  // the recommended way to reset state in response to a prop/state change.
  const [prevFilters, setPrevFilters] = useState(filters);
  if (prevFilters !== filters) {
    setPrevFilters(filters);
    setLimit(PAGE_SIZE);
  }

  const { data, isLoading, error } = useExecutionList({ ...filters, limit });
  const executions: (Execution & { project_id?: string; node_name?: string })[] =
    data?.executions ?? [];
  const total = data?.total ?? executions.length;
  const { mutate: bulkCancel, isPending: isBulkCancelling } = useBulkCancelExecutions();

  const hasFilters = Object.values(filters).some((v) => v);
  const sweepStats = computeSweepStats(executions);

  // Derive unique pipeline names for the filter dropdown
  const pipelineNames = Array.from(
    new Set(executions.map((e) => e.pipeline_name).filter(Boolean))
  ).sort();

  // Any execution can be checked (comparison works across statuses); only
  // the active subset is what bulk-cancel actually applies to.
  const checkedActive = executions
    .filter((e) => isActiveExecution(e) && checkedIds.has(e.id))
    .map((e) => e.id);

  const handleBulkCancel = () => {
    if (checkedActive.length === 0) return;
    bulkCancel(checkedActive, { onSuccess: () => setCheckedIds(new Set()) });
  };

  return (
    <PageContainer>
      <PageHeader
        title={header?.title ?? (projectId ? "Runs" : "All runs")}
        description={header?.description ?? (projectId ? undefined : "Every project's runs. Click a row for its logs.")}
        actions={<QueueIndicator />}
        tabs={header?.tabs}
      />

      <FilterBar
        filters={filters}
        onChange={setFilters}
        pipelines={pipelineNames}
        lockedProject={projectId}
      />

      {filters.pipeline_name && (
        <PipelineHealthStrip pipelineName={filters.pipeline_name} executions={executions} />
      )}

      {checkedIds.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Bulk actions">
          <span className="bulk-bar__count">{checkedIds.size} selected</span>
          {checkedActive.length > 0 && (
            <Button
              variant="danger"
              size="sm"
              onClick={handleBulkCancel}
              disabled={isBulkCancelling}
              loading={isBulkCancelling}
              leftIcon={<IconPlayerStop size={13} />}
            >
              Cancel selected
            </Button>
          )}
          {checkedIds.size >= 2 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCompareIds(Array.from(checkedIds))}
              leftIcon={<IconArrowsLeftRight size={13} />}
            >
              Compare
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => setCheckedIds(new Set())}>
            Clear
          </Button>
        </div>
      )}

      {/* Loading and error render inside the table: the filter bar stays put
          and the rows become skeletons, instead of the whole view being
          replaced by a centred "Loading…" that jumps when data lands. */}
      <DataTable<ExecutionListItem>
        columns={executionColumns(
          (projectId, runId) => setCertModal({ projectId, runId }),
          (id) => setExpandedId((prev) => (prev === id ? null : id)),
          expandedId,
          sweepStats,
          { showProject: !projectId, projectName },
        )}
        rows={executions}
        rowKey={(ex) => ex.id}
        minWidth={720}
        stickyHeader
        loading={isLoading}
        error={error ? "Failed to load executions." : undefined}
        onRowClick={(ex) => selectExecution(selectedId === ex.id ? null : ex.id)}
        isRowSelected={(ex) => selectedId === ex.id}
        rowClassName={(ex) =>
          ex.status === "failed"
            ? "tui-table__row--accent-danger"
            : ex.status === "running"
            ? "tui-table__row--accent-info"
            : undefined
        }
        expandedRowKey={expandedId}
        renderRowDetail={(ex) => <ExecutionRowDetail execution={ex} sweepStats={sweepStats} />}
        // Any execution can be checked — comparison works across statuses;
        // bulk-cancel simply ignores non-active ones (see checkedActive).
        selection={{
          selected: checkedIds,
          onChange: setCheckedIds,
          isSelectable: () => true,
        }}
        empty={
          <EmptyState
            icon={hasFilters ? IconSearch : IconClockHour4}
            title={hasFilters ? "No executions match these filters" : "No executions yet"}
            description={
              hasFilters
                ? "Try adjusting or clearing the filters above."
                : "Run a pipeline from the Pipeline page to see results here."
            }
          />
        }
      />

      {!isLoading && executions.length > 0 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 10,
            padding: "10px 0",
            fontSize: "var(--text-2xs)",
            fontFamily: "var(--font-mono)",
            color: "var(--text-dim)",
          }}
        >
          <span>
            Showing {executions.length} of {total}
          </span>
          {executions.length < total && (
            <Button variant="ghost" size="sm" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
              Load more
            </Button>
          )}
        </div>
      )}

      {selectedId && (
        <LogsDrawer executionId={selectedId} onClose={() => selectExecution(null)} />
      )}

      {compareIds && (
        <CompareDrawer
          executions={executions.filter((e) => compareIds.includes(e.id))}
          onClose={() => setCompareIds(null)}
        />
      )}

      {certModal && (
        <CertificateModal
          key={certModal.runId}
          projectId={certModal.projectId}
          runId={certModal.runId}
          onClose={() => setCertModal(null)}
        />
      )}
    </PageContainer>
  );
}
