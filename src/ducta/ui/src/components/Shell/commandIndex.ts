import { routes } from "../../utils/routes";

export type CommandKind = "command" | "project" | "pipeline" | "node" | "dataset" | "file" | "run";

export interface CommandEntry {
  kind: CommandKind;
  id: string;
  label: string;
  hint?: string;
  /** Where it goes… */
  to?: string;
  /** …or what it does. */
  run?: () => void;
}

export interface CommandSources {
  projectId?: string | null;
  projects?: { id: string; name?: string }[];
  pipelines?: string[];
  nodes?: { node: string; pipeline?: string | null; file?: string | null }[];
  datasets?: { name: string; layer?: string | null }[];
  files?: string[];
  runs?: { id: string; pipeline_name: string; status: string; env?: string }[];
  commands?: CommandEntry[];
}

/** Every place the menu can go and every action it can take, for one project. */
export function buildCommandIndex(s: CommandSources): CommandEntry[] {
  const p = s.projectId;
  const out: CommandEntry[] = [...(s.commands ?? [])];
  for (const project of s.projects ?? []) {
    out.push({ kind: "project", id: `project:${project.id}`, label: project.name ?? project.id, hint: "project", to: routes.project(project.id) });
  }
  if (!p) return out;
  for (const name of s.pipelines ?? []) {
    out.push({ kind: "pipeline", id: `pipeline:${name}`, label: name, hint: "pipeline", to: routes.pipeline(p, name) });
  }
  for (const n of s.nodes ?? []) {
    out.push({
      kind: "node",
      id: `node:${n.node}`,
      label: n.node,
      hint: n.pipeline ?? undefined,
      to: n.pipeline ? routes.node(p, n.pipeline, n.node) : n.file ? routes.code(p, n.file) : undefined,
    });
  }
  for (const d of s.datasets ?? []) {
    out.push({ kind: "dataset", id: `dataset:${d.name}`, label: d.name, hint: d.layer ?? "dataset", to: routes.dataset(p, d.name) });
  }
  for (const f of s.files ?? []) {
    out.push({ kind: "file", id: `file:${f}`, label: f.split("/").pop() ?? f, hint: f, to: routes.code(p, f) });
  }
  for (const r of s.runs ?? []) {
    out.push({
      kind: "run",
      id: `run:${r.id}`,
      label: `${r.pipeline_name} · ${r.status}`,
      hint: `${r.env ?? ""} ${r.id.slice(0, 8)}`.trim(),
      to: routes.run(p, r.id),
    });
  }
  return out;
}

/**
 * How well *query* matches *text*: its letters in order (a subsequence), with
 * a bonus for contiguous runs and for starting a word. -1 when it does not match.
 */
export function fuzzyScore(query: string, text: string): number {
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (!q) return 0;
  const exact = t.indexOf(q);
  if (exact >= 0) return 1000 - exact - (t.length - q.length) * 0.01 + (exact === 0 || /[\s._/:-]/.test(t[exact - 1]) ? 200 : 0);
  let score = 0;
  let ti = 0;
  let run = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, ti);
    if (found < 0) return -1;
    run = found === ti ? run + 1 : 0;
    score += 10 + run * 5 + (found === 0 || /[\s._/:-]/.test(t[found - 1]) ? 8 : 0) - (found - ti) * 0.5;
    ti = found + 1;
  }
  return score;
}

const KIND_ORDER: CommandKind[] = ["command", "pipeline", "node", "dataset", "file", "run", "project"];

/** The best matches, at most *limit*; with no query, commands then pipelines first. */
export function searchCommands(entries: CommandEntry[], query: string, limit = 40): CommandEntry[] {
  const q = query.trim();
  if (!q) {
    return [...entries].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind)).slice(0, limit);
  }
  // ">" narrows to commands, "#" to datasets, "@" to nodes — as in an editor's palette.
  const prefix = { ">": "command", "#": "dataset", "@": "node" }[q[0]] as CommandKind | undefined;
  const needle = prefix ? q.slice(1).trim() : q;
  return entries
    .filter((e) => !prefix || e.kind === prefix)
    .map((e) => ({ e, s: Math.max(fuzzyScore(needle, e.label), fuzzyScore(needle, e.hint ?? "") - 50) }))
    .filter((x) => x.s >= 0)
    .sort((a, b) => b.s - a.s || KIND_ORDER.indexOf(a.e.kind) - KIND_ORDER.indexOf(b.e.kind))
    .slice(0, limit)
    .map((x) => x.e);
}
