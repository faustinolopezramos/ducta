// ─────────────────────────────────────────────
// PIPELINE ADAPTER
// Converts raw API spec objects (from GET /nodes, GET /pipelines)
// into the shape expected by PipelineGraph / PipelineView.
// Also converts back for PUT /nodes and PUT /pipelines.
// ─────────────────────────────────────────────

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
 * Derive node-to-node dependencies from dataset wiring.
 *
 * ducta node configs express edges implicitly: a node consumes datasets
 * (`input`) that other nodes in the same pipeline produce (`output`). The
 * canvas only draws explicit `dependencies`, so dataset-wired pipelines (e.g.
 * worldcup's medallion layers) render as disconnected nodes without this step.
 *
 * Each node's dependencies become the union of any already-declared
 * dependencies and every same-pipeline node that outputs one of its input
 * datasets (self-edges excluded). Pure: returns new node objects, inputs
 * untouched. Mirrors, at node granularity, the dataset producer→consumer
 * matching the backend already does for the cross-pipeline project map.
 */
export function deriveDatasetDependencies<
  T extends {
    id: string;
    inputs?: { name?: string }[];
    outputs?: { name?: string }[];
    dependencies?: string[];
  },
>(nodes: T[]): T[] {
  const producers = new Map<string, string[]>();
  for (const node of nodes) {
    for (const out of node.outputs ?? []) {
      if (!out?.name) continue;
      (producers.get(out.name) ?? producers.set(out.name, []).get(out.name)!).push(node.id);
    }
  }

  return nodes.map((node) => {
    const deps = new Set(node.dependencies ?? []);
    for (const input of node.inputs ?? []) {
      if (!input?.name) continue;
      for (const producer of producers.get(input.name) ?? []) {
        if (producer !== node.id) deps.add(producer);
      }
    }
    return { ...node, dependencies: [...deps] };
  });
}

const ML_HINT = /(^|[._-])(ml|model|train|predict|infer|forecast|classif|regress|simulat|cluster|embed)/i;

/**
 * Infer a node's semantic type when the spec doesn't declare one. ducta nodes
 * carry their role implicitly (datasets in/out + module path), so every node
 * defaulting to "custom" left the whole canvas a flat grey. This recovers the
 * type — and therefore the per-type accent colour — from that existing data:
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
 * Transform a single node spec from the API into the
 * PipelineGraph node shape.
 *
 * API format:   { module, fn, status, dependencies, inputs:[{name,format,path}], outputs:[...] }
 * Graph format: { id, name, module, fn, status, dependencies, inputs:[{id,name,format,filepath,mode}], outputs:[...] }
 *
 * @param {string} name  - node key from GET /nodes
 * @param {Object} spec  - raw spec dict
 * @returns {Object}
 */
export function adaptApiNode(name: string, spec: any = {}) {
  const mapIO = (ios: any, mode: string) => {
    if (!ios) return [];
    const arr = Array.isArray(ios) ? ios : [ios];
    return arr.map((io, i) => {
      const isStr = typeof io === "string";
      const ioName = isStr ? io : (io.name ?? `${mode}_${i}`);
      return {
        id:       `${name}-${mode}-${ioName}`,
        name:     ioName,
        format:   isStr ? "parquet" : (io.format ?? "parquet"),
        filepath: isStr ? "" : (io.path ?? io.filepath ?? ""),
        mode,
      };
    });
  };

  const { fn, module } = coerceFnSpec(spec.fn ?? spec.function, spec.module, "run");

  return {
    id:           name,
    name,
    module,
    fn,
    status:       spec.status ?? "active",
    dependencies: spec.dependencies ?? [],
    inputs:       mapIO(spec.inputs ?? spec.input, "read"),
    outputs:      mapIO(spec.outputs ?? spec.output, "write"),
    // Preserve extra spec keys (dataQuality, executionConfig, etc.)
    _raw: spec,
  };
}
