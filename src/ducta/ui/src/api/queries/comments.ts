import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import client from "../client";

export interface CommentReply {
  id: string;
  author: string;
  body: string;
  created_at: string;
}

export interface CommentThread {
  id: string;
  anchor: { pipeline?: string; node?: string; file?: string; line?: number };
  author: string;
  body: string;
  created_at: string;
  resolved: boolean;
  resolved_by?: string | null;
  replies: CommentReply[];
}

export type CommentFilter = { node?: string; pipeline?: string; file?: string };

const base = (projectId: string) => ["server-projects", projectId, "comments"];

/** GET /projects/{id}/comments — threads, optionally about one node or file. */
export const useComments = (projectId: string, filter: CommentFilter = {}, enabled = true) =>
  useQuery<{ threads: CommentThread[] }>({
    queryKey: [...base(projectId), filter],
    queryFn: () => client.get(`/projects/${projectId}/comments`, { params: filter }).then((r) => r.data),
    enabled: enabled && !!projectId,
    staleTime: 15 * 1000,
  });

/** Add, reply, resolve and delete — each refreshes every comment view of the project. */
export const useCommentActions = (projectId: string) => {
  const queryClient = useQueryClient();
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: base(projectId) });
    queryClient.invalidateQueries({ queryKey: ["git"] });
  };
  const url = `/projects/${projectId}/comments`;
  return {
    add: useMutation({
      mutationFn: (v: { anchor: CommentThread["anchor"]; body: string }) => client.post(url, v).then((r) => r.data as CommentThread),
      onSuccess: refresh,
    }),
    reply: useMutation({
      mutationFn: (v: { id: string; body: string }) => client.post(`${url}/${v.id}/replies`, { body: v.body }).then((r) => r.data),
      onSuccess: refresh,
    }),
    resolve: useMutation({
      mutationFn: (v: { id: string; resolved: boolean }) => client.patch(`${url}/${v.id}`, { resolved: v.resolved }).then((r) => r.data),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => client.delete(`${url}/${id}`).then((r) => r.data),
      onSuccess: refresh,
    }),
  };
};
