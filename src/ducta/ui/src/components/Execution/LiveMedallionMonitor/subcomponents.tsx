import { useState, useEffect, useMemo, memo, type ReactNode } from "react";
import { colors } from "../../../theme/tokens";
import { Button } from "../../ui";
import { layerMeta, formatCell, formatUptime, formatRate } from "./helpers";

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
  const [, forceTick] = useState(0);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => forceTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  const extra = running && syncedAt ? Math.max(0, (Date.now() - syncedAt) / 1000) : 0;
  return <>{formatUptime(baseSeconds + extra)}</>;
});

export const SkeletonCard = memo(function SkeletonCard() {
  return (
    <div style={{ padding: "14px 16px", background: colors.bg, borderRadius: "8px", border: `1px solid ${colors.border}` }}>
      <div style={{ height: "10px", width: "60%", borderRadius: "4px", background: colors.border, marginBottom: "10px" }} />
      <div style={{ height: "22px", width: "40%", borderRadius: "4px", background: colors.border }} />
    </div>
  );
});

export const Gauge = memo(function Gauge({
  label,
  value,
  maxValue,
  color,
}: {
  label: string;
  value: number;
  maxValue: number;
  color: string;
}) {
  const pct = maxValue > 0 ? Math.min(100, (value / maxValue) * 100) : 0;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: colors.textMuted, marginBottom: "5px" }}>
        <span>{label}</span>
        <span style={{ fontWeight: 600, color: colors.text, fontFamily: "var(--font-mono)" }}>
          {value.toFixed(1)} rec/s
        </span>
      </div>
      <div style={{ height: "6px", background: colors.border, borderRadius: "3px", overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: color,
            borderRadius: "3px",
            transition: "width 0.6s ease",
          }}
        />
      </div>
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

export const DataTable = memo(function DataTable({ node, nodeData }: { node: string; nodeData: any[] }) {
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
