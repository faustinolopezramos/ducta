import type { LogEntry } from "../../store/logsStore";

/**
 * The search box's text as a test on a log message: plain text matches
 * anywhere (case-insensitive); `/pattern/` is a regular expression. An
 * invalid pattern matches nothing and says why.
 */
export function logMatcher(search: string): { test: (message: string) => boolean; error: string | null } {
  const q = search.trim();
  if (!q) return { test: () => true, error: null };
  const re = /^\/(.+)\/([imsu]*)$/.exec(q);
  if (re) {
    try {
      const rx = new RegExp(re[1], re[2].includes("i") ? re[2] : `${re[2]}i`);
      return { test: (m) => rx.test(m), error: null };
    } catch (e) {
      return { test: () => false, error: (e as Error).message };
    }
  }
  const needle = q.toLowerCase();
  return { test: (m) => m.toLowerCase().includes(needle), error: null };
}

/** Consecutive identical lines (same level, node and text) as one, counted. */
export function collapseRepeats(entries: LogEntry[]): (LogEntry & { repeat?: number })[] {
  const out: (LogEntry & { repeat?: number })[] = [];
  for (const e of entries) {
    const last = out[out.length - 1];
    if (last && last.message === e.message && last.level === e.level && last.nodeId === e.nodeId && !e.isNodeStatus) {
      last.repeat = (last.repeat ?? 1) + 1;
    } else {
      out.push({ ...e });
    }
  }
  return out;
}
