import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "./Button";
import { ICONS } from "../icons";
import { colors, styles } from "../../theme/tokens";

export interface PageHeaderProps {
  title: string;
  description?: string;
  backTo?: string;
  backLabel?: string;
  actions?: ReactNode;
}

export function PageHeader({
  title,
  description,
  backTo,
  backLabel = "Back",
  actions,
}: PageHeaderProps) {
  const navigate = useNavigate();
  return (
    <div style={{ marginBottom: 32 }}>
      {backTo && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(backTo)}
          style={{ marginBottom: 16 }}
        >
          {ICONS.BACK} {backLabel}
        </Button>
      )}
      <div className="page-header__content" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
        <div className="page-header__copy">
          <h1 style={{ ...styles.fontSans, margin: "0 0 6px", fontSize: 26, fontWeight: 700, color: colors.text }}>
            {title}
          </h1>
          {description && (
            <p style={{ ...styles.fontSans, margin: 0, fontSize: 13, color: colors.textMuted }}>
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="page-header__actions" style={{ display: "flex", gap: 8, flexShrink: 0 }}>
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
