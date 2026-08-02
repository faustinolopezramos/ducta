import type { ComponentType } from "react";
import {
  IconCircle,
  IconClock,
  IconLoader2,
  IconCircleCheck,
  IconAlertTriangle,
  IconCircleX,
  IconBan,
  IconPlayerSkipForward,
} from "@tabler/icons-react";
import "./StatusBadge.css";

export type Status =
  | "idle"
  | "pending"
  | "running"
  | "success"
  | "warning"
  | "failed"
  | "cancelled"
  | "skipped";

// Tabler icon components are forwardRef exotics; ComponentType<any> avoids the
// ref-typing friction while keeping a single shared shape for the mapping.
type IconComponent = ComponentType<any>;

interface StatusMeta {
  label: string;
  Icon: IconComponent;
  /** Spin the icon (running). */
  spin?: boolean;
}

/** Canonical mapping: one source of truth for status presentation. */
const STATUS_META: Record<Status, StatusMeta> = {
  idle:      { label: "Idle",      Icon: IconCircle },
  pending:   { label: "Pending",   Icon: IconClock },
  running:   { label: "Running",   Icon: IconLoader2, spin: true },
  success:   { label: "Success",   Icon: IconCircleCheck },
  warning:   { label: "Warning",   Icon: IconAlertTriangle },
  failed:    { label: "Failed",    Icon: IconCircleX },
  cancelled: { label: "Cancelled", Icon: IconBan },
  skipped:   { label: "Skipped",   Icon: IconPlayerSkipForward },
};

/** Map common backend aliases onto the canonical status set. */
const STATUS_ALIASES: Record<string, Status> = {
  active: "running",
  error: "failed",
  succeeded: "success",
  ok: "success",
  done: "success",
  queued: "pending",
  skip: "skipped",
};

export function normalizeStatus(raw: string | null | undefined): Status {
  if (!raw) return "idle";
  const key = raw.toLowerCase();
  if (key in STATUS_META) return key as Status;
  return STATUS_ALIASES[key] ?? "idle";
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
  const text = label ?? meta.label;
  const { Icon } = meta;

  const classes = [
    "tui-status",
    `tui-status--${canonical}`,
    `tui-status--${size}`,
    `tui-status--${variant}`,
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

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
      <Icon className="tui-status__icon" aria-hidden="true" size={size === "sm" ? 12 : 14} />
      <span className="tui-status__label">{text}</span>
    </span>
  );
}
