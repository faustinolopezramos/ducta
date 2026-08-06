import React from "react";
import { colors } from "../../theme/tokens";
import client from "../../api/client";
// Both MLOps tabs import from this module, so it is where the shared stylesheet
// gets pulled in. It existed but was never imported by anything, so none of its
// rules had ever applied.
import "./shared.css";

/** Best-effort fallback: find the project that owns a pipeline by name.
 *  Older MLOps runs only record the pipeline's name; newer runs carry a
 *  project_id tag, so this scan is only needed for pre-tag runs. */
export async function findProjectForPipeline(pipelineName: string): Promise<string | null> {
  const { data } = await client.get("/projects");
  for (const project of data?.projects ?? []) {
    try {
      const { data: pipelinesData } = await client.get(`/projects/${project.id}/pipelines`);
      if (pipelinesData?.pipelines && pipelineName in pipelinesData.pipelines) {
        return project.id;
      }
    } catch {
      // skip unreadable project
    }
  }
  return null;
}

// ── Style helpers ─────────────────────────────────────────────────────────────

export const card: React.CSSProperties = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: 8,
  padding: "16px 20px",
  marginBottom: 12,
};

export const STAGE_COLOR: Record<string, string> = {
  Staging: "var(--warning)",
  Production: "var(--success)",
  Archived: "var(--text-muted)",
};

export function StageBadge({ stage }: { stage: string }) {
  const color = STAGE_COLOR[stage] ?? "var(--text-muted)";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        background: `${color}20`,
        color,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
      }}
    >
      {stage}
    </span>
  );
}

export function formatDate(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
