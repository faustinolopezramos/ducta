import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { colors } from "../../theme/tokens";
import { PageHeader } from "../../components/ui/PageHeader";
import { PageContainer } from "../../components/ui/PageContainer";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Panel } from "../../components/ui/Panel";
import { Skeleton } from "../../components/ui/Skeleton";
import { Field } from "../../components/ui/Field";
import { useQualitySummary } from "../../api/qualityApi";
import { RunChecksModal } from "../../components/Quality/RunChecksModal";
import { ValidateConfigModal } from "../../components/Quality/ValidateConfigModal";
import {
  IconPlayerPlay,
  IconGauge,
  IconShieldCheck,
  IconDatabase,
} from "@tabler/icons-react";
import { input, sectionTitle } from "./shared";
import { DatasetCard } from "./DatasetCard";
import { DatasetDetail } from "./DatasetDetail";
import { ScoreSection } from "./ScoreSection";
import { ChecksCard } from "./ChecksCard";

// ─────────────────────────────────────────────
// PAGE
// ─────────────────────────────────────────────

export default function QualityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scoreRunId = searchParams.get("run_id") ?? "";
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [showRunModal, setShowRunModal] = useState(false);
  const [showValidateModal, setShowValidateModal] = useState(false);
  const [manualRunId, setManualRunId] = useState("");

  const summary = useQualitySummary();
  const datasets = summary.data ?? [];

  return (
    <PageContainer maxWidth={960}>
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
        <ScoreSection runId={scoreRunId} onClear={() => setSearchParams({}, { replace: true })} />
      )}

      {/* ── Dataset overview ── */}
      {summary.isLoading && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12, marginBottom: 16 }}>
          <Skeleton variant="block" height="88px" />
          <Skeleton variant="block" height="88px" />
          <Skeleton variant="block" height="88px" />
        </div>
      )}

      {!summary.isLoading && summary.isError && (
        <Panel>
          <EmptyState
            icon={IconDatabase}
            title="Couldn't load quality reports"
            description="Check that the API is reachable and try again."
            action={
              <Button variant="ghost" size="sm" onClick={() => summary.refetch()}>
                Refresh
              </Button>
            }
          />
        </Panel>
      )}

      {!summary.isLoading && !summary.isError && datasets.length === 0 && (
        <Panel>
          <EmptyState
            icon={IconDatabase}
            title="No quality reports yet"
            description="Run checks on a data file, or execute a pipeline with sanity_checks / data_quality enabled on its nodes."
            action={
              <Button variant="ghost" size="sm" onClick={() => setShowRunModal(true)}>
                <IconPlayerPlay size={14} /> Run your first checks
              </Button>
            }
          />
        </Panel>
      )}

      {datasets.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
            gap: 12,
            marginBottom: 16,
          }}
        >
          {datasets.map((d) => (
            <DatasetCard
              key={d.dataset}
              item={d}
              selected={selectedDataset === d.dataset}
              onSelect={() =>
                setSelectedDataset((cur) => (cur === d.dataset ? null : d.dataset))
              }
            />
          ))}
        </div>
      )}

      {selectedDataset && (
        <DatasetDetail dataset={selectedDataset} onClose={() => setSelectedDataset(null)} />
      )}

      {/* ── Manual composite-score lookup (fallback when not linked from a run) ── */}
      {!scoreRunId && (
        <Panel>
          {sectionTitle(<IconGauge size={16} color={colors.accent} />, "Pipeline quality score")}
          <p style={{ margin: "0 0 10px", fontSize: 12, color: colors.textMuted }}>
            Open a score from Execution History (Quality action on a run), or look one up by run id.
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
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
              onClick={() => setSearchParams({ run_id: manualRunId.trim() }, { replace: true })}
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
            if (dataset) setSelectedDataset(dataset);
          }}
        />
      )}
      {showValidateModal && <ValidateConfigModal onClose={() => setShowValidateModal(false)} />}
    </PageContainer>
  );
}
