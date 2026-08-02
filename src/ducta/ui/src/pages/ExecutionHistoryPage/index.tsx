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
import { ExecutionRow } from "./ExecutionRow";

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

  // Only active executions are cancellable / selectable.
  const activeIds = executions
    .filter((e) => e.status === "running" || e.status === "pending")
    .map((e) => e.id);
  const checkedActive = activeIds.filter((id) => checkedIds.has(id));
  const allActiveChecked = activeIds.length > 0 && checkedActive.length === activeIds.length;

  const toggleCheck = (id: string) =>
    setCheckedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleCheckAll = () =>
    setCheckedIds(allActiveChecked ? new Set() : new Set(activeIds));

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

      {isLoading && (
        <div style={{ ...styles.fontMono, fontSize: 13, color: colors.textMuted }}>Loading…</div>
      )}

      {error && (
        <div style={{ ...styles.fontMono, fontSize: 13, color: colors.red }}>
          Failed to load executions.
        </div>
      )}

      {!isLoading && !error && (
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

          {executions.length === 0 ? (
            <EmptyState
              icon={hasFilters ? IconSearch : IconClockHour4}
              title={hasFilters ? "No executions match these filters" : "No executions yet"}
              description={
                hasFilters
                  ? "Try adjusting or clearing the filters above."
                  : "Run a pipeline from the Pipeline page to see results here."
              }
            />
          ) : (
            <div style={{ overflowX: "auto", width: "100%" }}>
              <table style={{ width: "100%", minWidth: 720, borderCollapse: "collapse", ...styles.fontSans }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${colors.border}` }}>
                    <th style={{ padding: "8px 12px", textAlign: "left", width: 32 }}>
                      <input
                        type="checkbox"
                        checked={allActiveChecked}
                        disabled={activeIds.length === 0}
                        onChange={toggleCheckAll}
                        aria-label="Select all active executions"
                        title={activeIds.length === 0 ? "No active executions" : "Select all active"}
                        style={{ cursor: activeIds.length === 0 ? "not-allowed" : "pointer" }}
                      />
                    </th>
                    {["Status", "Pipeline", "Project", "Env", "Started", "Duration", "ID", ""].map((h) => (
                      <th
                        key={h}
                        style={{
                          padding: "8px 12px",
                          textAlign: "left",
                          ...styles.fontSans,
                          fontSize: 11,
                          fontWeight: 600,
                          color: colors.textMuted,
                          textTransform: "uppercase",
                          letterSpacing: "0.06em",
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {executions.map((ex) => (
                    <ExecutionRow
                      key={ex.id}
                      execution={ex}
                      selected={selectedId === ex.id}
                      onSelect={() => setSelectedId(selectedId === ex.id ? null : ex.id)}
                      checked={checkedIds.has(ex.id)}
                      onToggleCheck={() => toggleCheck(ex.id)}
                      onShowCertificate={(projectId, runId) =>
                        setCertModal({ projectId, runId })
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

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
