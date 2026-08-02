import { colors } from "../../theme/tokens";
import { useQualityChecks } from "../../api/qualityApi";
import { IconListCheck } from "@tabler/icons-react";
import { card, sectionTitle } from "./shared";

// ─────────────────────────────────────────────
// REGISTERED CHECKS (compact reference)
// ─────────────────────────────────────────────

export function ChecksCard() {
  const { data: checks, isLoading } = useQualityChecks();
  return (
    <div style={card}>
      {sectionTitle(<IconListCheck size={16} color={colors.accent} />, "Registered checks")}
      {isLoading && <p style={{ fontSize: 12, color: colors.textMuted }}>Loading…</p>}
      {checks && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {checks.map((c) => (
            <span
              key={c.name}
              title={`${c.class_name} (${c.origin})`}
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: 4,
                border: `1px solid ${colors.border}`,
                background: c.origin === "built-in" ? "transparent" : `${colors.accent}15`,
                color: colors.text,
              }}
            >
              {c.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
