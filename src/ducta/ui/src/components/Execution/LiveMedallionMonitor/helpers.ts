import { colors } from "../../../theme/tokens";

export const LAYER_HINTS: { match: RegExp; icon: string; color: string }[] = [
  { match: /bronze|raw|ingest|landing|source/i, icon: "📥", color: colors.amber },
  { match: /silver|clean|stage|refine|enrich/i, icon: "✨", color: colors.blue },
  { match: /gold|mart|serve|predict|score|aggregate|feature/i, icon: "🏆", color: colors.purple },
];

export function layerMeta(nodeName: string): { icon: string; color: string } {
  for (const h of LAYER_HINTS) {
    if (h.match.test(nodeName)) return { icon: h.icon, color: h.color };
  }
  return { icon: "🔁", color: colors.primary };
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "object") {
    try { return JSON.stringify(value); } catch { return String(value); }
  }
  return String(value);
}

export function statusColor(status?: string): string {
  switch (status) {
    case "running":        return colors.green;
    case "starting":       return colors.blue;
    case "partial_failure": return colors.amber;
    case "error":          return colors.red;
    case "stopped":        return colors.textMuted;
    default:               return colors.textMuted;
  }
}

export function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function formatRate(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k rec/s`;
  return `${value.toFixed(value >= 10 ? 0 : 1)} rec/s`;
}

export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) + "…" : id;
}
