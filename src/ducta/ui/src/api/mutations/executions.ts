import { useMutation, useQueryClient } from "@tanstack/react-query";
import client from "../client";
import { sourceKey } from "../utils";
import { toastStore } from "../../hooks/useModalStack";
import { defaultOnError } from "./errors";

// ── Execution Mutations ───────────────────────────────────────────────────────

/**
 * POST /executions/{executionId}/retry
 * Clones a terminal execution and re-enqueues it with the same parameters.
 */
export const useRetryExecution = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (executionId: string) =>
      client.post(`/executions/${executionId}/retry`).then((r) => r.data),
    onSuccess: (_data: unknown, executionId: string) => {
      queryClient.invalidateQueries({ queryKey: ["executions", sourceKey(), executionId] });
      queryClient.invalidateQueries({ queryKey: ["executions", sourceKey()] });
      toastStore.getState().show("Execution retried — new run queued.", "success");
    },
    onError: defaultOnError,
  });
};

/**
 * POST /executions/bulk-cancel
 * Cancels multiple executions at once. Returns { cancelled, skipped }.
 */
export const useBulkCancelExecutions = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (executionIds: string[]) =>
      client.post("/executions/bulk-cancel", { execution_ids: executionIds }).then((r) => r.data),
    onSuccess: (data: { cancelled?: string[]; skipped?: string[] }) => {
      queryClient.invalidateQueries({ queryKey: ["executions", sourceKey()] });
      const n = data?.cancelled?.length ?? 0;
      toastStore.getState().show(`Cancelled ${n} execution${n !== 1 ? "s" : ""}.`, "success");
    },
    onError: defaultOnError,
  });
};

/**
 * POST /executions/{executionId}/cancel
 * Cancels a running or pending pipeline execution.
 */
export const useCancelExecution = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (executionId: string) =>
      client.post(`/executions/${executionId}/cancel`).then((r) => r.data),
    onSuccess: (_data: unknown, executionId: string) => {
      queryClient.invalidateQueries({ queryKey: ["executions", sourceKey(), executionId] });
      queryClient.invalidateQueries({ queryKey: ["executions", sourceKey()] });
    },
    onError: defaultOnError,
  });
};
