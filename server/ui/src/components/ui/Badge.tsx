import type { CSSProperties, ReactNode } from "react";
import { StatusBadge, type Status } from "./StatusBadge";
import "./Badge.css";

interface BadgeProps {
  children: ReactNode;
  status?: "pending" | "running" | "success" | "failed" | "default";
  color?: string;  // For backward compatibility
  style?: CSSProperties;
  className?: string;
}

/**
 * Legacy Badge wrapper — delegates to StatusBadge for semantic status
 * or applies color-mix tokens for custom colored tags.
 * @deprecated Use `StatusBadge` instead for new code.
 */
export function Badge({ children, status = "default", color, style, className = "" }: BadgeProps) {
  if (!color && status !== "default") {
    const mappedStatus = status as Status;
    return <StatusBadge status={mappedStatus} label={String(children)} className={className} style={style} />;
  }

  const bgStyle = color
    ? { background: `color-mix(in srgb, ${color} 15%, transparent)`, color, ...style }
    : style;

  return (
    <span className={`exec-status-badge exec-status-badge-${status} ${className}`.trim()} style={bgStyle}>
      {children}
    </span>
  );
}
