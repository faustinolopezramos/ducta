import type { CanvasPort, DagCanvasItem } from "./types";

export const GROUP_PREFIX = "group:";

/** A node's group: its namespace — everything before the last dot (`silver.clean_x` → `silver`). */
export function groupKey(id: string): string | null {
  const i = id.lastIndexOf(".");
  return i > 0 ? id.slice(0, i) : null;
}

/** Namespaces with at least two nodes — the ones worth collapsing. */
export function groupsOf(items: DagCanvasItem[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const item of items) {
    const key = groupKey(item.id);
    if (key) out.set(key, [...(out.get(key) ?? []), item.id]);
  }
  for (const [k, ids] of out) if (ids.length < 2) out.delete(k);
  return out;
}

const RANK = ["failed", "error", "gate_blocked", "running", "queued", "pending", "skipped", "success", "completed"];

/** A group's state: the worst of its members' (a failure anywhere is the group's failure). */
export function worstState(states: (string | undefined)[]): string | undefined {
  const present = states.filter((s): s is string => !!s);
  if (present.length === 0) return undefined;
  return present.sort((a, b) => (RANK.indexOf(a) + 1 || 99) - (RANK.indexOf(b) + 1 || 99))[0];
}

/**
 * The canvas with each collapsed group drawn as one box: it reads what its
 * members read from outside the group, writes what leaves it, and depends on
 * what they depend on outside. Edges inside a group disappear with it.
 */
export function collapseGroups(items: DagCanvasItem[], collapsed: ReadonlySet<string>): DagCanvasItem[] {
  const groups = groupsOf(items);
  const memberOf = new Map<string, string>();
  for (const [key, ids] of groups) if (collapsed.has(key)) for (const id of ids) memberOf.set(id, GROUP_PREFIX + key);
  if (memberOf.size === 0) return items;

  const out: DagCanvasItem[] = [];
  const built = new Map<string, DagCanvasItem>();
  for (const item of items) {
    const group = memberOf.get(item.id);
    const remapDeps = (deps: string[]) =>
      [...new Set(deps.map((d) => memberOf.get(d) ?? d))].filter((d) => d !== (group ?? item.id));
    if (!group) {
      out.push({ ...item, dependsOn: remapDeps(item.dependsOn ?? []) });
      continue;
    }
    let box = built.get(group);
    if (!box) {
      const key = group.slice(GROUP_PREFIX.length);
      box = { id: group, name: `${key}.*`, type: "group", members: [] as string[], inputs: [], outputs: [], dependsOn: [], pipeline: item.pipeline };
      built.set(group, box);
      out.push(box);
    }
    box.members.push(item.id);
    box.dependsOn = remapDeps([...box.dependsOn, ...(item.dependsOn ?? [])]);
  }
  // Ports: what crosses the group's border.
  for (const box of built.values()) {
    const members = items.filter((i) => box.members.includes(i.id));
    const written = new Set(members.flatMap((m) => (m.outputs ?? []).map((p: CanvasPort) => p.name)));
    const readInside = new Set(members.flatMap((m) => (m.inputs ?? []).map((p: CanvasPort) => p.name)));
    const readOutside = new Set(
      items.filter((i) => !box.members.includes(i.id)).flatMap((i) => (i.inputs ?? []).map((p: CanvasPort) => p.name)),
    );
    const uniq = (ports: CanvasPort[]) => [...new Map(ports.map((p) => [p.name, p])).values()];
    box.inputs = uniq(members.flatMap((m) => (m.inputs ?? []).filter((p: CanvasPort) => !written.has(p.name))));
    box.outputs = uniq(
      members.flatMap((m) => (m.outputs ?? []).filter((p: CanvasPort) => readOutside.has(p.name) || !readInside.has(p.name))),
    );
    box.name = `${box.id.slice(GROUP_PREFIX.length)}.* · ${box.members.length} nodes`;
    box.description = `${box.members.length} nodes: ${box.members.join(", ")}`;
  }
  return out;
}
