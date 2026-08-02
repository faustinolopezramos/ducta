// ─────────────────────────────────────────────
// DAG VALIDATION UTILITIES
// ─────────────────────────────────────────────

/**
 * Minimal shape these graph algorithms need — deliberately looser than
 * `types.Node` so callers (including tests) can pass bare `{id, dependencies}`
 * objects. A full `Node[]` structurally satisfies this too.
 */
export interface GraphNode {
  id: string;
  name?: string;
  dependencies?: string[];
}

/**
 * Resolve a dependency reference (id or name) to node id.
 */
export const resolveDepId = (dep: string, nodes: GraphNode[]): string | undefined =>
  nodes.find((n) => n.id === dep)?.id ??
  nodes.find((n) => n.name === dep)?.id;

/**
 * Detect cycles in a node dependency graph using DFS.
 * @returns Returns an array representing the cycle path (IDs) if a cycle exists, else null.
 */
export function hasCycle(nodes: GraphNode[]): string[] | null {
  const visited = new Set<string>();
  const visiting = new Set<string>();
  const path: string[] = [];

  const dfs = (id: string): string[] | null => {
    if (visiting.has(id)) {
      const idx = path.indexOf(id);
      return path.slice(idx).concat(id);
    }
    if (visited.has(id)) return null;

    visiting.add(id);
    path.push(id);

    const node = nodes.find((n) => n.id === id);
    for (const dep of (node?.dependencies || [])) {
      const depId = resolveDepId(dep, nodes);
      if (depId) {
        const cyclePath = dfs(depId);
        if (cyclePath) return cyclePath;
      }
    }

    path.pop();
    visiting.delete(id);
    visited.add(id);
    return null;
  };

  for (const n of nodes) {
    const cycle = dfs(n.id);
    if (cycle) return cycle;
  }
  return null;
}

/**
 * Return nodes in topological order (Kahn's algorithm, O(V+E)).
 * Returns null if the graph has a cycle.
 */
export function topologicalSort<T extends GraphNode>(nodes: T[]): T[] | null {
  const inDegree = new Map<string, number>(nodes.map((n) => [n.id, 0]));
  const adjList = new Map<string, string[]>(nodes.map((n) => [n.id, []]));

  nodes.forEach((node) => {
    (node.dependencies || []).forEach((dep) => {
      const depId = resolveDepId(dep, nodes);
      if (depId && inDegree.has(depId)) {
        adjList.get(depId)!.push(node.id);
        inDegree.set(node.id, (inDegree.get(node.id) ?? 0) + 1);
      }
    });
  });

  const queue: string[] = nodes.filter((n) => inDegree.get(n.id) === 0).map((n) => n.id);
  const sorted: T[] = [];

  while (queue.length > 0) {
    const id = queue.shift()!;
    const node = nodes.find((n) => n.id === id);
    if (node) sorted.push(node);
    (adjList.get(id) || []).forEach((neighbour) => {
      const deg = (inDegree.get(neighbour) ?? 1) - 1;
      inDegree.set(neighbour, deg);
      if (deg === 0) queue.push(neighbour);
    });
  }

  return sorted.length === nodes.length ? sorted : null;
}

/**
 * Assign each node a layer for a dependency-aware layout: nodes with no
 * (resolved) dependencies sit at level 0; every other node sits one level
 * below the deepest of its dependencies. Nodes with no dependency relation to
 * each other land in the same level and render side by side.
 *
 * Returns null if the graph has a cycle (layering is undefined for cycles —
 * callers should surface `hasCycle`'s result instead of rendering a layout).
 */
export function computeLevels(nodes: GraphNode[]): Map<string, number> | null {
  if (hasCycle(nodes)) return null;

  const levels = new Map<string, number>();

  const levelOf = (id: string): number => {
    if (levels.has(id)) return levels.get(id)!;
    const node = nodes.find((n) => n.id === id);
    const depIds = (node?.dependencies || [])
      .map((dep) => resolveDepId(dep, nodes))
      .filter((depId): depId is string => Boolean(depId));

    const level = depIds.length === 0 ? 0 : 1 + Math.max(...depIds.map(levelOf));
    levels.set(id, level);
    return level;
  };

  for (const n of nodes) levelOf(n.id);
  return levels;
}

export function wouldCreateCycle(
  nodes: GraphNode[],
  sourceId: string,
  targetId: string,
): string[] | null {
  const patched = nodes.map((n) =>
    n.id === targetId
      ? { ...n, dependencies: [...(n.dependencies || []), sourceId] }
      : n
  );
  return hasCycle(patched);
}
