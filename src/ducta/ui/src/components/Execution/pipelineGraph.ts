import { parse } from "yaml";
import type { DagCanvasItem } from "../Pipeline/types";

const asNames = (v: unknown): string[] =>
  Array.isArray(v) ? v.map(String) : v && typeof v === "object" ? Object.values(v as Record<string, unknown>).map(String) : typeof v === "string" ? [v] : [];

/**
 * A format-2 pipeline file as canvas items — the graph as that version of the
 * file drew it: each node with what it reads and writes, depending on the
 * nodes that write what it reads. Null when the text is not a pipeline.
 */
export function itemsFromPipelineYaml(text: string, pipeline: string): DagCanvasItem[] | null {
  let doc: any;
  try {
    doc = parse(text);
  } catch {
    return null;
  }
  const nodes = doc?.nodes;
  if (!nodes || typeof nodes !== "object" || Array.isArray(nodes)) return null;
  const writer = new Map<string, string>();
  for (const [name, spec] of Object.entries<any>(nodes)) for (const out of asNames(spec?.outputs)) writer.set(out, name);
  return Object.entries<any>(nodes).map(([name, spec]) => {
    const inputs = asNames(spec?.inputs);
    const outputs = asNames(spec?.outputs);
    const deps = new Set([...inputs.map((d) => writer.get(d)).filter((w): w is string => !!w && w !== name), ...asNames(spec?.depends_on)]);
    return {
      id: name,
      name,
      type: spec?.kind ?? "transform",
      description: spec?.description,
      inputs: inputs.map((d) => ({ id: `${name}:in:${d}`, name: d })),
      outputs: outputs.map((d) => ({ id: `${name}:out:${d}`, name: d })),
      dependsOn: [...deps],
      pipeline,
    };
  });
}
