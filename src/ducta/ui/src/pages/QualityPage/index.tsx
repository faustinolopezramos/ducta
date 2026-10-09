import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { colors } from "../../theme/tokens";
import { PageHeader } from "../../components/ui/PageHeader";
import { PageContainer } from "../../components/ui/PageContainer";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Panel } from "../../components/ui/Panel";
import { Field } from "../../components/ui/Field";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Sparkline } from "../../components/Quality/Sparkline";
import { useQualitySummary, type QualityDatasetSummary } from "../../api/qualityApi";
import { useEnvironments, useExecutionList, useServerProjects } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { RunChecksModal } from "../../components/Quality/RunChecksModal";
import { ValidateConfigModal } from "../../components/Quality/ValidateConfigModal";
import {
  IconPlayerPlay,
  IconGauge,
  IconShieldCheck,
  IconDatabase,
} from "@tabler/icons-react";
import { sectionTitle, scoreColor } from "./shared";
import { formatDate } from "../../utils/formatDate";
import { formatRelative } from "../../utils/timeLabels";
import { statusMetaFor } from "../../components/ui/statusMeta";
import { DatasetDetail } from "./DatasetDetail";
import { ScoreSection } from "./ScoreSection";
import { ChecksCard } from "./ChecksCard";

// ─────────────────────────────────────────────
// PAGE
// ─────────────────────────────────────────────

const ADHOC_LABEL = "Manual run";
/** `?env=` value for the ad-hoc bucket (reports with no environment). */
const ADHOC_ENV = "_adhoc";

export default function QualityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  // Under a project the rail already names it: no second project picker.
  const { projectId: routeProject } = useParams<{ projectId?: string }>();
  const activeEnv = useSourceStore((st) => st.activeEnv) || "base";

  const project = searchParams.get("project") ?? "";
  // The environment follows the one in the header unless the URL names
  // another — or the ad-hoc bucket, where "Run checks" reports land.
  const envParam = searchParams.get("env");
  const adhoc = envParam === ADHOC_ENV;
  const env = adhoc ? "" : (envParam ?? activeEnv);
  const pipelineName = searchParams.get("pipeline_name") ?? "";
  const selectedDataset = searchParams.get("dataset") ?? "";
  const scoreRunId = searchParams.get("run_id") ?? "";

  const [showRunModal, setShowRunModal] = useState(false);
  const [showValidateModal, setShowValidateModal] = useState(false);
  const [manualRunId, setManualRunId] = useState("");
  const { data: recentRunsData } = useExecutionList({ project_id: project || undefined, limit: 20 });
  const recentRuns = (recentRunsData?.executions ?? []) as Array<{
    id: string; pipeline_name: string; status: string; env?: string; started_at?: string | null; certificate_run_id?: string | null;
  }>;

  const { data: projectsData } = useServerProjects();
  const projects = projectsData?.projects ?? [];

  const { data: environmentsData } = useEnvironments(project || undefined);
  const environments: string[] = environmentsData?.environments ?? [];

  const summary = useQualitySummary(env || undefined, undefined, project || undefined);
  const datasets = useMemo(
    () =>
      [...(summary.data ?? [])].sort((a, b) =>
        (b.created_at ?? "").localeCompare(a.created_at ?? "")
      ),
    [summary.data]
  );

  const setParam = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearchParams(next, { replace: true });
  };

  const handleProjectChange = (value: string) => {
    // A different project invalidates env, pipeline and dataset selection —
    // each project declares its own environments and keeps its own quality data.
    setParam({
      project: value || undefined,
      env: undefined,
      pipeline_name: undefined,
      dataset: undefined,
    });
  };

  const handleEnvChange = (value: string) => {
    setParam({ env: value === activeEnv ? undefined : value, pipeline_name: undefined, dataset: undefined });
  };

  const selectDataset = (row: { pipeline_name: string; dataset: string }) => {
    setParam({ pipeline_name: row.pipeline_name, dataset: row.dataset });
  };

  const columns: DataTableColumn<QualityDatasetSummary>[] = [
    {
      key: "pipeline_name",
      header: "Pipeline",
      sortable: true,
      cell: (r) => (r.pipeline_name === "_adhoc" ? ADHOC_LABEL : r.pipeline_name),
    },
    {
      key: "dataset",
      header: "Dataset",
      sortable: true,
      mono: true,
    },
    {
      key: "passed",
      header: "Status",
      sortable: true,
      cell: (r) =>
        r.passed == null ? (
          <span style={{ color: colors.textMuted }}>—</span>
        ) : (
          <StatusBadge status={r.passed ? "success" : "failed"} size="sm" />
        ),
    },
    {
      key: "latest_score",
      header: "Score",
      sortable: true,
      align: "right",
      mono: true,
      cell: (r) => (typeof r.latest_score === "number" ? r.latest_score.toFixed(3) : "—"),
    },
    {
      key: "trend",
      header: "Trend",
      cell: (r) => <Sparkline values={r.trend} color={scoreColor(r.latest_score)} />,
    },
    {
      key: "run_count",
      header: "Runs",
      sortable: true,
      align: "right",
    },
    {
      key: "created_at",
      header: "Last run",
      sortable: true,
      cell: (r) => formatDate(r.created_at),
    },
  ];

  return (
    <PageContainer>
      <PageHeader
        title="Quality"
        description="Dataset health at a glance — drill into reports, run checks, validate node configs."
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setShowValidateModal(true)}
              leftIcon={<IconShieldCheck size={15} />}
            >
              Validate node config
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowRunModal(true)}
              leftIcon={<IconPlayerPlay size={15} />}
            >
              Run checks
            </Button>
          </>
        }
      />

      {scoreRunId && (
        <ScoreSection
          runId={scoreRunId}
          env={env || undefined}
          pipelineName={pipelineName || undefined}
          project={project || undefined}
          onClear={() => setParam({ run_id: undefined })}
        />
      )}

      {/* ── Dataset overview ── */}
      <Panel>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
          {sectionTitle(<IconDatabase size={16} color={colors.accent} />, "Datasets")}
          <div style={{ flex: 1 }} />
          {!routeProject && <Field label="Project">
            <select
              className="input-field"
              style={{ minWidth: 160 }}
              value={project}
              onChange={(e) => handleProjectChange(e.target.value)}
              aria-label="Quality reports project"
            >
              <option value="">Current workspace</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>}
          <Field label="Environment">
            <select
              className="input-field"
              style={{ minWidth: 160 }}
              value={adhoc ? ADHOC_ENV : env}
              onChange={(e) => handleEnvChange(e.target.value)}
              aria-label="Quality reports environment"
            >
              {["base", ...environments.filter((e) => e !== "base")].map((e) => (
                <option key={e} value={e}>
                  {e}{e === activeEnv ? " (active)" : ""}
                </option>
              ))}
              <option value={ADHOC_ENV}>{ADHOC_LABEL}s (ad-hoc)</option>
            </select>
          </Field>
        </div>

        <DataTable<QualityDatasetSummary>
          columns={columns}
          rows={datasets}
          rowKey={(r) => `${r.pipeline_name}/${r.dataset}`}
          loading={summary.isLoading}
          error={summary.isError ? "Couldn't load quality reports. Check that the API is reachable." : undefined}
          onRowClick={selectDataset}
          isRowSelected={(r) => r.pipeline_name === pipelineName && r.dataset === selectedDataset}
          empty={
            <EmptyState
              icon={IconDatabase}
              title={env ? "No quality reports in this environment" : "No quality reports yet"}
              description={
                env
                  ? "Try another environment above, or run a pipeline with sanity_checks / data_quality enabled on its nodes."
                  : "Run checks on a data file, or execute a pipeline with sanity_checks / data_quality enabled on its nodes."
              }
              action={
                <Button variant="ghost" size="sm" onClick={() => setShowRunModal(true)}>
                  <IconPlayerPlay size={14} /> Run your first checks
                </Button>
              }
            />
          }
        />
      </Panel>

      {selectedDataset && (
        <DatasetDetail
          dataset={selectedDataset}
          env={env || undefined}
          pipelineName={pipelineName || undefined}
          project={project || undefined}
          onClose={() => setParam({ dataset: undefined, pipeline_name: undefined })}
        />
      )}

      {/* ── Manual composite-score lookup (fallback when not linked from a run) ── */}
      {!scoreRunId && (
        <Panel>
          {sectionTitle(<IconGauge size={16} color={colors.accent} />, "Pipeline quality score")}
          <p className="quality-score-hint">
            Pick a recent run to see its composite quality score.
          </p>
          <div className="quality-score-pick">
            <Field label="Run">
              <select
                className="input-field"
                value={manualRunId}
                onChange={(e) => setManualRunId(e.target.value)}
                aria-label="Run to score"
              >
                <option value="">Choose a run…</option>
                {recentRuns.map((r) => (
                  <option key={r.id} value={r.certificate_run_id ?? r.id}>
                    {r.pipeline_name} · {(statusMetaFor(r.status)?.label ?? r.status).toLowerCase()} · {r.env ?? ""} · {formatRelative(r.started_at) ?? ""}
                  </option>
                ))}
              </select>
            </Field>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setParam({ run_id: manualRunId.trim() })}
              disabled={!manualRunId.trim()}
            >
              Show score
            </Button>
          </div>
        </Panel>
      )}

      <ChecksCard />

      {showRunModal && (
        <RunChecksModal
          onClose={() => setShowRunModal(false)}
          onCompleted={(dataset) => {
            setShowRunModal(false);
            // Ad-hoc "Run checks" reports always land in the connected source's
            // own project, in its ad-hoc bucket — clear project/env/pipeline
            // scope so the drill-down looks in the right place.
            if (dataset)
              setParam({ project: routeProject ? project : undefined, env: ADHOC_ENV, pipeline_name: undefined, dataset });
          }}
        />
      )}
      {showValidateModal && <ValidateConfigModal onClose={() => setShowValidateModal(false)} />}
    </PageContainer>
  );
}
