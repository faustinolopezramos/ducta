/**
 * Turns nodes and datasets into the handful of things worth showing on canvas.
 *
 * In ducta the dataset is the durable thing: nodes reference datasets by name,
 * dependencies are *derived* from who produces and who consumes, medallion
 * layers are dataset namespaces, and run certificates fingerprint datasets.
 * So the canvas puts the dataset on the edge — the edge exists *because* of it —
 * and the node card keeps only what a node alone knows.
 */

/** Medallion layers, in the order a pipeline moves through them. */
const MEDALLION = ["bronze", "silver", "gold"] as const;

export type Medallion = (typeof MEDALLION)[number];

/**
 * The medallion layer a dataset belongs to, read from its namespace
 * (`bronze.etl.raw_data` → bronze).
 *
 * Ducta's own templates namespace datasets this way and the generated projects
 * follow it, so it is real information rather than a guess — but it is only a
 * convention, so anything that does not match simply has no layer.
 */
export function medallionOf(name: string | null | undefined): Medallion | null {
  if (!name) return null;
  const head = name.split(".")[0]?.trim().toLowerCase();
  return MEDALLION.find((layer) => layer === head) ?? null;
}

/** The first medallion layer found across a list of dataset names. */
export function medallionLayer(datasets: readonly string[]): Medallion | null {
  for (const name of datasets) {
    const hit = medallionOf(name);
    if (hit) return hit;
  }
  return null;
}

/** Dataset names for one side of a node, whatever shape the spec used. */
export function datasetNames(io: unknown): string[] {
  if (!io) return [];
  const arr = Array.isArray(io) ? io : [io];
  return arr
    .map((entry) =>
      typeof entry === "string" ? entry : ((entry as { name?: string })?.name ?? "")
    )
    .filter(Boolean);
}

// ── Format glyphs ───────────────────────────────────────────────────────────

/**
 * A dataset's storage shape, as a glyph.
 *
 * Format is encoded by glyph rather than colour so it survives greyscale and
 * colour blindness — the canvas already spends its four colour roles on
 * selection, run status, medallion layer and the lineage lens (see
 * theme/pipeline-canvas.css), and WCAG 1.4.1 rules out colour alone anyway.
 */
export type FormatKind = "table" | "json" | "stream" | "unknown";

const TABULAR = new Set(["parquet", "delta", "csv", "tsv", "orc", "avro", "excel", "xlsx"]);
const STREAMING = new Set(["kafka", "kinesis", "pubsub", "eventhub", "socket", "kafka_avro"]);

export function formatKind(format: string | null | undefined): FormatKind {
  if (!format) return "unknown";
  const f = format.trim().toLowerCase();
  if (TABULAR.has(f)) return "table";
  if (STREAMING.has(f)) return "stream";
  if (f === "json" || f === "jsonl" || f === "ndjson") return "json";
  return "unknown";
}

const GLYPHS: Record<FormatKind, string> = {
  table: "▤",
  json: "{ }",
  stream: "⟳",
  unknown: "·",
};

export function formatGlyph(format: string | null | undefined): string {
  return GLYPHS[formatKind(format)];
}

/** Spoken form of a glyph, for the accessible name of a dataset chip. */
export function formatLabel(format: string | null | undefined): string {
  if (format) return format;
  return "format not declared";
}

// ── Quality ─────────────────────────────────────────────────────────────────

export interface QualitySummary {
  /** How many checks are enabled on this node. */
  count: number;
  /** The gate's behaviour, when one is configured and enabled. */
  gate: string | null;
  /** True when the checks run before the node rather than after it. */
  isSanity: boolean;
}

/**
 * Quality checks and gate configured on a node.
 *
 * Read straight off the typed `quality` field the schema endpoint returns. It
 * used to be derived client-side from a `_raw` spec blob that nothing ever
 * populated, so none of this reached the screen.
 */
export function qualitySummary(
  quality:
    | { checkCount?: number; check_count?: number; gateBehavior?: string | null; gate_behavior?: string | null; isSanity?: boolean; is_sanity?: boolean }
    | null
    | undefined
): QualitySummary | null {
  if (!quality) return null;
  const count = quality.checkCount ?? quality.check_count ?? 0;
  const gate = quality.gateBehavior ?? quality.gate_behavior ?? null;
  const isSanity = quality.isSanity ?? quality.is_sanity ?? false;
  if (count === 0 && !gate) return null;
  return { count, gate, isSanity };
}

/** `skip_downstream` → `skip downstream`, for a label rather than a config key. */
export function humanizeGate(behavior: string): string {
  return behavior.replace(/_/g, " ");
}

/** `transform` → `Transform`: a config value, read as a sentence-case label. */
export function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// ── Semantic zoom ───────────────────────────────────────────────────────────

/**
 * Three tiers instead of two.
 *
 * With the datasets on the edges there is more to graduate: zoomed out you read
 * the topology, mid-zoom you follow the data, zoomed in you read the details.
 * Keeping the full card at every zoom is what forces a choice between "cards
 * you can read" and "a pipeline that fits".
 */
export type ZoomTier = "shape" | "flow" | "detail";

/** Below this, only a card's silhouette carries meaning. */
export const SHAPE_ZOOM_CEILING = 0.45;
/** Above this, the card shows everything it has. */
export const DETAIL_ZOOM_FLOOR = 0.85;

export function zoomTier(zoom: number): ZoomTier {
  if (zoom < SHAPE_ZOOM_CEILING) return "shape";
  if (zoom < DETAIL_ZOOM_FLOOR) return "flow";
  return "detail";
}

// ── Formatting ──────────────────────────────────────────────────────────────

/** `1234567` → `1.2 M`. Row counts sit in a 60px chip, so they must be short. */
export function compactCount(n: number | null | undefined): string | null {
  if (n == null || !Number.isFinite(n)) return null;
  if (Math.abs(n) < 1_000) return String(n);
  if (Math.abs(n) < 1_000_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")} K`;
  if (Math.abs(n) < 1_000_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")} M`;
  return `${(n / 1_000_000_000).toFixed(1).replace(/\.0$/, "")} B`;
}

/** `0.812` → `0.81 s`; `74.2` → `74 s`. */
export function compactDuration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`;
  if (seconds < 10) return `${seconds.toFixed(2).replace(/0$/, "")} s`;
  if (seconds < 120) return `${seconds.toFixed(0)} s`;
  return `${(seconds / 60).toFixed(1).replace(/\.0$/, "")} min`;
}
