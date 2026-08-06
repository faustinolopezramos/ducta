import { useState } from "react";
import { colors, styles } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { useExecutionList, type ExecutionListFilters } from "../../api/queries";
import { useBulkCancelExecutions } from "../../api/mutations";
import type { Execution } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { IconPlayerStop, IconClockHour4, IconSearch } from "@tabler/icons-react";
import { CertificateModal } from "../../components/Execution/CertificateModal";
import { QueueIndicator } from "./QueueIndicator";
import { FilterBar } from "./FilterBar";
import { LogsDrawer } from "./LogsDrawer";
import { DataTable } from "../../components/ui/DataTable";
import { executionColumns, isActiveExecution, type ExecutionListItem } from "./executionColumns";

// ─────────────────────────────────────────────
// EXECUTION HISTORY PAGE — /workspace/executions
// ─────────────────────────────────────────────

export function ExecutionHistoryPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filters, setFilters] = useState<ExecutionListFilters>({});
  const [checkedIds, setCheckedIds] = useState<Set<string>>(() => new Set());
  const [certModal, setCertModal] = useState<{ projectId: string; runId: string } | null>(null);

  const { data, isLoading, error } = useExecutionList(filters);
  const executions: (Execution & { project_id?: string; node_name?: string })[] =
    data?.executions ?? [];
  const { mutate: bulkCancel, isPending: isBulkCancelling } = useBulkCancelExecutions();

  const hasFilters = Object.values(filters).some((v) => v);

  // Derive unique pipeline names for the filter dropdown
  const pipelineNames = Array.from(
    new Set(executions.map((e) => e.pipeline_name).filter(Boolean))
  ).sort();

  // Only active executions are cancellable; DataTable owns the checkbox state
  // itself, so this is just the subset the bulk action applies to.
  const checkedActive = executions
    .filter((e) => isActiveExecution(e) && checkedIds.has(e.id))
    .map((e) => e.id);

  const handleBulkCancel = () => {
    if (checkedActive.length === 0) return;
    bulkCancel(checkedActive, { onSuccess: () => setCheckedIds(new Set()) });
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "36px 48px", background: colors.bg, minHeight: 0 }}>
      <PageHeader
        title="Execution History"
        description="All pipeline runs — click any row to view its logs."
        backTo="/projects"
        backLabel="Dashboard"
        actions={<QueueIndicator />}
      />

      {/* Loading and error are rendered inside the table now — the filter bar
          stays put and the rows become skeletons, instead of the whole view
          being replaced by a centred "Loading…" and jumping when data lands. */}
      <>
          <FilterBar
            filters={filters}
            onChange={setFilters}
            pipelines={pipelineNames}
          />

          {checkedActive.length > 0 && (
            <div
              role="region"
              aria-label="Bulk actions"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "8px 12px",
                marginBottom: 8,
                borderRadius: 6,
                background: colors.accentBg,
                border: `1px solid ${colors.accentA30}`,
              }}
            >
              <span style={{ ...styles.fontMono, fontSize: 12, color: colors.text }}>
                {checkedActive.length} selected
              </span>
              <Button
                variant="danger"
                size="sm"
                onClick={handleBulkCancel}
                disabled={isBulkCancelling}
                loading={isBulkCancelling}
              >
                <IconPlayerStop size={12} style={{ marginRight: 4 }} />
                Cancel selected
              </Button>
              <button
                onClick={() => setCheckedIds(new Set())}
                style={{ background: "none", border: "none", cursor: "pointer", color: colors.textMuted, ...styles.fontSans, fontSize: 11 }}
              >
                Clear
              </button>
            </div>
          )}

          <DataTable<ExecutionListItem>
            columns={executionColumns((projectId, runId) => setCertModal({ projectId, runId }))}
            rows={executions}
            rowKey={(ex) => ex.id}
            minWidth={720}
            stickyHeader
            loading={isLoading}
            error={error ? "Failed to load executions." : undefined}
            onRowClick={(ex) => setSelectedId(selectedId === ex.id ? null : ex.id)}
            isRowSelected={(ex) => selectedId === ex.id}
            // Only a running or pending execution can be bulk-cancelled.
            selection={{
              selected: checkedIds,
              onChange: setCheckedIds,
              isSelectable: isActiveExecution,
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
      </>

      {selectedId && (
        <LogsDrawer executionId={selectedId} onClose={() => setSelectedId(null)} />
      )}

      {certModal && (
        <CertificateModal
          projectId={certModal.projectId}
          runId={certModal.runId}
          onClose={() => setCertModal(null)}
        />
      )}
    </div>
  );
}
