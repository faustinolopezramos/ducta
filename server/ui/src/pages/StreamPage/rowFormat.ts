/** What a cell of the live table says, and how it is aligned: numbers right, the rest left. */
export interface Cell {
  text: string;
  kind: "num" | "text" | "time" | "bool" | "none";
}

const ISO_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/;

export function formatCell(value: unknown): Cell {
  if (value === null || value === undefined) return { text: "—", kind: "none" };
  if (typeof value === "boolean") return { text: String(value), kind: "bool" };
  if (typeof value === "number") {
    return { text: Number.isInteger(value) ? String(value) : String(Math.round(value * 1e6) / 1e6), kind: "num" };
  }
  if (typeof value === "string") {
    if (ISO_TIME.test(value)) {
      // 2026-11-16T12:14:02.123Z -> 2026-11-16 12:14:02: the second is the finest a stream reader needs.
      return { text: value.replace("T", " ").replace(/(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/, ""), kind: "time" };
    }
    return { text: value, kind: "text" };
  }
  return { text: JSON.stringify(value), kind: "text" };
}

/**
 * One key per row, stable across polls: a row's own content, with a counter for rows that are
 * identical. A new poll reuses the keys of the rows it already had, so only rows that
 * arrived since are mounted (and fade in).
 */
export function rowKeys(rows: Record<string, unknown>[]): string[] {
  const seen = new Map<string, number>();
  return rows.map((row) => {
    const sig = JSON.stringify(row);
    const n = seen.get(sig) ?? 0;
    seen.set(sig, n + 1);
    return `${sig}#${n}`;
  });
}
