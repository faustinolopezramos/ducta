import type { CSSProperties } from "react";
import { colors } from "../../../theme/tokens";
import { Button } from "../../ui";
import { ICONS } from "../../icons";
import type { LiveMedallionMonitorProps } from "./types";
import { statusColor, shortId } from "./helpers";
import {
  StatCard,
  UptimeTicker,
  SkeletonCard,
  Gauge,
  pulseKeyframes,
  PulsingDot,
  NodeCard,
  DataTable,
} from "./subcomponents";
import { useStreamingMonitor } from "./useStreamingMonitor";

export function LiveMedallionMonitor({ executionId, onCancel, executionStatus }: LiveMedallionMonitorProps) {
  const {
    status,
    data,
    monitorState,
    errorMsg,
    lastUpdated,
    confirmStop,
    setConfirmStop,
    confirmClear,
    setConfirmClear,
    restartingNodes,
    isClearingCheckpoints,
    handleRestartNode,
    handleClearCheckpoints,
    currentStatus,
    isTerminal,
    nodes,
    isNodeActive,
    nodeError,
    nodeRate,
    dataNodes,
    uptime,
    isLoading,
    pm,
    maxRateRef,
  } = useStreamingMonitor(executionId, executionStatus);

  // ── Styles ──────────────────────────────────────────────────────────────────

  const sectionStyle: CSSProperties = {
    background: colors.surfaceElevated,
    border: `1px solid ${colors.border}`,
    borderRadius: "12px",
    padding: "20px",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
  };

  const sectionTitleStyle: CSSProperties = {
    fontSize: "11px",
    fontWeight: 700,
    color: colors.textMuted,
    margin: 0,
    textTransform: "uppercase",
    letterSpacing: "0.8px",
  };

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <>
      {/* Inject pulse keyframe once */}
      <style>{pulseKeyframes}</style>

      <div
        style={{
          padding: "20px",
          display: "flex",
          flexDirection: "column",
          gap: "20px",
          overflowY: "auto",
          height: "100%",
          fontFamily: "var(--font-sans)",
          backgroundColor: colors.bg,
        }}
      >
        {/* ── Header ── */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "12px", flexWrap: "wrap" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <h2 style={{ fontSize: "18px", fontWeight: 700, color: colors.text, margin: 0 }}>
                Live Stream Monitor
              </h2>
              {currentStatus && (
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    padding: "3px 10px",
                    borderRadius: "12px",
                    color: statusColor(currentStatus),
                    background: `${statusColor(currentStatus)}1A`,
                    display: "flex",
                    alignItems: "center",
                    gap: "5px",
                  }}
                >
                  {currentStatus === "running" && <PulsingDot color={statusColor(currentStatus)} />}
                  {currentStatus}
                </span>
              )}
            </div>
            <p style={{ fontSize: "12px", color: colors.textMuted, margin: "5px 0 0 0", display: "flex", alignItems: "center", gap: "6px" }}>
              {status?.pipeline_name && (
                <span style={{ fontWeight: 600, color: colors.text }}>{status.pipeline_name}</span>
              )}
              {status?.pipeline_name && <span style={{ color: colors.border }}>·</span>}
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }} title={executionId ?? undefined}>
                {executionId ? shortId(executionId) : "No execution"}
              </span>
              {lastUpdated && (
                <>
                  <span style={{ color: colors.border }}>·</span>
                  <span style={{ fontSize: "11px" }}>
                    Updated {lastUpdated.toLocaleTimeString()}
                  </span>
                </>
              )}
            </p>
          </div>

          {/* Stop / Clear Checkpoints with inline confirmation */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            {confirmClear ? (
              <>
                <span style={{ fontSize: "12px", color: colors.textMuted }}>Clear all checkpoints?</span>
                <Button variant="ghost" size="md" onClick={() => setConfirmClear(false)}>
                  Cancel
                </Button>
                <Button
                  variant="ghost"
                  size="md"
                  onClick={handleClearCheckpoints}
                  style={{ color: colors.warningStrong, fontWeight: 600 }}
                >
                  Confirm Clear
                </Button>
              </>
            ) : (
              <Button
                variant="ghost"
                size="md"
                onClick={() => setConfirmClear(true)}
                disabled={isClearingCheckpoints || isTerminal}
                style={{ fontSize: "12px", color: colors.textMuted }}
              >
                {isClearingCheckpoints ? "Clearing..." : "Clear Checkpoints"}
              </Button>
            )}

            {confirmStop ? (
              <>
                <span style={{ fontSize: "12px", color: colors.textMuted }}>Stop pipeline?</span>
                <Button variant="ghost" size="md" onClick={() => setConfirmStop(false)}>
                  Cancel
                </Button>
                <Button
                  variant="ghost"
                  size="md"
                  onClick={onCancel}
                  style={{ color: colors.red, borderColor: colors.redA30, backgroundColor: colors.redA12, fontWeight: 600 }}
                >
                  {ICONS.STOP} Confirm Stop
                </Button>
              </>
            ) : (
              <Button
                variant="ghost"
                size="md"
                onClick={() => setConfirmStop(true)}
                disabled={isTerminal}
                style={{ color: colors.red, borderColor: colors.redA30, backgroundColor: colors.redA12, fontWeight: 600, opacity: isTerminal ? 0.5 : 1 }}
              >
                {ICONS.STOP} {isTerminal ? "Stream Stopped" : "Stop Stream"}
              </Button>
            )}
          </div>
        </div>

        {/* ── Error banner (only real errors, not 404) ── */}
        {errorMsg && (
          <div
            style={{
              padding: "12px 16px",
              backgroundColor: colors.errorBg,
              border: `1px solid ${colors.errorBorder}`,
              borderRadius: "8px",
              color: colors.error,
              fontSize: "13px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            ⚠️ {errorMsg}
          </div>
        )}

        {/* ── Pipeline Flow ── */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Pipeline Flow</h3>

          {isLoading || nodes.length === 0 ? (
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <PulsingDot color={colors.blue} />
              <span style={{ color: colors.textMuted, fontSize: "13px" }}>
                {monitorState === "stopped"
                  ? "Stream stopped — the engine is no longer running."
                  : monitorState === "waiting"
                  ? "Initializing streaming engine — this may take a few seconds…"
                  : "No nodes detected yet"}
              </span>
            </div>
          ) : (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "10px",
              }}
            >
              {nodes.map((node, idx) => (
                <div key={node} style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <NodeCard
                    name={node}
                    active={isNodeActive(node)}
                    error={nodeError(node)}
                    rate={nodeRate(node)}
                    onRestart={() => handleRestartNode(node)}
                    isRestarting={restartingNodes.has(node)}
                  />
                  {idx < nodes.length - 1 && (
                    <span style={{ color: colors.border, fontSize: "18px", flexShrink: 0 }}>→</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Summary + Engine Performance ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "16px" }}>

          {/* Summary */}
          <div style={sectionStyle}>
            <h3 style={sectionTitleStyle}>Pipeline Summary</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              {isLoading ? (
                [1, 2, 3, 4].map((i) => <SkeletonCard key={i} />)
              ) : (
                <>
                  <StatCard
                    label="Active Queries"
                    color={colors.green}
                    sub={`/ ${status?.total_queries ?? nodes.length}`}
                  >
                    {status?.active_queries ?? 0}
                  </StatCard>
                  <StatCard
                    label="Failed Queries"
                    color={(status?.failed_queries ?? 0) > 0 ? colors.red : colors.text}
                  >
                    {status?.failed_queries ?? 0}
                  </StatCard>
                  <StatCard label="Uptime">
                    <UptimeTicker
                      baseSeconds={uptime}
                      syncedAt={lastUpdated?.getTime() ?? null}
                      running={!isTerminal && monitorState === "running"}
                    />
                  </StatCard>
                  <StatCard label="Nodes" color={colors.primary}>
                    {nodes.length}
                  </StatCard>
                </>
              )}
            </div>
          </div>

          {/* Engine Performance */}
          <div style={sectionStyle}>
            <h3 style={sectionTitleStyle}>Engine Performance</h3>

            {isLoading ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <SkeletonCard />
                <SkeletonCard />
              </div>
            ) : pm ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                <Gauge
                  label="Input Velocity"
                  value={pm.total_input_rate ?? 0}
                  maxValue={maxRateRef.current}
                  color={colors.blue}
                />
                <Gauge
                  label="Processing Velocity"
                  value={pm.total_processing_rate ?? 0}
                  maxValue={maxRateRef.current}
                  color={colors.purple}
                />
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: "4px", borderTop: `1px solid ${colors.border}` }}>
                  <span style={{ fontSize: "12px", color: colors.textMuted }}>Processing Efficiency</span>
                  <span style={{ fontSize: "13px", fontWeight: 700, fontFamily: "var(--font-mono)", color: colors.green }}>
                    {(pm.processing_efficiency ?? 0).toFixed(1)}%
                  </span>
                </div>
                {pm.health_score !== undefined && (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "12px", color: colors.textMuted }}>Health Score</span>
                    <span
                      style={{
                        fontSize: "13px",
                        fontWeight: 700,
                        fontFamily: "var(--font-mono)",
                        color: pm.health_score >= 80 ? colors.green : pm.health_score >= 50 ? colors.warningStrong : colors.red,
                      }}
                    >
                      {Number(pm.health_score).toFixed(1)}%
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: "8px", color: colors.textMuted, fontSize: "13px" }}>
                <PulsingDot color={colors.blue} />
                Waiting for Spark engine metrics…
              </div>
            )}
          </div>
        </div>

        {/* ── Recent Output Data ── */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Recent Output Data</h3>

          {isLoading ? (
            <div style={{ display: "flex", alignItems: "center", gap: "8px", color: colors.textMuted, fontSize: "13px" }}>
              <PulsingDot color={colors.blue} />
              Waiting for output rows…
            </div>
          ) : dataNodes.length === 0 ? (
            <p style={{ color: colors.textMuted, fontSize: "13px", fontStyle: "italic", margin: 0 }}>
              No output rows yet — data will appear as each layer writes to Delta Lake.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
              {dataNodes.map((node) => (
                <DataTable key={node} node={node} nodeData={data[node] as any[]} />
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
