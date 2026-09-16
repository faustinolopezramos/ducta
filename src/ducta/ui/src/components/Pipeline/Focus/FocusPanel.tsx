import type React from "react";
import { IconX } from "@tabler/icons-react";

/**
 * The focus sheet: the selected object in the middle, what flows into it on the
 * left, what flows out of it on the right. It docks along the bottom of the
 * canvas, so the graph — and the lineage lens lighting up the selection's path —
 * stays in view above it, in either orientation.
 */
export function FocusPanel({
  label,
  onClose,
  children,
}: {
  label: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <aside className="focus-sheet" aria-label={label} data-no-pan>
      <button type="button" className="focus-close" onClick={onClose} aria-label="Close focus (Esc)">
        <IconX size={16} />
      </button>
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
