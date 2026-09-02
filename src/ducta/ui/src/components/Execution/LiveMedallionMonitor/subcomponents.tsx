import { useState, useEffect, useMemo, memo, type ReactNode } from "react";
import { colors } from "../../../theme/tokens";
import { Button, Skeleton } from "../../ui";
import { layerMeta, formatCell, formatUptime, formatRate, VERDICT_META } from "./helpers";
import type { RateSample, ThroughputVerdict } from "./types";
import { Sparkline } from "../../Quality/Sparkline";

export const StatCard = memo(function StatCard({
  label,
  color = colors.text,
  sub,
  children,
}: {
  label: string;
  color?: string;
  sub?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div style={{ padding: "14px 16px", background: colors.bg, borderRadius: "8px", border: `1px solid ${colors.border}` }}>
      <span style={{ fontSize: "11px", color: colors.textMuted, textTransform: "uppercase", letterSpacing: "0.4px" }}>
        {label}
      </span>
      <div style={{ display: "flex", alignItems: "baseline", gap: "4px", marginTop: "6px" }}>
        <p style={{ fontSize: "22px", fontWeight: 700, margin: 0, color }}>{children}</p>
        {sub && <span style={{ fontSize: "13px", color: colors.textMuted, fontWeight: 500 }}>{sub}</span>}
      </div>
    </div>
  );
});

/**
 * Self-ticking uptime display. Re-renders only itself once per second, so the
 * counter stays live between polls (which can be 15s apart once the pipeline
 * reaches a terminal state) without re-rendering the whole monitor.
 */
export const UptimeTicker = memo(function UptimeTicker({
  baseSeconds,
  syncedAt,
  running,
}: {
  baseSeconds: number;
  syncedAt: number | null;
  running: boolean;
}) {
  // The clock is sampled in the tick, not read during render: reading
  // `Date.now()` in a render body is impure, and this component already had a
  // once-a-second tick to hang it off.
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  const extra = running && syncedAt ? Math.max(0, (now - syncedAt) / 1000) : 0;
  return <>{formatUptime(baseSeconds + extra)}</>;
});

export const SkeletonCard = memo(function SkeletonCard() {
  return (
    <div style={{ padding: "14px 16px", background: colors.bg, borderRadius: "8px", border: `1px solid ${colors.border}` }}>
      <div style={{ marginBottom: "10px" }}>
        <Skeleton variant="text" width="60%" />
      </div>
      <Skeleton variant="text" width="40%" height="22px" />
    </div>
  );
});

export const pulseKeyframes = `
@keyframes lmm-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.45; }
}
`;

export function PulsingDot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: "7px",
        height: "7px",
        borderRadius: "50%",
        background: color,
        animation: "lmm-pulse 1.4s ease-in-out infinite",
        flexShrink: 0,
      }}
    />
  );
}

/**
 * The monitor's headline reading: how fast records are being processed, how
 * that has moved over the last minute, and whether it is keeping up with what
 * is arriving.
 *
 * This replaces two same-scaled bars plus two percentages. The pair of bars
 * showed arrival and processing as unrelated quantities when the whole question
 * is the relationship between them, and the percentages — a hardcoded-green
 * "efficiency" and a "health score" that restated the failure count — carried
 * no information the rest of the panel did not already give.
 */
export const ThroughputPanel = memo(function ThroughputPanel({
  input,
  processed,
  efficiency,
  verdict,
  history,
  scale,
  live,
}: {
  input: number;
  processed: number;
  efficiency?: number;
  verdict: ThroughputVerdict;
  history: RateSample[];
  scale: number;
  live: boolean;
}) {
  const meta = VERDICT_META[verdict];
  const trend = history.map((s) => s.processed);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: "12px" }}>
        <div>
          <div style={{ fontSize: "11px", color: colors.textMuted, textTransform: "uppercase", letterSpacing: "0.4px" }}>
            Processing
          </div>
          <div
            style={{ fontSize: "26px", fontWeight: 700, color: colors.text, fontFamily: "var(--font-mono)", lineHeight: 1.2 }}
          >
            {formatRate(processed)}
          </div>
        </div>

        {trend.length > 1 && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "2px" }}>
            <Sparkline
              values={trend}
              width={140}
              height={34}
              color={meta.color}
              domain={[0, scale]}
              ariaLabel={`Processing rate over the last minute, latest ${formatRate(processed)}`}
            />
            <span style={{ fontSize: "10px", color: colors.textMuted }}>last 60s</span>
          </div>
        )}
      </div>

      {/* Verdict — the reason this panel exists. */}
      <div
        title={meta.hint}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "8px 10px",
          borderRadius: "8px",
          background: `color-mix(in srgb, ${meta.color} 10%, transparent)`,
          border: `1px solid color-mix(in srgb, ${meta.color} 30%, transparent)`,
        }}
      >
        {live && verdict !== "idle" && <PulsingDot color={meta.color} />}
        <span style={{ fontSize: "12px", fontWeight: 700, color: meta.color }}>{meta.label}</span>
        <span style={{ fontSize: "11px", color: colors.textMuted }}>{meta.hint}</span>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px" }}>
        <span style={{ color: colors.textMuted }}>Arriving</span>
        <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: colors.text }}>
          {formatRate(input)}
        </span>
      </div>

      {efficiency !== undefined && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px", paddingTop: "4px", borderTop: `1px solid ${colors.border}` }}>
          <span style={{ color: colors.textMuted }}>Processed vs arriving</span>
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: meta.color }}>
            {efficiency.toFixed(0)}%
          </span>
        </div>
      )}
    </div>
  );
});

export const NodeCard = memo(function NodeCard({
  name,
  active,
  error,
  rate,
  onRestart,
  isRestarting
}: {
  name: string;
  active: boolean;
  error?: string;
  rate?: number;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { icon, color } = useMemo(() => layerMeta(name), [name]);
  const borderColor = error ? colors.red : active ? color : colors.border;
  const bg = error ? `${colors.red}0D` : active ? `${color}0D` : "transparent";

  return (
    <div
      style={{
        minWidth: "160px",
        padding: "14px 16px",
        borderRadius: "10px",
        border: `1.5px solid ${borderColor}`,
        background: bg,
        textAlign: "center",
        transition: "border-color 0.3s ease, background 0.3s ease",
        position: "relative",
      }}
    >
      <div style={{ fontSize: "22px", lineHeight: 1 }}>{icon}</div>
      <h4
        style={{
          fontSize: "12px",
          fontWeight: 600,
          margin: "8px 0 6px 0",
          color: colors.text,
          wordBreak: "break-word",
          lineHeight: 1.3,
        }}
      >
        {name}
      </h4>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "5px" }}>
        {active && <PulsingDot color={color} />}
        <span
          style={{
            fontSize: "10px",
            fontWeight: 700,
            textTransform: "uppercase",
            color: error ? colors.red : active ? color : colors.textMuted,
          }}
        >
          {error ? "Failed" : active ? "Active" : "Inactive"}
        </span>
      </div>

      {active && rate !== undefined && (
        <div style={{ marginTop: "6px", fontSize: "10px", fontFamily: "var(--font-mono)", color: colors.textMuted }}>
          {formatRate(rate)}
        </div>
      )}

      {error && (
        <div style={{ marginTop: "10px", display: "flex", flexDirection: "column", gap: "5px" }}>
           <p style={{ fontSize: "10px", color: colors.red, margin: 0, maxHeight: "40px", overflow: "hidden", textOverflow: "ellipsis" }} title={error}>
             {error}
           </p>
           {onRestart && (
             <Button
               variant="ghost"
               size="sm"
               onClick={onRestart}
               disabled={isRestarting}
               style={{ fontSize: "10px", padding: "2px 6px", height: "auto" }}
             >
               {isRestarting ? "Restarting..." : "Restart Node"}
             </Button>
           )}
        </div>
      )}
    </div>
  );
});

export const RecordPreviewTable = memo(function RecordPreviewTable({ node, nodeData }: { node: string; nodeData: any[] }) {
  const rows = nodeData ?? [];
  const { icon, color } = useMemo(() => layerMeta(node), [node]);

  // Collect columns from up to first 10 rows, cap at 8 cols
  const columns = useMemo(() => Array.from(
    rows.slice(0, 10).reduce((set: Set<string>, r) => {
      Object.keys(r ?? {}).forEach((k) => set.add(k));
      return set;
    }, new Set<string>()),
  ).slice(0, 8), [rows]);

  if (rows.length === 0) return null;

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          marginBottom: "8px",
        }}
      >
        <span>{icon}</span>
        <span style={{ fontSize: "13px", fontWeight: 600, color: colors.text }}>
          {node}
        </span>
        <span
          style={{
            fontSize: "11px",
            color: colors.textMuted,
            background: colors.grayA12,
            padding: "1px 7px",
            borderRadius: "10px",
          }}
        >
          {rows.length} rows
        </span>
        <span
          style={{
            fontSize: "10px",
            fontWeight: 700,
            textTransform: "uppercase",
            color,
          }}
        >
          ● live
        </span>
      </div>

      <div style={{ overflowX: "auto", border: `1px solid ${colors.border}`, borderRadius: "8px" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
          <thead>
            <tr>
              {columns.map((c) => (
                <th
                  key={c}
                  style={{
                    textAlign: "left",
                    padding: "8px 12px",
                    color: colors.textMuted,
                    fontWeight: 600,
                    borderBottom: `1px solid ${colors.border}`,
                    whiteSpace: "nowrap",
                    background: colors.bg,
                    fontSize: "11px",
                    textTransform: "uppercase",
                    letterSpacing: "0.3px",
                  }}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 10).map((row, ri) => (
              <tr
                key={ri}
                style={{ background: ri % 2 === 1 ? colors.bg : "transparent" }}
              >
                {columns.map((c) => (
                  <td
                    key={c}
                    style={{
                      padding: "6px 12px",
                      color: colors.text,
                      borderBottom: ri < rows.length - 1 ? `1px solid ${colors.border}` : "none",
                      whiteSpace: "nowrap",
                      maxWidth: "240px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      fontFamily: "var(--font-mono)",
                      fontSize: "11px",
                    }}
                  >
                    {formatCell(row?.[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});
