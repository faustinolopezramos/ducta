import type { ReactNode } from "react";
import { colors } from "../../theme/tokens";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { StatusBadge, type Status } from "../../components/ui/StatusBadge";
import { useQualityScore } from "../../api/qualityApi";
import { IconGauge, IconX } from "@tabler/icons-react";
import { label } from "./shared";
import { Panel } from "../../components/ui/Panel";
import { Skeleton } from "../../components/ui/Skeleton";

// ─────────────────────────────────────────────
// COMPOSITE SCORE (linked from Execution History via ?run_id=)
// ─────────────────────────────────────────────

/** Maps a gate's action (pass/warn/block, ducta/check/gate.py's GateAction) to
 *  a StatusBadge status — "warn" must render distinctly from "pass", not as
 *  a green success (it previously fell through to the 2-way "not block"
 *  branch and rendered identically to a real pass). */
const GATE_ACTION_STATUS: Record<string, Status> = {
  pass: "success",
  warn: "warning",
  block: "failed",
};

function metricCard(title: string, value: string) {
  return (
    <div style={{ flex: 1, minWidth: 100, padding: "10px 12px", borderRadius: 6, border: `1px solid ${colors.border}`, background: colors.bg }}>
      <div style={label}>{title}</div>
      <div style={{ fontSize: "var(--text-lg)", fontWeight: 600, color: colors.text, fontFamily: "var(--font-mono)" }}>{value}</div>
    </div>
  );
}

/** A 0–1 score as a percentage: "100%", "97.3%". */
export function scorePercent(value: number | null | undefined): string {
  if (typeof value !== "number") return "—";
  const pct = value * 100;
  return `${Number.isInteger(pct) ? pct : pct.toFixed(1)}%`;
}

export function ScoreSection({
  runId,
  env,
  pipelineName,
  project,
  onClear,
  title = "Pipeline quality score",
  runLabel,
  picker,
}: {
  runId: string;
  env?: string;
  pipelineName?: string;
  project?: string;
  /** Only for a run someone picked: the latest run's score has nothing to clear. */
  onClear?: () => void;
  title?: string;
  /** The run in words (pipeline · when); the raw id otherwise. */
  runLabel?: string;
  /** Choose another run. */
  picker?: ReactNode;
}) {
  const score = useQualityScore(runId, env, pipelineName, project);

  return (
    <Panel>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <IconGauge size={16} color={colors.accent} />
        <h2 style={{ margin: 0, fontSize: "var(--text-base)", fontWeight: 600, color: colors.text, flex: 1 }}>
          {title}
          <span style={{ fontFamily: runLabel ? "var(--font-sans)" : "var(--font-mono)", fontWeight: 400, fontSize: "var(--text-xs)", color: colors.textMuted, marginLeft: 8 }}>
            {runLabel ?? runId}
          </span>
        </h2>
        {picker}
        {onClear && (
          <Button variant="ghost" size="sm" onClick={onClear} leftIcon={<IconX size={14} />}>
            Clear
          </Button>
        )}
      </div>

      {score.isLoading && <Skeleton variant="text" width="50%" />}

      {!score.isLoading && score.isError && (
        <EmptyState
          icon={IconGauge}
          title="No quality data for this run"
          description="The pipeline ran without quality checks, or its reports were removed."
          size="sm"
        />
      )}

      {score.data && (
        <div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            {metricCard("Health index", scorePercent(score.data.health_index))}
            {metricCard("Sanity score", scorePercent(score.data.sanity_score))}
            {metricCard("DQ score", scorePercent(score.data.dq_score))}
          </div>
          {score.data.nodes_blocked?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <span style={label}>Nodes blocked</span>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {score.data.nodes_blocked.map((n: string) => (
                  <StatusBadge key={n} status="failed" label={n} size="sm" />
                ))}
              </div>
            </div>
          )}
          {score.data.gate_actions && Object.keys(score.data.gate_actions).length > 0 && (
            <div>
              <span style={label}>Gate actions</span>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {Object.entries(score.data.gate_actions as Record<string, string>).map(([node, action]) => (
                  <StatusBadge
                    key={node}
                    status={GATE_ACTION_STATUS[action] ?? "idle"}
                    label={`${node}: ${action}`}
                    size="sm"
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
