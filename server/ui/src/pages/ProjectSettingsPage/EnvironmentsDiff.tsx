import { useMemo, useState } from "react";
import { IconAdjustments } from "@tabler/icons-react";
import { useEnvironmentsCompare } from "../../api/queries";
import { EmptyState, Skeleton } from "../../components/ui";
import "./EnvironmentsDiff.css";

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * A table of key × environment with the values in force. A cell an
 * environment overrides is marked (⚑), so the rows where prod differs from
 * dev are found by eye — or by "only differences".
 */
export function EnvironmentsDiff({ projectId }: { projectId: string }) {
  const { data, isLoading, isError } = useEnvironmentsCompare(projectId);
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [filter, setFilter] = useState("");

  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (data?.rows ?? []).filter((r) => (!onlyDiff || r.differs) && (!q || r.key.toLowerCase().includes(q)));
  }, [data, onlyDiff, filter]);

  if (isLoading) return <Skeleton variant="block" height="240px" />;
  if (isError || !data)
    return (
      <EmptyState
        icon={IconAdjustments}
        title="Could not compare environments"
        description="The project's configuration did not load. Check Problems for configuration errors."
      />
    );
  if (data.environments.length < 2)
    return (
      <EmptyState
        icon={IconAdjustments}
        title="No environments"
        description="This project declares no environments in ducta.yaml, so every run uses the base configuration."
      />
    );

  return (
    <div className="env-diff">
      <div className="env-diff__toolbar">
        <input
          className="env-diff__filter"
          type="search"
          placeholder="Filter keys…"
          aria-label="Filter keys"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className="env-diff__check">
          <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} />
          Only differences
        </label>
        <span className="env-diff__count">{rows.length} keys</span>
      </div>
      <div className="env-diff__scroll">
        <table className="env-diff__table">
          <thead>
            <tr>
              <th scope="col">Key</th>
              {data.environments.map((env) => (
                <th scope="col" key={env} data-env={env}>
                  {env}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className={row.differs ? "is-diff" : undefined}>
                <th scope="row" className="env-diff__key">{row.key}</th>
                {data.environments.map((env) => {
                  const overridden = row.overridden[env];
                  return (
                    <td key={env} className={overridden ? "is-overridden" : undefined}>
                      {overridden && <span className="env-diff__flag" aria-label="overridden">⚑ </span>}
                      {show(row.values[env])}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="env-diff__empty">No environment changes anything that matches.</p>}
      </div>
    </div>
  );
}
