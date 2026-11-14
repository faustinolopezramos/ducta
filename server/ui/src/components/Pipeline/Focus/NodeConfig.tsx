import { useEffectiveConfig } from "../../../api/queries";
import { Skeleton } from "../../ui/Skeleton";
import { InheritedValue, shortSource } from "../../ui/InheritedValue";

const EDITABLE: Record<string, "number" | "boolean" | "missing"> = {
  retry: "number",
  timeout_seconds: "number",
  fail_fast: "boolean",
  on_missing_input: "missing",
};

/**
 * The node's settings as they apply in each environment. A value set on the
 * node reads normally; one it inherits says from where (pipeline or project
 * defaults, the framework); ⚑ marks an environment that overrides it. Editing
 * sets it on the node itself, in its pipeline's file.
 */
export function NodeConfig({
  projectId,
  pipeline,
  node,
  activeEnv,
  onSet,
}: {
  projectId: string;
  pipeline: string;
  node: string;
  activeEnv: string;
  /** Set (value) or drop back to the inherited value (null). Absent: read-only. */
  onSet?: (key: string, value: unknown) => void;
}) {
  const { data, isLoading, isError } = useEffectiveConfig(projectId, pipeline, node);
  if (isLoading) return <Skeleton variant="block" height="120px" />;
  if (isError || !data) return <p className="focus-empty">The settings could not be read — check Problems.</p>;
  const envs = data.environments;

  return (
    <section className="focus-col node-config" aria-label="Settings by environment">
      <h4 className="focus-col-label">Settings, by environment</h4>
      <div className="node-config__scroll">
        <table className="node-config__table">
          <thead>
            <tr>
              <th scope="col">Key</th>
              {envs.map((env) => (
                <th scope="col" key={env} className={env === activeEnv ? "is-active" : undefined}>{env}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <th scope="row" className="node-config__key">{row.key}</th>
                {envs.map((env) => (
                  <td key={env} className={env === activeEnv ? "is-active" : undefined}>
                    {env === "base" && onSet && EDITABLE[row.key] ? (
                      <EditCell
                        kind={EDITABLE[row.key]}
                        value={row.values.base}
                        own={row.sources.base === "node"}
                        source={row.sources.base}
                        onSet={(v) => onSet(row.key, v)}
                      />
                    ) : (
                      <InheritedValue
                        value={row.values[env]}
                        source={row.sources[env]}
                        overridden={Boolean(row.overridden[env])}
                        showSource={env === "base" || Boolean(row.overridden[env])}
                      />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="focus-empty">Base values are set on the node. An environment overrides them in ducta.yaml.</p>
    </section>
  );
}

function EditCell({
  kind,
  value,
  own,
  source,
  onSet,
}: {
  kind: "number" | "boolean" | "missing";
  value: unknown;
  own: boolean;
  source: string;
  onSet: (v: unknown) => void;
}) {
  const reset = own ? (
    <button type="button" className="node-config__reset" title={`Drop it: inherit from ${source === "node" ? "defaults" : source}`} aria-label="Use the inherited value" onClick={() => onSet(null)}>
      ↺
    </button>
  ) : null;
  if (kind === "boolean") {
    return (
      <span className="node-config__edit">
        <input type="checkbox" checked={Boolean(value)} aria-label="Value" onChange={(e) => onSet(e.target.checked)} />
        {!own && <span className="inherited-value__source">{shortSource(source)}</span>}
        {reset}
      </span>
    );
  }
  if (kind === "missing") {
    return (
      <span className="node-config__edit">
        <select aria-label="Value" value={value == null ? "" : String(value)} onChange={(e) => onSet(e.target.value || null)}>
          <option value="">— {shortSource(source)}</option>
          <option value="skip">skip</option>
          <option value="fail">fail</option>
        </select>
        {reset}
      </span>
    );
  }
  return (
    <span className="node-config__edit">
      <input
        type="number"
        min={kind === "number" ? 0 : undefined}
        defaultValue={value == null ? "" : String(value)}
        placeholder={shortSource(source)}
        aria-label="Value"
        onBlur={(e) => {
          const raw = e.target.value.trim();
          const next = raw === "" ? null : Number(raw);
          if (next !== value && !(next === null && !own)) onSet(next);
        }}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      />
      {!own && value != null && <span className="inherited-value__source">{shortSource(source)}</span>}
      {reset}
    </span>
  );
}
