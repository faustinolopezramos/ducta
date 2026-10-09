import React, { useMemo } from "react";
import { Modal } from "../ui/Modal";
import { colors } from "../../theme/tokens";
import { lastMetricValues, type ExperimentRun } from "../../api/mlopsApi";

/** Metric keys where a smaller value wins (loss-like); everything else is higher-better. */
const LOWER_IS_BETTER = /loss|error|rmse|mae|mse|rps|brier|deviance/i;

/**
 * Side-by-side comparison of the selected runs' final metric values, with the
 * best value per metric highlighted. Differing parameters are shown below so
 * users can attribute metric deltas to hyperparameter changes.
 */
export function RunCompareModal({
  runs,
  onClose,
}: {
  runs: ExperimentRun[];
  onClose: () => void;
}) {
  const metricsPerRun = useMemo(() => runs.map(lastMetricValues), [runs]);
  const metricKeys = useMemo(
    () => [...new Set(metricsPerRun.flatMap((m) => Object.keys(m)))].sort(),
    [metricsPerRun]
  );

  const paramKeys = useMemo(() => {
    const all = [...new Set(runs.flatMap((r) => Object.keys(r.parameters ?? {})))].sort();
    // Only show parameters that actually differ between the selected runs.
    return all.filter((k) => {
      const vals = runs.map((r) => JSON.stringify(r.parameters?.[k]));
      return new Set(vals).size > 1;
    });
  }, [runs]);

  const bestIndex = (key: string): number => {
    const values = metricsPerRun.map((m) => m[key]);
    const defined = values
      .map((v, i) => ({ v, i }))
      .filter((x): x is { v: number; i: number } => typeof x.v === "number");
    if (defined.length < 2) return -1;
    const lower = LOWER_IS_BETTER.test(key);
    return defined.reduce((best, cur) =>
      lower ? (cur.v < best.v ? cur : best) : cur.v > best.v ? cur : best
    ).i;
  };

  const th: React.CSSProperties = {
    textAlign: "left",
    padding: "6px 10px",
    fontWeight: 600,
    fontSize: "var(--text-2xs)",
    color: colors.textMuted,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  };
  const td: React.CSSProperties = {
    padding: "6px 10px",
    fontFamily: "var(--font-mono)",
    fontSize: "var(--text-xs)",
    color: colors.text,
  };

  const table = (title: string, keys: string[], value: (key: string, runIdx: number) => React.ReactNode) => (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: "0 0 8px", fontSize: "var(--text-xs)", fontWeight: 600, color: colors.textMuted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {title}
      </h3>
      {keys.length === 0 ? (
        <p style={{ margin: 0, fontSize: "var(--text-xs)", color: colors.textMuted }}>
          {title === "Metrics" ? "No metrics recorded on these runs." : "No differing parameters."}
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>{title === "Metrics" ? "Metric" : "Parameter"}</th>
                {runs.map((r) => (
                  <th key={r.run_id} style={{ ...th, fontFamily: "var(--font-mono)", textTransform: "none" }}>
                    {r.name ?? r.run_id.slice(0, 8)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key} style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td style={{ ...td, color: colors.textMuted }}>{key}</td>
                  {runs.map((_, i) => (
                    <td key={i} style={td}>
                      {value(key, i)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <Modal title={`Compare ${runs.length} runs`} onClose={onClose} width={720}>
      {table("Metrics", metricKeys, (key, i) => {
        const v = metricsPerRun[i][key];
        if (typeof v !== "number") return <span style={{ color: colors.textDim }}>—</span>;
        const best = bestIndex(key) === i;
        return (
          <span
            style={{
              fontWeight: best ? 700 : 400,
              color: best ? "var(--success)" : colors.text,
            }}
            title={best ? `Best ${key} of the selection` : undefined}
          >
            {v.toFixed(6).replace(/\.?0+$/, "")}
            {best ? " ★" : ""}
          </span>
        );
      })}

      {table("Differing parameters", paramKeys, (key, i) => {
        const v = runs[i].parameters?.[key];
        return v === undefined ? <span style={{ color: colors.textDim }}>—</span> : String(v);
      })}

      <p style={{ margin: 0, fontSize: "var(--text-2xs)", color: colors.textDim }}>
        Best value per metric is highlighted (metrics matching loss/error/rmse/… count lower as better).
      </p>
    </Modal>
  );
}
