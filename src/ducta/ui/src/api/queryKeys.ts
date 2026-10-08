import { sourceKey } from "./utils";

/**
 * Every React Query key the app uses, in one place.
 *
 * Keys start with `[domain, sourceKey()]`, so `qk.<domain>.all()` invalidates
 * exactly that domain for the connected source — no more mixing `["git"]`
 * (every source) with `["git", sourceKey()]`, or invalidating a key no query
 * uses. Build keys here; never spell one out inline.
 */

/** The optional env / pipeline / project narrowing quality and MLOps queries share. */
export interface ScopeKey {
  env?: string;
  pipelineName?: string;
  project?: string;
}

const scope = ({ env, pipelineName, project }: ScopeKey = {}) =>
  [env ?? null, pipelineName ?? null, project ?? null] as const;

export const qk = {
  platform: () => ["platform"] as const,
  /** The signed-in user: not scoped to a source, it is the same everywhere. */
  auth: {
    me: () => ["auth", "me"] as const,
  },
  source: () => ["source", sourceKey()] as const,
  workspaceBrowse: (cwd: string | null | undefined) => ["workspace-browse", cwd] as const,
  environments: (project?: string) => ["environments", sourceKey(), project ?? null] as const,
  templates: () => ["templates", sourceKey()] as const,
  schedules: () => ["schedules", sourceKey()] as const,

  configs: {
    all: () => ["configs", sourceKey()] as const,
    list: (env: string) => ["configs", sourceKey(), env] as const,
    file: (env: string, name: string) => ["configs", sourceKey(), env, name] as const,
  },

  git: {
    all: () => ["git", sourceKey()] as const,
    config: () => ["git", sourceKey(), "config"] as const,
    status: () => ["git", sourceKey(), "status"] as const,
    log: (path: string | undefined, limit: number) =>
      ["git", sourceKey(), "log", { path, limit }] as const,
    commit: (sha: string) => ["git", sourceKey(), "commit", sha] as const,
    diff: (sha: string) => ["git", sourceKey(), "diff", sha] as const,
  },

  projects: {
    all: () => ["server-projects", sourceKey()] as const,
    detail: (projectId: string) => ["server-projects", sourceKey(), projectId] as const,
    pipelines: (projectId: string) =>
      ["server-projects", sourceKey(), projectId, "pipelines"] as const,
    pipeline: (projectId: string, name: string) =>
      ["server-projects", sourceKey(), projectId, "pipelines", name] as const,
    dependencies: (projectId: string) =>
      ["server-projects", sourceKey(), projectId, "dependencies"] as const,
    mlPlan: (projectId: string, pipeline: string, env: string) =>
      ["server-projects", sourceKey(), projectId, "pipelines", pipeline, "ml-plan", env] as const,
    datasets: (projectId: string) =>
      ["server-projects", sourceKey(), projectId, "datasets"] as const,
    nodeSchemas: (projectId: string, pipeline: string) =>
      ["server-projects", sourceKey(), projectId, "pipelines", pipeline, "nodes", "schema"] as const,
    nodeSchema: (projectId: string, pipeline: string, node: string) =>
      ["server-projects", sourceKey(), projectId, "pipelines", pipeline, "nodes", node, "schema"] as const,
  },

  nodes: {
    all: () => ["nodes", sourceKey()] as const,
    detail: (name: string) => ["nodes", sourceKey(), name] as const,
    code: (name: string) => ["nodes", sourceKey(), name, "code"] as const,
  },

  executions: {
    all: () => ["executions", sourceKey()] as const,
    list: (filters: unknown) => ["executions", sourceKey(), filters] as const,
    queue: () => ["executions", sourceKey(), "queue"] as const,
    detail: (executionId: string) => ["executions", sourceKey(), executionId] as const,
    logs: (executionId: string) => ["executions", sourceKey(), executionId, "logs"] as const,
    errors: (executionId: string | null | undefined) => ["executions", sourceKey(), executionId, "errors"] as const,
    streaming: (executionId: string) => ["executions", sourceKey(), executionId, "streaming"] as const,
  },

  files: {
    all: () => ["workspace-files", sourceKey()] as const,
    dir: (path: string) => ["workspace-files", sourceKey(), path] as const,
    content: (path: string) => ["workspace-file-content", sourceKey(), path] as const,
  },

  ingestion: {
    all: () => ["ingestion", sourceKey()] as const,
    connections: () => ["ingestion", sourceKey(), "connections"] as const,
    usage: (name: string) => ["ingestion", sourceKey(), "connections", name, "usage"] as const,
  },

  certificates: {
    detail: (projectId: string | null | undefined, runId: string | null | undefined) =>
      ["certificates", sourceKey(), projectId, runId] as const,
    diff: (projectId: string | null | undefined, runId: string | null | undefined, otherRunId: string | null | undefined) =>
      ["certificates", sourceKey(), "diff", projectId, runId, otherRunId] as const,
  },

  quality: {
    all: () => ["quality", sourceKey()] as const,
    checks: () => ["quality", sourceKey(), "checks"] as const,
    summary: (s: ScopeKey) => ["quality", sourceKey(), "summary", ...scope(s)] as const,
    score: (runId: string | undefined, s: ScopeKey) =>
      ["quality", sourceKey(), "score", runId, ...scope(s)] as const,
    reports: (dataset: string) => ["quality", sourceKey(), "reports", dataset] as const,
    runs: (dataset: string, s: ScopeKey) =>
      ["quality", sourceKey(), "reports", dataset, "all", ...scope(s)] as const,
    report: (dataset: string, runId: string | undefined, s: ScopeKey) =>
      ["quality", sourceKey(), "reports", dataset, runId ?? "latest", ...scope(s)] as const,
  },

  mlops: {
    mlPipelines: () => ["mlops", sourceKey(), "ml-pipelines"] as const,
    experiments: (s: ScopeKey) => ["mlops", sourceKey(), "experiments", ...scope(s)] as const,
    experiment: (experimentId: string, s: ScopeKey) =>
      ["mlops", sourceKey(), "experiments", experimentId, ...scope(s)] as const,
    models: (s: ScopeKey) => ["mlops", sourceKey(), "models", ...scope(s)] as const,
    modelVersions: (name: string, s: ScopeKey) =>
      ["mlops", sourceKey(), "models", name, ...scope(s)] as const,
  },
};
