import type { ProjectDataset } from "../api/queries/datasets";

export interface LineageLevel {
  /** 1 = directly feeds / is fed by the dataset. */
  hop: number;
  datasets: string[];
}

export interface DatasetLineage {
  upstream: LineageLevel[];
  downstream: LineageLevel[];
  /** Everything downstream, at any distance: what a change here can break. */
  impact: { pipelines: string[]; nodes: string[]; datasets: string[] };
}

/**
 * Lineage across every pipeline of the project, from the dataset list's
 * producers and consumers: dataset → node that writes it → that node's inputs
 * (upstream), and dataset → nodes that read it → their outputs (downstream).
 */
export function datasetLineage(datasets: ProjectDataset[], name: string, hops = 3): DatasetLineage {
  const reads = new Map<string, Set<string>>(); // node → datasets it reads
  const writes = new Map<string, Set<string>>(); // node → datasets it writes
  const pipelineOf = new Map<string, string>();
  const add = (m: Map<string, Set<string>>, k: string, v: string) => (m.get(k) ?? m.set(k, new Set()).get(k)!).add(v);
  const byName = new Map(datasets.map((d) => [d.name, d]));
  for (const d of datasets) {
    for (const p of d.producers) {
      add(writes, p.node, d.name);
      if (p.pipeline) pipelineOf.set(p.node, p.pipeline);
    }
    for (const c of d.consumers) {
      add(reads, c.node, d.name);
      if (c.pipeline) pipelineOf.set(c.node, c.pipeline);
    }
  }

  const walk = (step: (ds: string) => { nodes: string[]; next: string[] }, limit: number) => {
    const levels: LineageLevel[] = [];
    const seen = new Set([name]);
    const nodes = new Set<string>();
    let frontier = [name];
    for (let hop = 1; frontier.length > 0 && hop <= limit; hop++) {
      const next: string[] = [];
      for (const ds of frontier) {
        const s = step(ds);
        s.nodes.forEach((n) => nodes.add(n));
        for (const n of s.next) {
          if (seen.has(n)) continue;
          seen.add(n);
          next.push(n);
        }
      }
      if (next.length) levels.push({ hop, datasets: next.sort() });
      frontier = next;
    }
    return { levels, nodes, seen };
  };

  const up = (ds: string) => {
    const nodes = (byName.get(ds)?.producers ?? []).map((p) => p.node);
    return { nodes, next: nodes.flatMap((n) => [...(reads.get(n) ?? [])]) };
  };
  const down = (ds: string) => {
    const nodes = (byName.get(ds)?.consumers ?? []).map((c) => c.node);
    return { nodes, next: nodes.flatMap((n) => [...(writes.get(n) ?? [])]) };
  };

  const upstream = walk(up, hops).levels;
  const all = walk(down, Infinity);
  const downstream = walk(down, hops).levels;
  const nodes = [...all.nodes].sort();
  return {
    upstream,
    downstream,
    impact: {
      nodes,
      pipelines: [...new Set(nodes.map((n) => pipelineOf.get(n)).filter((p): p is string => !!p))].sort(),
      datasets: [...all.seen].filter((d) => d !== name).sort(),
    },
  };
}
