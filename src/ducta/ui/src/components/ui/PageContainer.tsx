import type { CSSProperties, ReactNode } from "react";

export interface PageContainerProps {
  children: ReactNode;
  /** Constrain width for form-shaped pages (Quality, Ingestion, ...).
   *  Omit for full-width pages (tables, dashboards). */
  maxWidth?: number;
  style?: CSSProperties;
}

/**
 * The page body's root container: `var(--space-6)` padding, everything else
 * left to the page. Pages used to each pick their own padding/maxWidth by
 * hand — 24px+960px here, 24px+900px there, "36px 48px" full-width
 * elsewhere — with no discernible reason for the differences. This is the
 * one shape; `maxWidth` is the only per-page knob.
 */
export function PageContainer({ children, maxWidth, style }: PageContainerProps) {
  return (
    <div
      style={{
        padding: "var(--space-6)",
        maxWidth,
        marginLeft: maxWidth ? "auto" : undefined,
        marginRight: maxWidth ? "auto" : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
