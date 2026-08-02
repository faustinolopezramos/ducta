import { useRef, type ReactNode } from "react";
import { colors, styles } from "../../theme/tokens";
import { ICONS } from "../icons";
import { useDialogA11y } from "../../hooks/useDialogA11y";

interface SlidePanelProps {
  title?: ReactNode;
  /** Extra controls rendered in the header, left of the close button. */
  headerActions?: ReactNode;
  onClose: () => void;
  /** CSS width (clamped to viewport). Default 600px. */
  width?: number | string;
  /** Render a dimming overlay behind the panel. Default false (non-blocking). */
  overlay?: boolean;
  children: ReactNode;
}

/**
 * Right-side slide-in drawer with accessible dialog semantics: Esc-to-close,
 * focus trap, restore focus on unmount, role="dialog" + aria-modal. Replaces the
 * ad-hoc `position: fixed` drawers that duplicated this logic per page.
 */
export function SlidePanel({
  title,
  headerActions,
  onClose,
  width = 600,
  overlay = false,
  children,
}: SlidePanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogA11y(panelRef, onClose);

  const widthValue = typeof width === "number" ? `min(${width}px, 90vw)` : width;

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === "string" ? title : "Panel"}
      tabIndex={-1}
      style={{
        position: "fixed",
        right: 0,
        top: 0,
        bottom: 0,
        width: widthValue,
        background: colors.bg,
        borderLeft: `1px solid ${colors.border}`,
        display: "flex",
        flexDirection: "column",
        zIndex: 200,
        boxShadow: "-4px 0 20px rgba(0,0,0,0.15)",
        animation: "slideInRight 0.2s ease-out",
        outline: "none",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 16px",
          background: colors.surface,
          borderBottom: `1px solid ${colors.border}`,
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>{title}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          {headerActions}
          <button
            onClick={onClose}
            aria-label="Close panel"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: colors.textDim,
              fontSize: 16,
              display: "flex",
              alignItems: "center",
              padding: 4,
              ...styles.fontMono,
            }}
          >
            {ICONS.CLOSE}
          </button>
        </div>
      </div>
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {children}
      </div>
    </div>
  );

  if (!overlay) return panel;

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", zIndex: 199 }}
      />
      {panel}
    </>
  );
}
