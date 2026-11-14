import { useFailingRows } from "../../api/queries";
import { apiErrorMessage } from "../../api/mutations/errors";
import { Skeleton } from "../ui/Skeleton";

/** The rows a check fails on — the columns it looks at first. */
export function FailingRows({
  projectId,
  dataset,
  env,
  check,
  params,
}: {
  projectId: string;
  dataset: string;
  env: string;
  check: string;
  params: Record<string, unknown>;
}) {
  const { data, isLoading, error } = useFailingRows(projectId, { dataset, env, check, params });
  if (isLoading) return <Skeleton variant="block" height="80px" />;
  if (error) return <p className="focus-empty">{apiErrorMessage(error)}</p>;
  if (!data) return null;
  const watched = [params.column, ...((Array.isArray(params.columns) ? params.columns : []) as unknown[])].filter(
    (c): c is string => typeof c === "string",
  );
  const columns = [...watched, ...data.columns.filter((c) => !watched.includes(c))];
  return (
    <div className="failing-rows">
      <p className="failing-rows__count">
        {data.failing.toLocaleString()} of {data.scanned.toLocaleString()} rows fail <span className="mono">{check}</span>
        {data.failing > data.rows.length ? ` — the first ${data.rows.length}` : ""}
      </p>
      {data.rows.length > 0 && (
        <div className="failing-rows__scroll">
          <table className="failing-rows__table">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c} scope="col" className={watched.includes(c) ? "is-watched" : undefined}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c} className={watched.includes(c) ? "is-watched" : undefined}>
                      {row[c] === null || row[c] === undefined ? <span className="failing-rows__null">null</span> : String(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
