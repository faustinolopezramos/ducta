import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import client from "../../api/client";
import { colors } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { ActionButton } from "../../components/ui/ActionButton";
import { EmptyState } from "../../components/ui/EmptyState";
import { StatusBadge } from "../../components/ui/StatusBadge";
import {
  useQualityReport,
  useQualityRuns,
  useDeleteQualityReport,
  fetchQualityReport,
  type RunChecksVars,
} from "../../api/qualityApi";
import { CheckResultsList, RawJson, type QualityReportData } from "../../components/Quality/report";
import { IconDatabase, IconRefresh, IconTrash, IconX } from "@tabler/icons-react";
import { label } from "./shared";
import { Panel } from "../../components/ui/Panel";
import { Skeleton } from "../../components/ui/Skeleton";
import { qk } from "../../api/queryKeys";

// ─────────────────────────────────────────────
// DATASET DETAIL (run history + report)
// ─────────────────────────────────────────────

function RunHistoryRow({
  dataset,
  env,
  pipelineName,
  project,
  runId,
  selected,
  onSelect,
  onDeleted,
}: {
  dataset: string;
  env?: string;
  pipelineName?: string;
  project?: string;
  runId: string;
  selected: boolean;
  onSelect: () => void;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const deleteReport = useDeleteQualityReport();

  const handleRerun = async () => {
    const report = (await fetchQualityReport(
      dataset,
      runId,
      env,
      pipelineName,
      project
    )) as QualityReportData;
    const source = report.source;
    if (!source?.input_path) {
      throw new Error("This report has no reproducible source (run before rerun support was added)");
    }
    const vars: RunChecksVars = {
      input_path: source.input_path,
      format: (source.format as RunChecksVars["format"]) ?? "parquet",
      fail_fast: source.fail_fast ?? false,
    };
    if (source.checks) vars.checks = source.checks;
    else if (source.config_path) vars.config_path = source.config_path;
    await client.post("/quality/run", vars);
    queryClient.invalidateQueries({ queryKey: qk.quality.all() });
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        padding: "6px 0",
        borderTop: `1px solid ${colors.border}`,
      }}
    >
      <button
        onClick={onSelect}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-xs)",
          fontWeight: selected ? 700 : 400,
          color: selected ? colors.accent : colors.text,
        }}
      >
        {runId}
      </button>
      <div style={{ display: "flex", gap: 4 }}>
        <ActionButton
          variant="ghost"
          size="sm"
          leftIcon={<IconRefresh size={13} />}
          onAction={handleRerun}
          successMessage="Rerun started"
          errorMessage="Could not rerun this report"
        >
          Rerun
        </ActionButton>
        <ActionButton
          variant="ghost"
          size="sm"
          leftIcon={<IconTrash size={13} />}
          confirm={{
            title: `Delete report ${runId}?`,
            description: "The quality results for this run are removed from history.",
            tone: "danger",
            confirmLabel: "Delete report",
          }}
          onAction={async () => {
            await deleteReport.mutateAsync({ dataset, runId, env, pipelineName, project });
            onDeleted();
          }}
          successMessage="Report deleted"
          errorMessage="Could not delete report"
        >
          Delete
        </ActionButton>
      </div>
    </div>
  );
}

export function DatasetDetail({
  dataset,
  env,
  pipelineName,
  project,
  onClose,
}: {
  dataset: string;
  env?: string;
  pipelineName?: string;
  project?: string;
  onClose: () => void;
}) {
  const [runId, setRunId] = useState<string | undefined>(undefined);
  const runs = useQualityRuns(dataset, env, pipelineName, project);
  const runIds = useMemo(() => (runs.data?.run_ids ?? []).slice().sort().reverse(), [runs.data]);
  const report = useQualityReport(dataset, runId, env, pipelineName, project);

  return (
    <Panel>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <IconDatabase size={16} color={colors.accent} />
        <h2 style={{ margin: 0, fontSize: "var(--text-base)", fontWeight: 600, color: colors.text, flex: 1 }}>
          {pipelineName && pipelineName !== "_adhoc" ? `${pipelineName} / ${dataset}` : dataset}
        </h2>
        <Button variant="ghost" size="sm" onClick={onClose} leftIcon={<IconX size={14} />}>
          Close
        </Button>
      </div>

      {runIds.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <span style={label}>Run history</span>
          {runIds.map((id) => (
            <RunHistoryRow
              key={id}
              dataset={dataset}
              env={env}
              pipelineName={pipelineName}
              project={project}
              runId={id}
              selected={(runId ?? runIds[0]) === id}
              onSelect={() => setRunId(id)}
              onDeleted={() => setRunId((current) => (current === id ? undefined : current))}
            />
          ))}
        </div>
      )}

      {report.isLoading && <Skeleton variant="text" width="40%" />}

      {report.data && (report.data as QualityReportData).results && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <StatusBadge
              status={(report.data as QualityReportData).passed ? "success" : "failed"}
            />
            {typeof (report.data as QualityReportData).score === "number" && (
              <span style={{ fontSize: "var(--text-xs)", color: colors.textMuted }}>
                score {(report.data as QualityReportData).score!.toFixed(3)}
              </span>
            )}
          </div>
          <CheckResultsList results={(report.data as QualityReportData).results!} />
          <RawJson data={report.data} />
        </div>
      )}

      {!report.isLoading && report.data && !(report.data as QualityReportData).results && (
        <EmptyState
          icon={IconDatabase}
          title="No reports yet"
          description={
            (report.data as QualityReportData).message ?? `No stored reports for "${dataset}".`
          }
          size="sm"
        />
      )}
    </Panel>
  );
}
