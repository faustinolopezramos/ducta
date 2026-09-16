import type { Medallion } from "../../utils/nodePresentation";

/**
 * A dataset, resolved against `input_config` / `output_config`.
 *
 * Every optional field is `null`/undefined when the registry does not declare
 * it, and `declared` is false when the reference is dangling. Those are
 * answers: the UI says "not declared" rather than substituting a default the
 * data does not have. (It used to hard-code `"parquet"` for every dataset, so
 * a Kafka→Delta pipeline was presented as parquet→parquet.)
 */
export interface CanvasDataset {
  /** Reference name as declared on the node, e.g. `bronze.raw_results`. */
  name: string;
  declared: boolean;
  format?: string | null;
  path?: string | null;
  writeMode?: string | null;
  schema?: string | null;
  layer?: Medallion | null;
  /** Rows written by the last run, when a certificate reported it. */
  rows?: number | null;
}

/** One port on a node: a stable id for edge anchoring, plus the dataset name. */
export interface CanvasPort {
  id: string;
  /** Dataset reference name this port carries. */
  name: string;
}

export interface CanvasQuality {
  checkCount: number;
  gateBehavior?: string | null;
  isSanity: boolean;
}

export interface DagCanvasItem {
  id: string;
  name?: string;
  type?: string;
  module?: string;
  fn?: string;
  description?: string;
  inputs?: CanvasPort[];
  outputs?: CanvasPort[];
  /** ids (or names) of items this one depends on. */
  dependsOn: string[];
  /** Checks and gate, from the schema endpoint's typed `quality` field. */
  quality?: CanvasQuality | null;
  /** Duration of the last run, in seconds. */
  lastDuration?: number | null;
  /** Pipeline that declares the node — set when a chain of pipelines is drawn together. */
  pipeline?: string;
  [key: string]: any;
}

/**
 * What the canvas has selected. Nodes and datasets are both first-class, so
 * selection carries which kind it is and the inspector is chosen from that.
 */
export type CanvasSelection =
  | { kind: "node"; id: string }
  | { kind: "dataset"; id: string }
  | null;

/** An edge that exists because a dataset flows across it. */
export interface DatasetEdge {
  from: string;
  to: string;
  /** null for an explicit `dependencies` edge with no dataset behind it. */
  dataset: string | null;
}
