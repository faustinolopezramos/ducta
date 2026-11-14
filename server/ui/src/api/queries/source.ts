import { useQuery } from "@tanstack/react-query";
import client from "../client";
import axios from "axios";
import type { WorkspaceInfo } from "../../types/api";
import { qk } from "../queryKeys";

// ─────────────────────────────────────────────
// SOURCE QUERIES — TanStack Query hooks for
// reading source and config data from the API.
// ─────────────────────────────────────────────

/**
 * GET /workspace
 * Returns current source metadata (name, path, git info, active env).
 */
export const useSourceInfo = () =>
  useQuery<WorkspaceInfo>({
    queryKey: qk.source(),
    queryFn: () => client.get<WorkspaceInfo>("/workspace").then((r) => r.data),
    staleTime: 2 * 60 * 1000, // 2 min
    retry: 1,
  });

/**
 * GET /environments
 * Returns { environments: string[], count } — the environments the project declares
 * (`environments:` in ducta.yaml).
 * `project`, when given, resolves the environments of a different project
 * than the one the connected source belongs to (see WorkspaceManager.for_project).
 */
export const useEnvironments = (project?: string) =>
  useQuery({
    queryKey: qk.environments(project),
    queryFn: () => client.get("/environments", { params: { project } }).then((r) => r.data),
    staleTime: 5 * 60 * 1000, // 5 min — envs rarely change
  });

/**
 * GET /health/platform  (no auth required)
 * Returns OS, architecture, Python version and git availability.
 * Uses a plain axios call (not the authed client) so it works before login.
 */
export const usePlatformInfo = () => {
  const baseURL = client.defaults.baseURL?.replace(/\/api$/, "") ?? "";
  return useQuery({
    queryKey: qk.platform(),
    queryFn: () => axios.get(`${baseURL}/health/platform`).then((r) => r.data),
    staleTime: Infinity,   // platform info never changes during a session
    retry: 2,
  });
};

/**
 * GET /git/config
 * Returns { name, email, configured } from the workspace git config.
 */
export const useGitConfig = () =>
  useQuery({
    queryKey: qk.git.config(),
    queryFn: () => client.get("/git/config").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

/**
 * GET /configs/{env}
 * Returns all config files for the given environment as a
 * { [name]: ConfigFileResponse } map.
 * Only runs when env is provided.
 */
export const useWorkspaceConfigs = (env: string) =>
  useQuery({
    queryKey: qk.configs.list(env),
    queryFn: () => client.get(`/configs/${env}`).then((r) => r.data),
    staleTime: 60 * 1000, // 1 min
    enabled: !!env,
  });

/**
 * GET /configs/{env}/{name}
 * Returns a single config file for the given environment and name.
 */
export const useWorkspaceConfig = (env: string, name: string) =>
  useQuery({
    queryKey: qk.configs.file(env, name),
    queryFn: () => client.get(`/configs/${env}/${name}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!env && !!name,
  });
