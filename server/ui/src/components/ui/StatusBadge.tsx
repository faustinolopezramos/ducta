import { cx } from "../../utils/classNames";
import { STATUS_META, statusMetaFor, type Status, type StatusTone } from "./statusMeta";
import "./StatusBadge.css";

// Re-export so existing `import { type Status } from "./StatusBadge"` consumers
// keep working — the canonical status domain now lives in ./statusMeta.
export type { Status };

/**
 * The subset of the shared status domain that StatusBadge actually renders as
 * a pill: each has a dedicated `--status-*` CSS token block in StatusBadge.css.
 * Everything else in the shared `Status` union (e.g. "error", "starting") is a
 * raw value other consumers (the log viewer, the streaming monitor) see
 * directly; StatusBadge folds those down to one of these eight via aliasing
 * rather than growing new CSS for every raw backend string.
 */
type BadgeStatus =
  | "idle"
  | "pending"
  | "running"
  | "success"
  | "warning"
  | "failed"
  | "cancelled"
  | "skipped";

const BADGE_STATUSES = new Set<BadgeStatus>([
  "idle", "pending", "running", "success", "warning", "failed", "cancelled", "skipped",
]);

function isBadgeStatus(key: string): key is BadgeStatus {
  return BADGE_STATUSES.has(key as BadgeStatus);
}

/** Map backend aliases (and the shared domain's non-pill statuses) onto the
 *  eight canonical badge statuses. */
const STATUS_ALIASES: Record<string, BadgeStatus> = {
  active: "running",
  starting: "running",
  error: "failed",
  partial_failure: "warning",
  stopped: "cancelled",
  succeeded: "success",
  ok: "success",
  done: "success",
  queued: "pending",
  skip: "skipped",
  completed: "success",
  // A quality gate stopped the run: it finished, but did not do all its work.
  gate_blocked: "warning",
};

export function normalizeStatus(raw: string | null | undefined): BadgeStatus {
  if (!raw) return "idle";
  const key = raw.toLowerCase();
  if (isBadgeStatus(key)) return key;
  return STATUS_ALIASES[key] ?? "idle";
}

/** Coarse severity of any raw status, for pills and row accents. */
export function statusTone(raw: string | null | undefined): StatusTone {
  return statusMetaFor(raw)?.tone ?? STATUS_META[normalizeStatus(raw)].tone;
}

export interface StatusBadgeProps {
  status: Status | string;
  /** Override the default human label. */
  label?: string;
  size?: "sm" | "md";
  /** Subtle dot only, no pill background. */
  variant?: "solid" | "subtle" | "dot";
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Accessible status indicator. Conveys state via icon + text + color so it never
 * relies on color alone (WCAG 1.4.1). Colors come from the --status-* tokens, so
 * a single change in tokens.css restyles every status across the app.
 */
export function StatusBadge({
  status,
  label,
  size = "md",
  variant = "subtle",
  className,
  style,
}: StatusBadgeProps) {
  const canonical = normalizeStatus(status);
  const meta = STATUS_META[canonical];
  // The raw status's own label when it has one ("Gate blocked"), not the
  // label of the pill style it folds into ("Warning").
  const text = label ?? statusMetaFor(status)?.label ?? meta.label;
  const { Icon } = meta;

  const classes = cx(
    "tui-status",
    `tui-status--${canonical}`,
    `tui-status--${size}`,
    `tui-status--${variant}`,
    className,
  );

  if (variant === "dot") {
    return (
      <span className={classes} title={`${text} (${canonical})`} style={style}>
        <span className="tui-status__dot" aria-hidden="true" />
        <span className="tui-status__sr-only">{text}</span>
      </span>
    );
  }

  return (
    <span className={classes} style={style}>
      <Icon
        className={cx("tui-status__icon", meta.spin && "tui-status__icon--spin")}
        aria-hidden="true"
        size={size === "sm" ? 12 : 14}
      />
      <span className="tui-status__label">{text}</span>
    </span>
  );
}
