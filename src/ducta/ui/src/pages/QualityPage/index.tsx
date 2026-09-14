import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import { useEnvironments, useServerProjects } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { RunChecksModal } from "../../components/Quality/RunChecksModal";
import { ValidateConfigModal } from "../../components/Quality/ValidateConfigModal";
import {
  IconPlayerPlay,
  IconGauge,
  IconShieldCheck,
  IconDatabase,
} from "@tabler/icons-react";
import { input, sectionTitle, formatDate, scoreColor } from "./shared";
import { DatasetDetail } from "./DatasetDetail";
import { ScoreSection } from "./ScoreSection";
import { ChecksCard } from "./ChecksCard";

// ─────────────────────────────────────────────
// PAGE
// ─────────────────────────────────────────────

const ADHOC_LABEL = "Manual run";

export default function QualityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const seeded = useRef(false);

  // Seed the environment filter from the workspace's active environment on a
  // completely fresh visit (no quality-page params at all) — afterwards the
  // URL is the single source of truth, so deep links stay authoritative.
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;
    if (
      !searchParams.has("project") &&
      !searchParams.has("env") &&
      !searchParams.has("pipeline_name") &&
      !searchParams.has("dataset") &&
      !searchParams.has("run_id")
    ) {
      const activeEnv = useSourceStore.getState().activeEnv;
      if (activeEnv) {
        const next = new URLSearchParams(searchParams);
        next.set("env", activeEnv);
        setSearchParams(next, { replace: true });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const project = searchParams.get("project") ?? "";
  const env = searchParams.get("env") ?? "";
  const pipelineName = searchParams.get("pipeline_name") ?? "";
  const selectedDataset = searchParams.get("dataset") ?? "";
  const scoreRunId = searchParams.get("run_id") ?? "";

  const [showRunModal, setShowRunModal] = useState(false);
  const [showValidateModal, setShowValidateModal] = useState(false);
  const [manualRunId, setManualRunId] = useState("");

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
    // each project has its own environment.yaml and its own quality data.
    setParam({
      project: value || undefined,
      env: undefined,
      pipeline_name: undefined,
      dataset: undefined,
    });
  };

  const handleEnvChange = (value: string) => {
    setParam({ env: value || undefined, pipeline_name: undefined, dataset: undefined });
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
      mono: true,
      cell: (r) => formatDate(r.created_at),
    },
  ];

  return (
    <PageContainer>
      <PageHeader
        title="Data Quality"
        description="Dataset health at a glance — drill into reports, run checks, validate node configs"
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
          <Field label="Project">
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
          </Field>
          <Field label="Environment">
            <select
              className="input-field"
              style={{ minWidth: 160 }}
              value={env}
              onChange={(e) => handleEnvChange(e.target.value)}
              aria-label="Quality reports environment"
            >
              <option value="">{ADHOC_LABEL}s (ad-hoc)</option>
              {environments.map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
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
          <p style={{ margin: "0 0 10px", fontSize: 12, color: colors.textMuted }}>
            Open a score from Execution History (Quality action on a run), or look one up by run id.
          </p>
          {/* The page fills the window, but a single id field should not be
              1500px wide — the measure belongs on the control, not the page. */}
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", maxWidth: 520 }}>
            <div style={{ flex: 1 }}>
              <Field label="Run ID">
                <input
                  style={input}
                  value={manualRunId}
                  onChange={(e) => setManualRunId(e.target.value)}
                  placeholder="e.g. 3f9a2c81"
                />
              </Field>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setParam({ run_id: manualRunId.trim() })}
              disabled={!manualRunId.trim()}
            >
              Load
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
              setParam({ project: undefined, env: undefined, pipeline_name: undefined, dataset });
          }}
        />
      )}
      {showValidateModal && <ValidateConfigModal onClose={() => setShowValidateModal(false)} />}
    </PageContainer>
  );
}
