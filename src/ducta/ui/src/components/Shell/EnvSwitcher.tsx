import { useEffect, useMemo } from "react";
import { useEnvironments, useExecutionList } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { envKind } from "./envKind";

/**
 * The environment everything runs and resolves against — one choice for the
 * whole app, always visible. Under a project it offers that project's
 * environments; an environment the project does not declare falls back to base.
 */
export function EnvSwitcher({ projectId }: { projectId?: string | null }) {
  const activeEnv = useSourceStore((s) => s.activeEnv) || "base";
  const setActiveEnv = useSourceStore((s) => s.setActiveEnv);
  const { data } = useEnvironments(projectId ?? undefined);
  const envs: string[] = useMemo(() => data?.environments ?? [], [data]);
  // Under a project, the canonical environments it does not declare say so:
  // they run, but with the base configuration — "staging" looked as real as dev.
  const declared: string[] | null = projectId && data?.declared?.length ? data.declared : null;
  const options = ["base", ...envs.filter((e) => e !== "base")].sort((a, b) =>
    declared ? Number(!declared.includes(a)) - Number(!declared.includes(b)) : 0,
  );

  useEffect(() => {
    // A fallback, not a choice: it leaves the first-visit pick below free to run.
    if (data && activeEnv !== "base" && !envs.includes(activeEnv)) useSourceStore.setState({ activeEnv: "base" });
  }, [data, envs, activeEnv]);

  // First visit (no environment ever chosen): start where the project's latest
  // run is, so its pages are not empty. After that the environment only changes
  // when the user changes it.
  const envPicked = useSourceStore((s) => s.envPicked);
  const pickInitialEnv = useSourceStore((s) => s.pickInitialEnv);
  const { data: runs } = useExecutionList(
    { project_id: projectId ?? undefined, limit: 200 },
    { enabled: Boolean(projectId) && !envPicked },
  );
  useEffect(() => {
    if (envPicked || !projectId || !data) return;
    const latest = runs?.executions?.[0]?.env;
    if (latest && (latest === "base" || envs.includes(latest))) pickInitialEnv(latest);
  }, [envPicked, projectId, data, envs, runs, pickInitialEnv]);

  const kind = envKind(activeEnv);
  return (
    <label className="env-switcher" data-env-kind={kind} title="Environment for runs, previews and validation">
      <span className="env-switcher__dot" aria-hidden="true" />
      <span className="sr-only">Environment</span>
      <select
        className="env-switcher__select"
        title={declared && !declared.includes(activeEnv) ? `${activeEnv} is not configured in this project: it runs with the base settings` : undefined}
        value={activeEnv}
        onChange={(e) => setActiveEnv(e.target.value)}
        aria-label="Environment"
      >
        {options.map((env) => (
          <option key={env} value={env}>
            {declared && !declared.includes(env) ? `${env} · not configured` : env}
          </option>
        ))}
      </select>
    </label>
  );
}
