import type React from "react";
import { IconX } from "@tabler/icons-react";

/**
 * The inspector: the selected object first, then what it reads and writes,
 * then its neighbours. It docks to the right of the canvas, so the graph — and
 * the lineage lens lighting up the selection's path — stays fully in view.
 * `tabs` sits in its header; the body is whichever view is selected.
 */
export function FocusPanel({
  label,
  onClose,
  tabs,
  children,
}: {
  label: string;
  onClose: () => void;
  tabs?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <aside className="focus-sheet" aria-label={label} data-no-pan>
      <div className="focus-head">
        <div className="focus-head-tabs">{tabs}</div>
        <button type="button" className="focus-close" onClick={onClose} aria-label="Close inspector (Esc)">
          <IconX size={16} />
        </button>
      </div>
      <div className="focus-bowtie">{children}</div>
    </aside>
  );
}

/** One side of the bow-tie. `from`/`to` are the neighbours, `in`/`out` the data. */
export function FocusColumn({
  label,
  side,
  count,
  children,
}: {
  label: string;
  side: "from" | "in" | "out" | "to";
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className={`focus-col focus-col--${side}`}>
      <h4 className="focus-col-label">
        {label}
        {count != null && count > 0 && <span className="inspector-section-count">{count}</span>}
      </h4>
      <div className="focus-col-items">{children}</div>
    </section>
  );
}
