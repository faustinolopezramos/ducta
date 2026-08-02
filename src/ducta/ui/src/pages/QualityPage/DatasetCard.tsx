import { colors } from "../../theme/tokens";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Sparkline } from "../../components/Quality/Sparkline";
import type { QualityDatasetSummary } from "../../api/qualityApi";
import { formatDate, scoreColor } from "./shared";

// ─────────────────────────────────────────────
// DATASET OVERVIEW GRID
// ─────────────────────────────────────────────

export function DatasetCard({
  item,
  selected,
  onSelect,
}: {
  item: QualityDatasetSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "14px 16px",
        borderRadius: 8,
        border: `1px solid ${selected ? colors.accent : colors.border}`,
        background: selected ? `${colors.accent}08` : colors.surface,
        cursor: "pointer",
        textAlign: "left",
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
        <span
          style={{
            flex: 1,
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            fontWeight: 600,
            color: colors.text,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {item.dataset}
        </span>
        {item.passed != null && (
          <StatusBadge status={item.passed ? "success" : "failed"} size="sm" />
        )}
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 12, width: "100%" }}>
        <span
          style={{
            fontSize: 24,
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            color: scoreColor(item.latest_score),
            lineHeight: 1,
          }}
        >
          {typeof item.latest_score === "number" ? item.latest_score.toFixed(2) : "—"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Sparkline values={item.trend} color={scoreColor(item.latest_score)} />
        </div>
      </div>
      <div style={{ fontSize: 11, color: colors.textMuted }}>
        {item.run_count} run{item.run_count !== 1 ? "s" : ""} · last {formatDate(item.created_at)}
      </div>
    </button>
  );
}
