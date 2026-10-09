import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { IconBell } from "@tabler/icons-react";
import client from "../../api/client";
import { EmptyState, PermittedButton, Skeleton } from "../../components/ui";
import { toastStore } from "../../hooks/useModalStack";
import { routes } from "../../utils/routes";

interface Channel {
  type: string;
  webhook_env?: string | null;
  url_env?: string | null;
  to: string[];
  configured: boolean;
}
interface Rule {
  when: string[];
  pipelines: string[];
  channels: Channel[];
}

/**
 * The project's `alerts:` rules, read from ducta.yaml: what each listens for,
 * where it sends, whether its secret is set in the server's environment — and
 * a test message to prove the route works before a real failure does.
 */
export function AlertRules({ projectId }: { projectId: string }) {
  const { data, isLoading, isError } = useQuery<{ rules: Rule[] }>({
    queryKey: ["server-projects", projectId, "alerts"],
    queryFn: () => client.get(`/projects/${projectId}/alerts`).then((r) => r.data),
    enabled: !!projectId,
  });
  const test = useMutation({
    mutationFn: (rule: number) => client.post(`/projects/${projectId}/alerts/test`, { rule }).then((r) => r.data),
    onSuccess: (d: { results: { channel: string; ok: boolean; error?: string }[] }) => {
      const failed = d.results.filter((r) => !r.ok);
      if (failed.length) toastStore.getState().show(`Not sent: ${failed.map((f) => `${f.channel} — ${f.error}`).join("; ")}`, "error");
      else toastStore.getState().show("Test alert sent", "success");
    },
  });

  if (isLoading) return <Skeleton variant="block" height="160px" />;
  if (isError || !data) return <p className="focus-empty">The alert rules could not be read — check Problems.</p>;
  if (data.rules.length === 0)
    return (
      <EmptyState
        icon={IconBell}
        title="No alerts"
        description="Add an alerts: block to ducta.yaml — e.g. when: [failure, quality_gate], with a slack channel whose webhook URL is in an environment variable."
        action={<Link to={routes.code(projectId, "ducta.yaml")}>Open ducta.yaml</Link>}
      />
    );
  return (
    <div className="alert-rules">
      <ul className="alert-rules__list">
        {data.rules.map((rule, i) => (
          <li key={i} className="alert-rules__rule">
            <div>
              <p className="alert-rules__on">
                On <strong>{rule.when.join(", ")}</strong> in <span className="mono">{rule.pipelines.join(", ")}</span>
              </p>
              <ul className="alert-rules__channels">
                {rule.channels.map((c, j) => (
                  <li key={j}>
                    <span className="mono">{c.type}</span>{" "}
                    {c.webhook_env || c.url_env ? <>via environment variable <span className="mono">{c.webhook_env || c.url_env}</span></> : c.to.join(", ")}{" "}
                    <span className={c.configured ? "alert-rules__ok" : "alert-rules__missing"}>
                      {c.configured ? "configured" : "not set on the server"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <PermittedButton permission="project.write" variant="secondary" size="sm" loading={test.isPending && test.variables === i} onClick={() => test.mutate(i)}>
              Send test
            </PermittedButton>
          </li>
        ))}
      </ul>
      <p className="focus-empty">
        Rules live in <Link to={routes.code(projectId, "ducta.yaml")}>ducta.yaml</Link>. Missed SLAs are checked by calling
        POST /api/projects/{projectId}/alerts/check from a schedule.
      </p>
    </div>
  );
}
