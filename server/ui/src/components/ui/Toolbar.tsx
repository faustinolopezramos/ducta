import type { ReactNode } from "react";
import { cx } from "../../utils/classNames";
import "./Toolbar.css";

export interface ToolbarProps {
  /** Items aligned to the start (left). */
  children?: ReactNode;
  /** Items aligned to the end (right). */
  end?: ReactNode;
  /** Visually separate the bar from content above/below. */
  bordered?: boolean;
  /** Accessible label for the toolbar landmark. */
  "aria-label"?: string;
  className?: string;
}

/**
 * Horizontal action bar with consistent spacing and start/end alignment. Uses
 * `role="toolbar"` so arrow-key navigation and screen-reader grouping work; on
 * narrow viewports the two groups stack instead of overflowing.
 */
export function Toolbar({ children, end, bordered = false, className, ...rest }: ToolbarProps) {
  return (
    <div
      role="toolbar"
      className={cx("tui-toolbar", bordered && "tui-toolbar--bordered", className)}
      {...rest}
    >
      <div className="tui-toolbar__group tui-toolbar__group--start">{children}</div>
      {end && <div className="tui-toolbar__group tui-toolbar__group--end">{end}</div>}
    </div>
  );
}
