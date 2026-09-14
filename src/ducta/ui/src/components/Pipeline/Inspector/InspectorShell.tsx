import type React from "react";
import { IconX } from "@tabler/icons-react";

/**
 * The anatomy both inspectors share: identity header, tabulated sections,
 * actions at the foot. Selecting a node and selecting a dataset open panels
 * that look and work the same, so switching object costs no relearning.
 */
export function InspectorShell({
  title,
  titleMono = false,
  subtitle,
  pills,
  onClose,
  children,
  actions,
  ariaLabel,
}: {
  title: string;
  titleMono?: boolean;
  subtitle?: React.ReactNode;
  pills?: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  actions?: React.ReactNode;
  ariaLabel: string;
}) {
  return (
    <aside aria-label={ariaLabel} className="inspector" data-no-pan>
      <header className="inspector-head">
        <div className="inspector-title-group">
          <h3 className={`inspector-title${titleMono ? " mono" : ""}`}>{title}</h3>
          {subtitle && <p className="inspector-subtitle">{subtitle}</p>}
          {pills && <div className="inspector-pills">{pills}</div>}
        </div>
        <button className="inspector-close" onClick={onClose} aria-label="Close panel">
          <IconX size={16} />
        </button>
      </header>

      <div className="inspector-body">{children}</div>

      {actions && <div className="inspector-actions">{actions}</div>}
    </aside>
  );
}

export function Section({
  label,
  count,
  children,
}: {
  label: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="inspector-section">
      <h4 className="inspector-section-label">
        {label}
        {count != null && <span className="inspector-section-count">{count}</span>}
      </h4>
      {children}
    </section>
  );
}

/**
 * A label/value list. Values are monospaced by default because most of them are
 * identifiers, paths or formats; `plain` opts a prose value out.
 */
export function KeyValues({ rows }: { rows: Array<KeyValueRow> }) {
  return (
    <dl className="inspector-kv">
      {rows.map((row) => (
        <div className="inspector-kv-row" key={row.label}>
          <dt>{row.label}</dt>
          <dd
            className={[
              row.plain ? "plain" : "",
              row.value == null ? "absent" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            title={typeof row.value === "string" ? row.value : undefined}
          >
            {/* "not declared" is the useful answer: it points at the config
                that needs fixing, where a dash or a fake default does not. */}
            {row.value ?? row.absent ?? "not declared"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export interface KeyValueRow {
  label: string;
  value: React.ReactNode | null;
  /** Render in the sans stack instead of mono — for prose, not identifiers. */
  plain?: boolean;
  /** Override the "not declared" placeholder for a null value. */
  absent?: string;
}

export function Pill({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "bronze" | "silver" | "gold" | "ok" | "warn" | "bad" | "neutral";
}) {
  return <span className={`inspector-pill${tone ? ` tone-${tone}` : ""}`}>{children}</span>;
}
