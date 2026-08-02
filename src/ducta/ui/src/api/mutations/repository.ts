import { useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { defaultOnError, onForbiddenError } from "./errors";

export interface RepositoryConnectPayload {
  type: "local" | "github" | "azure" | "aws" | string;
  branch?: string;
  org?: string;
  repo?: string;
  project?: string;
  region?: string;
  token?: string;
  aws_https_username?: string;
  aws_https_password?: string;
}

interface BranchPayload {
  branch?: string;
}

// ── Repository Mutations ──────────────────────────────────────────────────────

export const useRepositoryConnect = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (config: RepositoryConnectPayload) =>
      client.post("/repository/connect", config).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repository"] });
    },
    onError: defaultOnError,
  });
};

export const useRepositoryPush = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ branch }: BranchPayload = {}) =>
      client.post("/repository/push", { branch: branch ?? "main" }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repository"] });
    },
    onError: onForbiddenError,
  });
};

export const useRepositoryPull = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ branch }: BranchPayload = {}) =>
      client.post("/repository/pull", { branch: branch ?? "main" }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repository"] });
      queryClient.invalidateQueries({ queryKey: ["git"] });
    },
    onError: onForbiddenError,
  });
};
