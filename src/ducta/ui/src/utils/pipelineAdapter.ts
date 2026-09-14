// ─────────────────────────────────────────────
// PIPELINE ADAPTER
// Normalizes raw API spec objects (GET /nodes, GET /projects/…/pipelines)
// into the shapes the canvas and the project model expect.
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
  return ioNames(spec[plural] ?? spec[side]);
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
