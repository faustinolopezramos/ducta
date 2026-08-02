import { useEffect } from "react";
import { useServerProjectPipelines, useNodes } from "../api/queries";
import { coerceFnSpec, deriveDatasetDependencies, inferNodeType } from "../utils/pipelineAdapter";
import type { Pipeline, Node } from "../types";

/**
 * useServerPipelineHydration — Separates pipeline data transformation logic from UI layout.
 *
 * Fetches server-persisted pipelines and node specs, transforms them to local model,
 * and dispatches to the reducer when the project is initially empty.
 *
 * This hook extracts business logic from ProjectLayout, improving separation of concerns.
 */
/**
 * Coerce a pipeline `nodes` entry to a string name. The list is normally
 * strings, but a hand-edited YAML (or an alternate/normalized format) can carry
 * objects like `{ key, module }`. Using such an object as a node id/name made
 * React try to render it as a child → "Objects are not valid as a React child"
 * (minified error #31). Always resolve a plain string here.
 */
function toNodeName(entry: any): string {
  if (typeof entry === "string") return entry;
  if (entry && typeof entry === "object") {
    return String(entry.key ?? entry.name ?? entry.id ?? entry.node ?? "");
  }
  return String(entry ?? "");
}

export function useServerPipelineHydration(projectId: string | undefined, dispatch: any) {
  const { data: serverPipelinesData } = useServerProjectPipelines(projectId ?? "");
  const { data: nodesData } = useNodes();

  useEffect(() => {
    if (!serverPipelinesData?.pipelines || !projectId) return;

    const rawPipelines = serverPipelinesData.pipelines as Record<string, any>;
    const nodeSpecs: Record<string, any> = nodesData?.nodes ?? {};

    const converted: Pipeline[] = Object.entries(rawPipelines).map(([name, spec]) => ({
      id: name,
      name,
      description: spec.description ?? "",
      type: spec.type ?? "batch",
      tags: spec.tags ?? [],
      active: spec.active ?? true,
      nodes: deriveDatasetDependencies((spec.nodes ?? [])
        .map((entry: any) => ({ name: toNodeName(entry), entry }))
        .filter(({ name }: { name: string }) => name.length > 0)
        .map(({ name: nodeName, entry }: { name: string; entry: any }): Node => {
        const entryObj = entry && typeof entry === "object" ? entry : {};
        const ns = nodeSpecs[nodeName] ?? entryObj;
        const rawInputs: any[] = ns.inputs ?? ns.input ?? [];
        const rawOutputs: any[] = ns.outputs ?? ns.output ?? [];
        // Streaming nodes carry `function: { key, module }` (object); coerce to
        // string fn/module so the graph never renders an object (React #31).
        const { fn, module } = coerceFnSpec(
          ns.fn ?? ns.function ?? entryObj.function,
          ns.module ?? entryObj.module,
        );
        return {
          id: nodeName,
          name: nodeName,
          type: inferNodeType({
            type: ns.type,
            module,
            fn,
            ml_stage: ns.ml_stage,
            inputs: rawInputs,
            outputs: rawOutputs,
          }),
          module,
          fn,
          inputs: rawInputs.map((io: any, i: number) => ({
            id: `${nodeName}-input-${i}`,
            name: typeof io === "string" ? io : (io.name ?? `input_${i}`),
            format: typeof io === "string" ? "parquet" : (io.format ?? "parquet"),
          })),
          outputs: rawOutputs.map((io: any, i: number) => ({
            id: `${nodeName}-output-${i}`,
            name: typeof io === "string" ? io : (io.name ?? `output_${i}`),
            format: typeof io === "string" ? "parquet" : (io.format ?? "parquet"),
          })),
          active: true,
          status: "idle",
        };
      })),
      edges: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }));

    dispatch({ type: "HYDRATE_PIPELINES", projectId, pipelines: converted });
  }, [serverPipelinesData, nodesData, projectId, dispatch]);
}
