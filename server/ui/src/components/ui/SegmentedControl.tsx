import type { ReactNode } from "react";
import { cx } from "../../utils/classNames";
import "./SegmentedControl.css";

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  /** Shown muted after the label (incidents still open, for example). */
  count?: number;
  title?: string;
}

export interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Names the group for screen readers ("Project view"). */
  "aria-label": string;
  className?: string;
}

/**
 * One choice out of a few views or filters: a light track with the current
 * option raised on it. Map/List/Health, By experiment/All runs and
 * Active/Resolved/Ignored each drew this differently (a bordered button, a
 * filled petrol pill, outlined pills); they share this one now.
 *
 * Not for filters that combine (the run status chips): those are toggles, each
 * on or off on its own.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className,
  ...rest
}: SegmentedControlProps<T>) {
  return (
    <div className={cx("tui-segmented", className)} role="group" aria-label={rest["aria-label"]}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={cx("tui-segmented__option", o.value === value && "is-active")}
          aria-pressed={o.value === value}
          title={o.title}
          onClick={() => onChange(o.value)}
        >
          {o.icon}
          <span>{o.label}</span>
          {/* The space keeps the accessible name "Active 2", not "Active2"; a flex
              container does not draw whitespace, so it costs nothing visually. */}
          {o.count != null && <>{" "}<span className="tui-segmented__count">{o.count}</span></>}
        </button>
      ))}
    </div>
  );
}
