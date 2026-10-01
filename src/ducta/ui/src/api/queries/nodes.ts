import { useQuery } from "@tanstack/react-query";
import client from "../client";
import { qk } from "../queryKeys";

// ─────────────────────────────────────────────

// NODE QUERIES
// ─────────────────────────────────────────────

/**
 * GET /nodes
 * Returns { nodes: { [name]: spec }, count }.
 */
export const useNodes = () =>
  useQuery({
    queryKey: qk.nodes.all(),
    queryFn: () => client.get("/nodes").then((r) => r.data),
    staleTime: 60 * 1000,
  });

/**
 * GET /nodes/{name}
 * Returns { name, spec }.
 */
export const useNode = (name: string) =>
  useQuery({
    queryKey: qk.nodes.detail(name),
    queryFn: () => client.get(`/nodes/${name}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!name,
  });

/**
 * GET /nodes/{name}/code
 * Returns { name, module_path, code, size_bytes, exists }.
 * Note: This endpoint may not be available in all server versions.
 * If unavailable, we gracefully handle the error and use code from pipeline store.
 */
/**
 * The query behind `useNodeCode`, shared so a caller that needs the code once —
 * opening the editor from a list row — can `fetchQuery` it and hit the same cache.
 */
export const nodeCodeQuery = (name: string) => ({
  queryKey: qk.nodes.code(name),
  // Untyped like the endpoint's other consumers read it (NodeCodePage also uses `module_path`).
  queryFn: async (): Promise<any> => {
    try {
      const result = await client.get(`/nodes/${name}/code`);
      return result.data;
    } catch (error: any) {
      // If endpoint returns 404 or any error, return null instead of failing the query
      // The frontend will fall back to using code from the pipeline store
      if (error?.response?.status === 404 || error?.response?.status === 405) {
        return null;
      }
      throw error;
    }
  },
  staleTime: 30 * 1000,
});

export const useNodeCode = (name: string) =>
  useQuery({
    ...nodeCodeQuery(name),
    enabled: !!name,
  });
