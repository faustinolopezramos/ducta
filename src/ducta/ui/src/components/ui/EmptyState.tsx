import type { ComponentType, ReactNode } from "react";
import { colors, styles } from "../../theme/tokens";

interface EmptyStateProps {
  /** Tabler icon component (e.g. IconInbox). Typed loosely to match forwardRef icons. */

  icon?: ComponentType<any>;
  title: string;
  description?: string;
  /** Optional call-to-action(s) rendered below the description. */
  action?: ReactNode;
  /** Vertical padding; "sm" for inline panels, "lg" for full-page. */
  size?: "sm" | "lg";
}

/**
 * Consistent empty-state placeholder: centered icon + title + description + CTA.
 * Replaces the ad-hoc "No X yet…" plain-text blocks scattered across pages.
 */
export function EmptyState({ icon: Icon, title, description, action, size = "lg" }: EmptyStateProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        gap: 10,
        padding: size === "lg" ? "64px 24px" : "32px 16px",
        color: colors.textMuted,
      }}
    >
      {Icon && (
        <div style={{ opacity: 0.4, marginBottom: 2 }}>
          <Icon size={size === "lg" ? 40 : 28} stroke={1} color={colors.textDim} />
        </div>
      )}
      <div style={{ ...styles.fontSans, fontSize: size === "lg" ? 16 : 14, fontWeight: 600, color: colors.text }}>
        {title}
      </div>
      {description && (
        <div style={{ ...styles.fontSans, fontSize: "var(--text-sm)", color: colors.textMuted, maxWidth: 360 }}>
          {description}
        </div>
      )}
      {action && <div style={{ marginTop: 6, display: "flex", gap: 8 }}>{action}</div>}
    </div>
  );
}
