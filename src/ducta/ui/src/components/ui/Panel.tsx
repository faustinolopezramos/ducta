import type { ReactNode } from "react";
import { cx } from "../../utils/classNames";
import "./Panel.css";

export interface PanelProps {
  children: ReactNode;
  /** Optional header title. */
  title?: ReactNode;
  /** Optional sub-text under the title. */
  description?: ReactNode;
  /** Actions rendered at the end of the header row. */
  actions?: ReactNode;
  /** Remove inner padding (e.g. for tables / canvases that bleed to the edge). */
  flush?: boolean;
  /** Elevation level. `flat` = border only (default), `raised` = shadow. */
  elevation?: "flat" | "raised";
  as?: "section" | "div" | "article";
  className?: string;
  /** Labelled region for assistive tech when there is no visible title. */
  "aria-label"?: string;
}

/**
 * Surface container with an optional header. The default `section` element plus
 * a heading gives screen-reader users a navigable landmark; pass `aria-label`
 * when there is no visible `title`.
 */
export function Panel({
  children,
  title,
  description,
  actions,
  flush = false,
  elevation = "flat",
  as: Tag = "section",
  className,
  ...rest
}: PanelProps) {
  const classes = cx("tui-panel", `tui-panel--${elevation}`, flush && "tui-panel--flush", className);

  const hasHeader = title || actions || description;

  return (
    <Tag className={classes} {...rest}>
      {hasHeader && (
        <header className="tui-panel__header">
          <div className="tui-panel__heading">
            {title && <h2 className="tui-panel__title">{title}</h2>}
            {description && <p className="tui-panel__desc">{description}</p>}
          </div>
          {actions && <div className="tui-panel__actions">{actions}</div>}
        </header>
      )}
      <div className="tui-panel__body">{children}</div>
    </Tag>
  );
}
