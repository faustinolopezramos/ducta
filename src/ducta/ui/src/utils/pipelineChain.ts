// ─────────────────────────────────────────────
// PIPELINE CHAIN — how a project's pipelines depend on each other.
//
// Running a pipeline runs its chain: `run_pipeline_chain` resolves every
// upstream pipeline it `depends_on` and executes them in order. So the chain is
// not decoration — it is what "Run" actually does, and the workspace shows it.
//
// A graph here is `pipeline → pipelines it depends on`, the same shape
// `computeLineage` and `computeLevels` already take.
// ─────────────────────────────────────────────

import { computeLevels } from "./dagValidation";

export type PipelineGraph = Map<string, Set<string>>;

function asList(value: unknown): string[] {
  if (typeof value === "string") return value ? [value] : [];
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  return [];
}

/** From the pipeline specs' own `depends_on` — what the runtime chains. */
export function dependsOnFromSpecs(
  specs: Record<string, { depends_on?: unknown } | null | undefined>
): PipelineGraph {
  const graph: PipelineGraph = new Map();
  for (const [name, spec] of Object.entries(specs)) {
    const deps = asList(spec?.depends_on).filter((d) => d !== name && d in specs);
    graph.set(name, new Set(deps));
  }
  return graph;
}

/**
 * From `GET /projects/{id}/dependencies` edges — explicit node dependencies and
 * shared datasets that cross a pipeline boundary.
 */
export function dependsOnFromEdges(
  pipelines: string[],
  edges: ReadonlyArray<{ from_pipeline: string; to_pipeline: string }>
): PipelineGraph {
  const graph: PipelineGraph = new Map(pipelines.map((p) => [p, new Set<string>()]));
  for (const edge of edges) {
    if (edge.from_pipeline === edge.to_pipeline) continue;
    graph.get(edge.to_pipeline)?.add(edge.from_pipeline);
  }
  return graph;
}

/** `graph` as the parents map (`id → ids it depends on`) the lineage utils take. */
export function toParentsMap(graph: PipelineGraph): Map<string, string[]> {
  return new Map([...graph].map(([p, deps]) => [p, [...deps]]));
}

function walk(start: string, next: (id: string) => Iterable<string>): string[] {
  const seen = new Set<string>([start]);
  const out: string[] = [];
  const queue = [start];
  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const n of next(id)) {
      if (seen.has(n)) continue;
      seen.add(n);
      out.push(n);
      queue.push(n);
    }
  }
  return out;
}

/** Every pipeline `pipeline` transitively depends on (what its run executes first). */
export function ancestorsOf(pipeline: string, graph: PipelineGraph): string[] {
  return walk(pipeline, (id) => graph.get(id) ?? []);
}

/** Every pipeline that transitively depends on `pipeline`. */
export function descendantsOf(pipeline: string, graph: PipelineGraph): string[] {
  const children = new Map<string, string[]>();
  for (const [p, deps] of graph) {
    for (const d of deps) {
      if (!children.has(d)) children.set(d, []);
      children.get(d)!.push(p);
    }
  }
  return walk(pipeline, (id) => children.get(id) ?? []);
}

/**
 * `pipelines` in execution order: dependencies first, ties broken by name so the
 * order is stable. A cycle has no order, so the input order is kept.
 */
export function orderPipelines(pipelines: string[], graph: PipelineGraph): string[] {
  const inScope = new Set(pipelines);
  const levels = computeLevels(
    pipelines.map((p) => ({
      id: p,
      dependencies: [...(graph.get(p) ?? [])].filter((d) => inScope.has(d)),
    }))
  );
  if (!levels) return [...pipelines];
  return [...pipelines].sort(
    (a, b) => (levels.get(a) ?? 0) - (levels.get(b) ?? 0) || a.localeCompare(b)
  );
}

/** The chain a run of `pipeline` executes: its ancestors, then itself, in order. */
export function runChainOf(pipeline: string, graph: PipelineGraph): string[] {
  return orderPipelines([...ancestorsOf(pipeline, graph), pipeline], graph);
}
