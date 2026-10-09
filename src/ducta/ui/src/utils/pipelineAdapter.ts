// ─────────────────────────────────────────────
// PIPELINE ADAPTER
// Normalizes raw API spec objects (GET /nodes, GET /projects/…/pipelines)
// into the shapes the canvas and the project model expect.
// ─────────────────────────────────────────────

import type { Node, Pipeline } from "../types";

/**
 * Normalize a node's transform spec into string `fn` + `module`.
 *
 * Batch nodes declare a string `fn`/`function`, but streaming nodes declare an
 * object `function: { key, module, params }`. Without this, the object leaks
 * into the graph node and React crashes (error #31, "objects are not valid as
 * a React child") wherever `fn` is rendered.
 */
export function coerceFnSpec(
  rawFn: unknown,
  fallbackModule: unknown,
  defaultFn = "",
): { fn: string; module: string } {
  if (rawFn && typeof rawFn === "object") {
    const obj = rawFn as Record<string, unknown>;
    return {
      fn: String(obj.key ?? obj.fn ?? defaultFn),
      module: String(fallbackModule ?? obj.module ?? ""),
    };
  }
  return {
    fn: rawFn != null ? String(rawFn) : defaultFn,
    module: String(fallbackModule ?? ""),
  };
}

/**
 * Dataset reference names for one side of a node spec.
 *
 * The canonical config spells these `input`/`output` as a list of strings; the
 * API's repository layer normalizes to `inputs`/`outputs`, and a hand-edited
 * YAML can carry a scalar, a dict keyed by name, or a list of objects. Every
 * caller wants the same list of plain names, so the rule lives here.
 *
 * Mirrors `io_names`/`node_io` in api/services/dataset_service.py.
 */
export function ioNames(value: unknown): string[] {
  if (value == null) return [];
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) {
    return value
      .map((entry) => {
        if (typeof entry === "string") return entry;
        if (entry && typeof entry === "object") {
          const obj = entry as { name?: unknown; id?: unknown };
          return String(obj.name ?? obj.id ?? "");
        }
        return "";
      })
      .filter(Boolean);
  }
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>);
  return [];
}

/** Dataset names a node spec declares on `side` ("input" or "output"). */
export function nodeIoNames(spec: any, side: "input" | "output"): string[] {
  if (!spec) return [];
  const plural = `${side}s`;
  const value = spec[plural] ?? spec[side];
  if (side === "input") {
    // Inputs as {param: dataset} — alone, or as a list item, which is how the
    // API returns a format-2 node's: the datasets are the values, the keys are
    // the function's parameter names.
    // Only string values: `{name: {format…}}` is a dict keyed by name instead.
    const isMapping = (v: unknown): v is Record<string, string> =>
      !!v && typeof v === "object" && !Array.isArray(v) && !("name" in v) && !("id" in v) &&
      Object.values(v).length > 0 && Object.values(v).every((x) => typeof x === "string");
    if (isMapping(value)) return Object.values(value);
    if (Array.isArray(value) && value.length > 0 && value.every(isMapping)) {
      return value.flatMap((m) => Object.values(m));
    }
  }
  return ioNames(value);
}

const ML_HINT = /(^|[._-])(ml|model|train|predict|infer|forecast|classif|regress|simulat|cluster|embed)/i;

/**
 * Infer a node's semantic type when the spec doesn't declare one. ducta nodes
 * carry their role implicitly (datasets in/out + module path), so every node
 * defaulting to "custom" left the whole canvas a flat grey. This recovers the
 * type from that existing data:
 *   • an explicit valid `type` always wins
 *   • ML modules / stages → "ml"
 *   • only produces (no inputs) → "source"; only consumes (no outputs) → "sink"
 *   • both → "transform"; neither → "custom"
 */
export function inferNodeType(spec: {
  type?: string;
  module?: string;
  fn?: string;
  function?: unknown;
  ml_stage?: unknown;
  inputs?: unknown[];
  outputs?: unknown[];
}): "source" | "transform" | "ml" | "sink" | "custom" {
  const declared = spec.type;
  if (declared && ["source", "transform", "ml", "sink", "custom"].includes(declared)) {
    return declared as any;
  }
  const nIn = spec.inputs?.length ?? 0;
  const nOut = spec.outputs?.length ?? 0;
  const hay = `${spec.module ?? ""} ${spec.fn ?? ""} ${typeof spec.function === "string" ? spec.function : ""}`;
  if (spec.ml_stage != null || ML_HINT.test(hay)) return "ml";
  if (nIn === 0 && nOut > 0) return "source";
  if (nOut === 0 && nIn > 0) return "sink";
  if (nIn > 0 || nOut > 0) return "transform";
  return "custom";
}

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

/**
 * Server pipeline specs (`GET /projects/{id}/pipelines`) plus the workspace's
 * node specs (`GET /nodes`) → the `Pipeline[]` the canvas and lists render.
 *
 * Pure: derived on read from the query cache, never copied into a store, so
 * the server stays the only source of truth.
 *
 * Node I/O stays a list of *dataset reference names*. The formats, paths and
 * write modes live in `input_config` / `output_config` and are fetched
 * separately by `useProjectDatasets`.
 */
export function pipelinesFromServer(
  rawPipelines: Record<string, any>,
  nodeSpecs: Record<string, any>,
): Pipeline[] {
  return Object.entries(rawPipelines).map(([name, spec]) => ({
    id: name,
    name,
    description: spec?.description ?? "",
    type: spec?.type ?? "batch",
    tags: spec?.tags ?? [],
    active: spec?.active ?? true,
    nodes: (spec?.nodes ?? [])
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
          description: ns.description ?? undefined,
          inputs: inputNames.map((dataset, i) => ({ id: `${nodeName}-input-${i}`, name: dataset })),
          outputs: outputNames.map((dataset, i) => ({ id: `${nodeName}-output-${i}`, name: dataset })),
          active: true,
          status: "idle",
          // Dependencies are the node's own declared ones. The canvas derives
          // the dataset-wired edges itself, from the names above.
          dependencies: Array.isArray(ns.dependencies) ? ns.dependencies.map(String) : [],
        };
      }),
  }));
}
