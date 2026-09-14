import { useEffect } from "react";
import { useServerProjectPipelines, useNodes } from "../api/queries";
import { coerceFnSpec, inferNodeType, nodeIoNames } from "../utils/pipelineAdapter";
import type { Pipeline, Node } from "../types";

/**
 * useServerPipelineHydration — server pipelines into the local project model.
 *
 * Fetches server-persisted pipelines and node specs, transforms them to the
 * local model, and dispatches to the reducer.
 *
 * Node I/O stays a list of *dataset reference names* here. The formats, paths
 * and write modes live in `input_config` / `output_config` and are fetched
 * separately by `useProjectDatasets` — this hook used to hard-code
 * `format: "parquet"` on every entry, so a Kafka→Delta pipeline was presented
 * as parquet→parquet.
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
      nodes: (spec.nodes ?? [])
        .map((entry: any) => ({ name: toNodeName(entry), entry }))
        .filter(({ name: nodeName }: { name: string }) => nodeName.length > 0)
        .map(({ name: nodeName, entry }: { name: string; entry: any }): Node => {
          const entryObj = entry && typeof entry === "object" ? entry : {};
          const ns = nodeSpecs[nodeName] ?? entryObj;
          const inputNames = nodeIoNames(ns, "input");
          const outputNames = nodeIoNames(ns, "output");
          // Streaming nodes carry `function: { key, module }` (object); coerce to
          // string fn/module so the graph never renders an object (React #31).
          const { fn, module } = coerceFnSpec(
            ns.fn ?? ns.function ?? entryObj.function,
            ns.module ?? entryObj.module
          );
          return {
            id: nodeName,
            name: nodeName,
            type: inferNodeType({
              type: ns.type,
              module,
              fn,
              ml_stage: ns.ml_stage,
              inputs: inputNames,
              outputs: outputNames,
            }),
            module,
            fn,
            // Carried through so the canvas can show it without a second fetch;
            // the old hydration dropped it, and the card read it from a `_raw`
            // blob nothing populated, so no description ever rendered.
            description: ns.description ?? undefined,
            inputs: inputNames.map((dataset, i) => ({
              id: `${nodeName}-input-${i}`,
              name: dataset,
            })),
            outputs: outputNames.map((dataset, i) => ({
              id: `${nodeName}-output-${i}`,
              name: dataset,
            })),
            active: true,
            status: "idle",
            // Dependencies are the node's own declared ones. The canvas derives
            // the dataset-wired edges itself, from the names above — deriving
            // them here as well produced a second, unlabelled edge set.
            dependencies: Array.isArray(ns.dependencies) ? ns.dependencies.map(String) : [],
          };
        }),
      createdAt: Date.now(),
      updatedAt: Date.now(),
      // The server just listed this one, so the reducer can safely drop it
      // later if a future hydration stops listing it (deleted elsewhere) —
      // see the `persisted` field's own doc comment on `Pipeline`.
      persisted: true,
    }));

    dispatch({ type: "HYDRATE_PIPELINES", projectId, pipelines: converted });
  }, [serverPipelinesData, nodesData, projectId, dispatch]);
}
