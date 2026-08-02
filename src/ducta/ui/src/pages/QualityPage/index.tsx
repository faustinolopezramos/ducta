import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { colors } from "../../theme/tokens";
import { PageHeader } from "../../components/ui/PageHeader";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useQualitySummary } from "../../api/qualityApi";
import { RunChecksModal } from "../../components/Quality/RunChecksModal";
import { ValidateConfigModal } from "../../components/Quality/ValidateConfigModal";
import {
  IconPlayerPlay,
  IconGauge,
  IconShieldCheck,
  IconDatabase,
} from "@tabler/icons-react";
import { card, input, sectionTitle } from "./shared";
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
    <div style={{ padding: 24, maxWidth: 960, margin: "0 auto" }}>
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
        <p style={{ fontSize: 12, color: colors.textMuted }}>Loading datasets…</p>
      )}

      {!summary.isLoading && datasets.length === 0 && (
        <div style={card}>
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
        </div>
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
        <div style={card}>
          {sectionTitle(<IconGauge size={16} color={colors.accent} />, "Pipeline quality score")}
          <p style={{ margin: "0 0 10px", fontSize: 12, color: colors.textMuted }}>
            Open a score from Execution History (Quality action on a run), or look one up by run id.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              style={input}
              value={manualRunId}
              onChange={(e) => setManualRunId(e.target.value)}
              placeholder="run id"
            />
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setSearchParams({ run_id: manualRunId.trim() }, { replace: true })}
              disabled={!manualRunId.trim()}
            >
              Load
            </Button>
          </div>
        </div>
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
    </div>
  );
}
