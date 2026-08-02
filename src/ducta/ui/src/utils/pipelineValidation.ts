// ─────────────────────────────────────────────
// PIPELINE VALIDATION — client-side rules that
// run before the user hits "Execute".
// ─────────────────────────────────────────────

import { hasCycle } from "./dagValidation";


export type ValidationLevel = "error" | "warning" | "info";

export interface ValidationResult {
  id: string;
  level: ValidationLevel;
  nodeId?: string;
  message: string;
  action?: { label: string; type: "focus-node" | "auto-fix" };
}

export interface BuilderNodeData {
  id: string;
  name: string;
  type: string;
  module: string;
  fn: string;
  status: string;
  description?: string;
  dependencies: string[];
  inputs: { id: string; name: string; format: string; filepath?: string; mode?: string }[];
  outputs: { id: string; name: string; format: string; filepath?: string; mode?: string }[];
  _raw?: Record<string, unknown>;
}

/**
 * Runs all validation rules against a pipeline and returns a list of issues.
 */
export function validatePipelineGraph(
  pipelineName: string,
  nodes: BuilderNodeData[]
): ValidationResult[] {
  const results: ValidationResult[] = [];
  let counter = 0;
  const nextId = () => `v-${++counter}`;

  // ── Rule 1: Empty pipeline ─────────────────────────────────────────────
  if (nodes.length === 0) {
    results.push({
      id: nextId(),
      level: "warning",
      message: "Pipeline has no nodes. Add at least one node before executing.",
    });
    return results; // No point validating further
  }

  // ── Rule 2: Duplicate node names ───────────────────────────────────────
  const nameCount = new Map<string, string[]>();
  nodes.forEach((n) => {
    const existing = nameCount.get(n.name) ?? [];
    existing.push(n.id);
    nameCount.set(n.name, existing);
  });
  nameCount.forEach((ids, name) => {
    if (ids.length > 1) {
      ids.forEach((id) => {
        results.push({
          id: nextId(),
          level: "error",
          nodeId: id,
          message: `Duplicate node name "${name}". Each node must have a unique name.`,
          action: { label: "Go to node", type: "focus-node" },
        });
      });
    }
  });

  // ── Rule 3: Missing module path ────────────────────────────────────────
  nodes.forEach((node) => {
    if (!node.module || node.module.trim() === "") {
      results.push({
        id: nextId(),
        level: "error",
        nodeId: node.id,
        message: `Node "${node.name}" has no module path configured.`,
        action: { label: "Go to node", type: "focus-node" },
      });
    }
  });

  // ── Rule 4: Orphan nodes (no inputs AND no outputs) ────────────────────
  nodes.forEach((node) => {
    if (
      node.inputs.length === 0 &&
      node.outputs.length === 0 &&
      (node.dependencies?.length ?? 0) === 0
    ) {
      const hasDependents = nodes.some(
        (other) => other.dependencies?.includes(node.id) || other.dependencies?.includes(node.name)
      );
      if (!hasDependents) {
        results.push({
          id: nextId(),
          level: "warning",
          nodeId: node.id,
          message: `Node "${node.name}" is isolated — no inputs, outputs, or dependencies.`,
          action: { label: "Go to node", type: "focus-node" },
        });
      }
    }
  });

  // ── Rule 5: Cycle detection (delegated to dagValidation.hasCycle) ────
  // Convert BuilderNodeData[] to minimal shape expected by hasCycle
  const dagNodes = nodes.map((n) => ({
    id: n.id,
    name: n.name,
    dependencies: n.dependencies ?? [],
  }));
  const cyclePath = hasCycle(dagNodes);

  if (cyclePath) {
    // cyclePath is an array of IDs forming the cycle
    const cycleNodeIds = new Set(cyclePath);
    const cycleNodes = nodes.filter((n) => cycleNodeIds.has(n.id));
    results.push({
      id: nextId(),
      level: "error",
      message: `Circular dependency detected among nodes: ${cycleNodes.map((n) => `"${n.name}"`).join(", ")}.`,
    });
    cycleNodes.forEach((n) => {
      results.push({
        id: nextId(),
        level: "error",
        nodeId: n.id,
        message: `Node "${n.name}" is part of a dependency cycle.`,
        action: { label: "Go to node", type: "focus-node" },
      });
    });
  }

  // ── Rule 6: Unresolved dependencies ────────────────────────────────────
  const nodeIds = new Set(nodes.map((n) => n.id));
  const nodeNames = new Set(nodes.map((n) => n.name));
  nodes.forEach((node) => {
    (node.dependencies ?? []).forEach((dep) => {
      if (!nodeIds.has(dep) && !nodeNames.has(dep)) {
        results.push({
          id: nextId(),
          level: "error",
          nodeId: node.id,
          message: `Node "${node.name}" depends on "${dep}" which is not in this pipeline.`,
          action: { label: "Go to node", type: "focus-node" },
        });
      }
    });
  });

  // ── Rule 7: Pipeline name sanity ───────────────────────────────────────
  if (!pipelineName || pipelineName.trim() === "") {
    results.push({
      id: nextId(),
      level: "error",
      message: "Pipeline name is empty.",
    });
  }

  return results;
}
