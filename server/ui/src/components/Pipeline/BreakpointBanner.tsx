import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import client from "../../api/client";
import { useCancelExecution } from "../../api/mutations";
import { qk } from "../../api/queryKeys";

/**
 * A run with a data breakpoint. It pauses after the node — its output written,
 * nothing downstream started — so the data can be looked at (Data tab), then
 * the same run continues, or stops there.
 */
export function BreakpointBanner({
  breakpoint,
  onInspect,
  onDismiss,
}: {
  breakpoint: { node: string; execId: string | null };
  onInspect: () => void;
  onDismiss: () => void;
}) {
  const queryClient = useQueryClient();
  const id = breakpoint.execId ?? "";
  const { data } = useQuery<{ status: string; paused_at?: string | null }>({
    queryKey: qk.executions.detail(id),
    queryFn: () => client.get(`/executions/${id}`).then((r) => r.data),
    enabled: !!id,
    // Watch closely: the pause is a moment someone is waiting for.
    refetchInterval: (q) => (["pending", "running", "paused"].includes(q.state.data?.status ?? "pending") ? 2000 : false),
  });
  const resume = useMutation({
    mutationFn: () => client.post(`/executions/${id}/resume`).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.executions.detail(id) }),
  });
  const { mutate: cancel } = useCancelExecution();
  const status = data?.status;

  return (
    <div className="breakpoint-banner" role="status" aria-live="polite" data-no-pan>
      <span className="breakpoint-banner__icon" aria-hidden="true">⏸</span>
      <span>
        {status === "paused" ? (
          <>Paused after <strong>{data?.paused_at ?? breakpoint.node}</strong> — its output is written; nothing after it has started.</>
        ) : status === "success" ? (
          <>The run went past <strong>{breakpoint.node}</strong> and finished.</>
        ) : status === "failed" || status === "cancelled" ? (
          <>The run {status === "failed" ? "failed" : "was stopped"}{status === "failed" ? <> before or after <strong>{breakpoint.node}</strong></> : null}.</>
        ) : (
          <>Running — it will pause after <strong>{breakpoint.node}</strong>…</>
        )}
      </span>
      {status === "paused" && (
        <>
          <button type="button" className="breakpoint-banner__btn" onClick={onInspect}>Inspect data</button>
          <button type="button" className="breakpoint-banner__btn is-primary" onClick={() => resume.mutate()} disabled={resume.isPending}>
            Continue ▶
          </button>
          <button type="button" className="breakpoint-banner__btn" onClick={() => cancel(id)}>Stop here</button>
        </>
      )}
      <button type="button" className="breakpoint-banner__close" aria-label="Dismiss" onClick={onDismiss}>×</button>
    </div>
  );
}
