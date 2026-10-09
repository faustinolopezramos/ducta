/**
 * Every in-app URL, built in one place.
 *
 * A project owns its pipelines, datasets, code, runs and settings, so they all
 * live under `/p/:projectId`. Building the strings here — instead of writing
 * `/project/${id}/pipeline/${name}` at each call site — is what let the scheme
 * change without hunting for template literals, and keeps encoding consistent.
 */

const enc = encodeURIComponent;

export type ProjectSection =
  | "pipelines"
  | "runs"
  | "quality"
  | "models"
  | "schedules"
  | "connections"
  | "code"
  | "settings";

function withQuery(path: string, query?: Record<string, string | null | undefined>): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value != null && value !== "") params.set(key, value);
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export const routes = {
  projects: () => "/projects",
  /** The project's overview — its home. */
  project: (projectId: string) => `/p/${enc(projectId)}`,
  /** Its pipelines, as a map or a list. */
  pipelines: (projectId: string) => `/p/${enc(projectId)}/pipelines`,
  pipeline: (
    projectId: string,
    pipelineId: string,
    query?: { focus?: string | null; lens?: string | null; panel?: string | null; run?: string | null },
  ) => withQuery(`/p/${enc(projectId)}/pipelines/${enc(pipelineId)}`, query),
  /** A node is addressed through its pipeline: the canvas, focused on it. */
  node: (projectId: string, pipelineId: string, nodeId: string, panel?: string) =>
    routes.pipeline(projectId, pipelineId, { focus: `node:${nodeId}`, panel }),
  dataset: (projectId: string, dataset: string) => `/p/${enc(projectId)}/datasets/${enc(dataset)}`,
  /** A project file; `line` scrolls the editor to it. */
  code: (projectId: string, path?: string, line?: number) =>
    withQuery(
      `/p/${enc(projectId)}/code${path ? `/${path.split("/").map(enc).join("/")}` : ""}`,
      { line: line ? String(line) : null },
    ),
  runs: (projectId: string, query?: { pipeline?: string | null }) =>
    withQuery(`/p/${enc(projectId)}/runs`, query),
  run: (projectId: string, runId: string, query?: { node?: string | null }) =>
    withQuery(`/p/${enc(projectId)}/runs/${enc(runId)}`, query),
  section: (projectId: string, section: ProjectSection, sub?: string) =>
    `/p/${enc(projectId)}/${section}${sub ? `/${sub}` : ""}`,
} as const;

/** The project a path is about, if it is a project-scoped path. */
export function projectIdFromPath(pathname: string): string | null {
  const m = /^\/p\/([^/]+)/.exec(pathname);
  return m ? decodeURIComponent(m[1]) : null;
}
