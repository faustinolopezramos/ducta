import { useEffect, useMemo } from "react";
import { useEnvironments } from "../../api/queries";
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
  const options = ["base", ...envs.filter((e) => e !== "base")];

  useEffect(() => {
    if (data && activeEnv !== "base" && !envs.includes(activeEnv)) setActiveEnv("base");
  }, [data, envs, activeEnv, setActiveEnv]);

  const kind = envKind(activeEnv);
  return (
    <label className="env-switcher" data-env-kind={kind} title="Environment for runs, previews and validation">
      <span className="env-switcher__dot" aria-hidden="true" />
      <span className="sr-only">Environment</span>
      <select
        className="env-switcher__select"
        value={activeEnv}
        onChange={(e) => setActiveEnv(e.target.value)}
        aria-label="Environment"
      >
        {options.map((env) => (
          <option key={env} value={env}>
            {env}
          </option>
        ))}
      </select>
    </label>
  );
}
