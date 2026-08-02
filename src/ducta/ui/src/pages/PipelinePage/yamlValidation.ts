import type { EditorMarker } from "../../components/CodeEditor";
import yaml from "js-yaml";

export const VALID_PIPELINE_TYPES = ["batch", "streaming", "ml", "hybrid"];

export function validatePipelineYaml(value: string): EditorMarker[] {
  if (!value.trim()) return [];
  let parsed: unknown;
  try {
    parsed = yaml.load(value);
  } catch (e: any) {
    const mark = e?.mark;
    return [
      {
        startLineNumber: mark ? mark.line + 1 : 1,
        startColumn: mark ? mark.column + 1 : 1,
        message: e?.reason ? `YAML syntax: ${e.reason}` : `Invalid YAML: ${e?.message ?? "parse error"}`,
        severity: "error",
      },
    ];
  }
  if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return [{ startLineNumber: 1, message: "Pipeline spec must be a YAML mapping (key: value).", severity: "error" }];
  }
  const spec = parsed as Record<string, unknown>;
  const markers: EditorMarker[] = [];
  if ("type" in spec && !VALID_PIPELINE_TYPES.includes(String(spec.type))) {
    markers.push({
      startLineNumber: 1,
      message: `Unknown pipeline type "${String(spec.type)}". Expected one of: ${VALID_PIPELINE_TYPES.join(", ")}.`,
      severity: "error",
    });
  }
  if ("nodes" in spec && !Array.isArray(spec.nodes)) {
    markers.push({
      startLineNumber: 1,
      message: "`nodes` must be a list of node names.",
      severity: "error",
    });
  }
  if (!("nodes" in spec)) {
    markers.push({
      startLineNumber: 1,
      message: "Pipeline has no `nodes` defined.",
      severity: "warning",
    });
  }
  return markers;
}
