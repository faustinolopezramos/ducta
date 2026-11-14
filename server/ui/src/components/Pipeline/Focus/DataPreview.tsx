import { useEffect, useState } from "react";
import { useDatasetPreview } from "../../../api/queries";
import { Skeleton } from "../../ui/Skeleton";

/**
 * What the node reads and writes, as last materialized in the active
 * environment: columns with their types, and the first rows.
 */
export function DataPreview({
  projectId,
  inputs,
  outputs,
  env,
  scratch = false,
  refreshKey,
}: {
  projectId: string;
  inputs: string[];
  outputs: string[];
  env: string;
  /** Show what the last sample run wrote, not the real dataset. */
  scratch?: boolean;
  /** Changes when there is something new to read (a sample run finished). */
  refreshKey?: unknown;
}) {
  const options = [...outputs.map((d) => ({ d, side: "writes" })), ...inputs.map((d) => ({ d, side: "reads" }))];
  const [chosen, setChosen] = useState<string | null>(options[0]?.d ?? null);
  const { data, isLoading, refetch } = useDatasetPreview(projectId, chosen, env, 50, scratch);
  useEffect(() => {
    if (refreshKey !== undefined) void refetch();
  }, [refreshKey, refetch]);

  if (options.length === 0) return <p className="focus-empty">This node reads and writes no dataset.</p>;
  return (
    <section className="focus-col data-preview" aria-label="Data preview">
      {options.length > 1 && (
      <label className="data-preview__pick">
        <span className="focus-col-label">Dataset</span>
        <select value={chosen ?? ""} onChange={(e) => setChosen(e.target.value)}>
          {options.map(({ d, side }) => (
            <option key={`${side}:${d}`} value={d}>{side === "writes" ? "→ " : "← "}{d}</option>
          ))}
        </select>
      </label>
      )}
      {isLoading ? (
        <Skeleton variant="block" height="140px" />
      ) : !data ? null : !data.available ? (
        <p className="focus-empty">{data.reason}</p>
      ) : (
        <>
          <p className="data-preview__meta">
            {scratch ? "Sample run · " : ""}
            {data.total_rows != null ? `${data.total_rows.toLocaleString()} rows` : "rows"} · {data.columns.length} columns · {data.format} · {env}
          </p>
          <div className="data-preview__scroll">
            <table className="data-preview__table">
              <thead>
                <tr>
                  {data.columns.map((c) => (
                    <th key={c.name} scope="col" title={c.type}>
                      {c.name}
                      <span className="data-preview__type">{c.type}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i}>
                    {data.columns.map((c) => (
                      <td key={c.name}>{row[c.name] == null ? <span className="data-preview__null">null</span> : String(row[c.name])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
