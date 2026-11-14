import { IconPlugConnected } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import client from "../../../api/client";
import { useNodeQuality } from "../../../api/queries";
import { useConnectionCredentials, useConnections, useRetestConnection } from "../../../api/ingestionApi";
import { PermittedButton } from "../../ui/PermittedButton";
import { routes } from "../../../utils/routes";

/**
 * An ingest node's connection: which one it reads through, whether that
 * connection's credentials are set where the API runs — never what they are —
 * and a test that it answers. Switching the connection edits the node.
 */
export function NodeConnection({
  projectId,
  pipeline,
  node,
  onSet,
}: {
  projectId: string;
  pipeline: string;
  node: string;
  onSet?: (key: string, value: unknown) => void;
}) {
  const { data } = useNodeQuality(projectId, pipeline, node);
  const { data: conns } = useConnections();
  const ingest = data?.ingest ?? null;
  const current = typeof ingest?.source === "string" ? ingest.source : null;
  const { data: creds } = useConnectionCredentials(current);
  const test = useRetestConnection();
  const { data: lineage } = useQuery<{ columns: { column: string; sources: string[] }[]; note?: string | null }>({
    queryKey: ["server-projects", projectId, "column-lineage", pipeline, node],
    queryFn: () =>
      client
        .get(`/projects/${projectId}/pipelines/${encodeURIComponent(pipeline)}/nodes/${encodeURIComponent(node)}/column-lineage`)
        .then((r) => r.data),
    enabled: data?.kind === "ingest",
  });
  if (data?.kind !== "ingest" || !ingest) return null;

  return (
    <section className="focus-col node-connection" aria-label="Connection">
      <h4 className="focus-col-label">Connection</h4>
      <div className="node-connection__row">
        <IconPlugConnected size={14} aria-hidden="true" />
        <select
          value={current ?? ""}
          disabled={!onSet}
          aria-label="Connection this node reads through"
          onChange={(e) => onSet?.("ingest", { ...ingest, source: e.target.value })}
        >
          {!current && <option value="">—</option>}
          {(conns?.connections ?? []).map((c) => (
            <option key={c.name} value={c.name}>
              {c.name} · {c.type} {c.host ? `@ ${c.host}` : ""}
            </option>
          ))}
        </select>
        <PermittedButton
          permission="ingestion.read"
          variant="ghost"
          size="sm"
          disabled={!current}
          loading={test.isPending}
          onClick={() => current && test.mutate(current)}
        >
          Test
        </PermittedButton>
      </div>
      {creds && (
        <ul className="node-connection__vars" aria-label="Credentials">
          {creds.variables.map((v) => (
            <li key={v.name} data-set={v.set}>
              <span className="mono">{v.name}</span> {v.set ? `set (${v.where})` : "not set where the API runs"}
            </li>
          ))}
        </ul>
      )}
      {test.data && (
        <p className={`node-tests__summary${test.data.ok ? " is-ok" : " is-bad"}`} role="status">
          {test.data.ok ? "Connected" : test.data.message}
        </p>
      )}
      <Link className="node-connection__manage" to={routes.section(projectId, "connections")}>Manage connections →</Link>
      {lineage && (
        <div className="node-connection__lineage">
          <h4 className="focus-col-label">Column lineage</h4>
          {lineage.columns.length > 0 ? (
            <table>
              <tbody>
                {lineage.columns.map((c) => (
                  <tr key={c.column}>
                    <th scope="row" className="mono">{c.column}</th>
                    <td className="mono">← {c.sources.join(", ") || "?"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {lineage.note && <p className="focus-empty">{lineage.note}</p>}
        </div>
      )}
    </section>
  );
}
