import type React from "react";
import { colors } from "../../theme/tokens";

// ─────────────────────────────────────────────
// SHARED STYLES
// ─────────────────────────────────────────────

export const label: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  color: colors.textMuted,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  marginBottom: 4,
};

export const input: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  borderRadius: 6,
  border: `1px solid ${colors.border}`,
  background: colors.bg,
  color: colors.text,
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  outline: "none",
};

export function sectionTitle(icon: React.ReactNode, text: string) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
      {icon}
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: colors.text }}>{text}</h2>
    </div>
  );
}


export function scoreColor(score?: number | null): string {
  if (typeof score !== "number") return colors.textMuted;
  if (score >= 0.9) return "var(--success)";
  if (score >= 0.7) return "var(--warning)";
  return "var(--danger)";
}
