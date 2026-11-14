import { useExecutionStatus } from "../../api/queries";
import { StatusBadge } from "../ui/StatusBadge";
import { DataPreview } from "./Focus/DataPreview";

/**
 * The last sample run of a node: how it went, and what it produced — read
 * from the scratch area, so the real dataset is never what is shown here.
 */
export function SamplePreview({
  projectId,
  sample,
  outputs,
  env,
}: {
  projectId: string;
  sample: { node: string; execId: string | null; rows: number };
  outputs: string[];
  env: string;
}) {
  const { data } = useExecutionStatus(sample.execId ?? "");
  const status: string | undefined = data?.status;
  const done = status === "success";
  return (
    <div className="sample-preview">
      <p className="sample-preview__head">
        {status && <StatusBadge status={status} size="sm" />}
        <span>
          {sample.node} on the first {sample.rows} rows of each input, in {env}. Nothing real is written —
          outputs land in .ducta/scratch.
        </span>
      </p>
      {status === "failed" && data?.error_message && <p className="focus-alert">{data.error_message}</p>}
      {done ? (
        <DataPreview projectId={projectId} inputs={[]} outputs={outputs} env={env} scratch refreshKey={sample.execId} />
      ) : (
        !status || status === "pending" || status === "running" ? <p className="focus-empty">Running…</p> : null
      )}
    </div>
  );
}
