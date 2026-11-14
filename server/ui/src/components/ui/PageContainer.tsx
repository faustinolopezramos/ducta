import type { CSSProperties, ReactNode } from "react";
import "./PageContainer.css";

export interface PageContainerProps {
  children: ReactNode;
  /**
   * Constrain width for form-shaped pages (Quality, Ingestion, Schedules).
   * Omit for full-width pages (tables, dashboards).
   */
  maxWidth?: number;
  /**
   * Let the page own the full height of the content area instead of flowing.
   * Only for pages whose body is itself a pane — a canvas, a split view — and
   * which therefore scroll their own regions.
   */
  fill?: boolean;
  className?: string;
  style?: CSSProperties;
}

/**
 * The page body's root container.
 *
 * One padding for every module. Pages used to each pick their own — 24px here,
 * `36px 48px` there, `24px 24px 0` plus a second `24` elsewhere — with no
 * reason for the differences, so the app read as five apps.
 *
 * It deliberately does *not* scroll. `.ducta-content` (see theme/layout.css) is
 * already the scroll region; the pages that added `flex: 1; overflow-y: auto`
 * of their own were nesting a second scroller inside it, which is what made
 * some pages scroll their header away and others not.
 */
export function PageContainer({
  children,
  maxWidth,
  fill = false,
  className,
  style,
}: PageContainerProps) {
  return (
    <div
      className={["page-container", fill ? "page-container--fill" : "", className]
        .filter(Boolean)
        .join(" ")}
      style={{ maxWidth, ...style }}
    >
      {children}
    </div>
  );
}
