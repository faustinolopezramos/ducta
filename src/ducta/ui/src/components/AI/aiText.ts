import { useEffect, useState } from "react";
import type { AIDocsGaps } from "../../api/aiApi";

/** "42 s", "2 min 05 s" since *startedAt*, ticking while *active*; "" when not active. */
export function useElapsed(startedAt: string | undefined, active: boolean): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  const since = startedAt ? Date.parse(startedAt) : NaN;
  if (!active || Number.isNaN(since)) return "";
  const s = Math.max(0, Math.round((now - since) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "3 datasets, 1 pipeline and 2 nodes have no description." */
export function gapsSentence(g: AIDocsGaps): string {
  const parts = [
    g.datasets && plural(g.datasets, "dataset", "datasets"),
    g.pipelines && plural(g.pipelines, "pipeline", "pipelines"),
    g.nodes && plural(g.nodes, "node", "nodes"),
  ].filter(Boolean) as string[];
  if (parts.length === 0) return "Everything has a description.";
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}` : parts[0];
  const total = g.datasets + g.pipelines + g.nodes;
  return `${list} ${total === 1 ? "has" : "have"} no description.`;
}
