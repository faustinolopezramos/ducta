import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import type {
  WorkspaceProject,
  WorkspaceProjectList,
  WorkspaceProjectCreateRequest,
  WorkspaceProjectUpdateRequest,
} from "../../types";
import { qk } from "../queryKeys";

// ─────────────────────────────────────────────
// PROJECT QUERIES  (Workspace → Project hierarchy)
// ─────────────────────────────────────────────

/**
 * GET /projects
 * Returns { projects: WorkspaceProject[], count }.
 * These are the server-persisted projects stored in Git under projects/{id}/.
 */
export const useServerProjects = () =>
  useQuery<WorkspaceProjectList>({
    queryKey: qk.projects.all(),
    queryFn: () => client.get("/projects").then((r) => r.data),
    staleTime: 30 * 1000,
  });

/**
 * GET /projects/{id}
 */
export const useServerProject = (projectId: string) =>
  useQuery<WorkspaceProject>({
    queryKey: qk.projects.detail(projectId),
    queryFn: () => client.get(`/projects/${projectId}`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

/**
 * POST /projects/import — import an existing directory as a project.
 * The directory must already exist inside workspace/projects/.
 * Invalidates the project list on success.
 */
export const useImportServerProject = () => {
  const qc = useQueryClient();
  return useMutation<WorkspaceProject, Error, { path: string; name?: string; description?: string }>({
    mutationFn: (body) => client.post("/projects/import", body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.projects.all() });
    },
  });
};

/**
 * POST /projects — create a server project.
 * Invalidates the project list on success.
 */
export const useCreateServerProject = () => {
  const qc = useQueryClient();
  return useMutation<WorkspaceProject, Error, WorkspaceProjectCreateRequest>({
    mutationFn: (body) => client.post("/projects", body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.projects.all() });
    },
  });
};

/**
 * PATCH /projects/{id} — update project metadata.
 */
export const useUpdateServerProject = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<WorkspaceProject, Error, WorkspaceProjectUpdateRequest>({
    mutationFn: (body) => client.patch(`/projects/${projectId}`, body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.projects.all() });
    },
  });
};

/**
 * DELETE /projects/{id}
 */
export const useDeleteServerProject = () => {
  const qc = useQueryClient();
  return useMutation<void, Error, { projectId: string; force?: boolean }>({
    mutationFn: ({ projectId, force }) =>
      client.delete(`/projects/${projectId}`, { params: force ? { force: true } : {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.projects.all() });
    },
  });
};

// ── Workspace File Browser ────────────────────────────────────────────────────

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number | null;
}

/**
 * GET /workspace/files?path=
 * Lists directory contents inside the workspace.
 */
export const useWorkspaceFiles = (path: string = "") =>
  useQuery<{ path: string; entries: FileEntry[] }>({
    queryKey: qk.files.dir(path),
    queryFn: () =>
      client.get("/workspace/files", { params: { path } }).then((r) => r.data),
    staleTime: 10 * 1000,
  });

/**
 * GET /workspace/files/content?path=
 * Reads a text file from the workspace.
 */
export const useWorkspaceFileContent = (path: string) =>
  useQuery<{ path: string; content: string; size_bytes: number; version?: string }>({
    queryKey: qk.files.content(path),
    queryFn: () =>
      client.get("/workspace/files/content", { params: { path } }).then((r) => r.data),
    staleTime: 15 * 1000,
    enabled: !!path,
  });

export interface EnvironmentRow {
  key: string;
  values: Record<string, unknown>;
  differs: boolean;
  overridden: Record<string, boolean>;
}

export interface EnvironmentsCompare {
  environments: string[];
  rows: EnvironmentRow[];
}

/**
 * GET /projects/{id}/environments/compare
 * Every path and setting in force per environment, plus the catalog/pipeline
 * values an environment changes — "why does prod behave differently?".
 */
export const useEnvironmentsCompare = (projectId: string) =>
  useQuery<EnvironmentsCompare>({
    queryKey: [...qk.projects.detail(projectId), "environments-compare"],
    queryFn: () => client.get(`/projects/${projectId}/environments/compare`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

/** GET /projects/{id}/governance — protected environments, and whether this user may run there. */
export const useGovernance = (projectId: string) =>
  useQuery<{ protected_environments: string[]; can_run_protected: boolean; permission: string }>({
    queryKey: ["server-projects", projectId, "governance"],
    queryFn: () => client.get(`/projects/${projectId}/governance`).then((r) => r.data),
    enabled: !!projectId,
    staleTime: 60 * 1000,
  });
