/** Pure rules for editing the graph on the canvas. */

/** Would `to` reading from `from` close a loop? True when `to` is already upstream of `from`. */
export function wouldCycle(from: string, to: string, parents: Map<string, string[]>): boolean {
  if (from === to) return true;
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const id = stack.pop()!;
    if (id === to) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...(parents.get(id) ?? []));
  }
  return false;
}

/** Of what `from` writes, what `to` does not read yet — what a connection would add. */
export function datasetsToConnect(fromOutputs: string[], toInputs: string[]): string[] {
  const reads = new Set(toInputs);
  return fromOutputs.filter((d) => !reads.has(d));
}

const NODE_NAME = /^[A-Za-z_][A-Za-z0-9_.-]*$/;

/** A node name the format-2 loader accepts, not taken. Null when fine. */
export function nodeNameError(name: string, taken: ReadonlySet<string>): string | null {
  if (!name) return "A node needs a name.";
  if (!NODE_NAME.test(name)) return "Start with a letter or _, then letters, digits, _, - or .";
  if (taken.has(name)) return `“${name}” already exists — node names are unique in the project.`;
  return null;
}

/** `src.silver:clean` — a module path and a function. Null when fine. */
export function runError(run: string): string | null {
  if (!run) return null; // optional: an ingest node has none
  return /^[A-Za-z_][\w.]*:[A-Za-z_]\w*$/.test(run) ? null : "Write it as module.path:function, e.g. src.silver:clean";
}

/** The parameter name a dataset gets: its last segment as an identifier (as the server does). */
export function aliasFor(dataset: string): string {
  const base = (dataset.split(".").pop() ?? "data").replace(/[^A-Za-z0-9_]/g, "_") || "data";
  return /^\d/.test(base) ? `_${base}` : base;
}

/** `src/silver.py` → `src.silver`. */
export function moduleOf(file: string): string {
  return file.replace(/\.py$/, "").replace(/\/__init__$/, "").split("/").join(".");
}

/**
 * A node name for a function dropped on the canvas: its module's last part as
 * the namespace (`src.silver:clean_orders` → `silver.clean_orders`).
 */
export function suggestNodeName(run: string): string {
  const [module, fn = ""] = run.split(":");
  const ns = module.split(".").filter((p) => p !== "src").pop();
  return ns ? `${ns}.${fn}` : fn;
}

/** The dataset a function's first parameter names, if one does (`def clean(orders)` → `bronze.sales.orders`). */
export function datasetForParam(param: string | undefined, datasets: string[]): string | undefined {
  if (!param) return undefined;
  return datasets.find((d) => aliasFor(d) === param) ?? datasets.find((d) => aliasFor(d).endsWith(param));
}
