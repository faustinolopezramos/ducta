import { useMemo } from "react";
import { useExecutionList } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import type { Execution } from "../../types";
import "./EnvHint.css";

/**
 * The busiest other environment, when *env* has no runs and another one does —
 * or null. Pure so the rule is testable without a query client.
 */
export function otherEnvWithRuns(
  runs: Pick<Execution, "env">[],
  env: string,
): { env: string; count: number } | null {
  const counts = new Map<string, number>();
  for (const r of runs) if (r.env) counts.set(r.env, (counts.get(r.env) ?? 0) + 1);
  if ((counts.get(env) ?? 0) > 0) return null;
  let best: { env: string; count: number } | null = null;
  for (const [name, count] of counts) if (!best || count > best.count) best = { env: name, count };
  return best;
}

/**
 * One line under an empty, environment-scoped view: "No runs in base — 24 runs
 * in dev. View dev". The environment only changes when the user clicks; pages
 * never switch it on their own.
 */
export function EnvHint({ projectId }: { projectId: string }) {
  const env = useSourceStore((s) => s.activeEnv) || "base";
  const setActiveEnv = useSourceStore((s) => s.setActiveEnv);
  const { data } = useExecutionList({ project_id: projectId, limit: 200 });
  const other = useMemo(() => otherEnvWithRuns(data?.executions ?? [], env), [data, env]);
  if (!other) return null;
  return (
    <p className="env-hint" role="status">
      No runs in <span className="mono">{env}</span> — {other.count} run{other.count === 1 ? "" : "s"} in{" "}
      <span className="mono">{other.env}</span>.{" "}
      <button type="button" className="env-hint__switch" onClick={() => setActiveEnv(other.env)}>
        View {other.env}
      </button>
    </p>
  );
}
