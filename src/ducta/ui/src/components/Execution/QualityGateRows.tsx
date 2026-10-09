import { useEffect } from "react";
import { useNodeQuality, useTryChecks } from "../../api/queries";
import { FailingRows } from "../Quality/FailingRows";
import { Skeleton } from "../ui/Skeleton";

const ROW_CHECKS = new Set(["null_rate", "range", "duplicates", "prediction_contract", "business_rules"]);

/**
 * A quality gate stopped the run: which of the node's checks fail on the data
 * now, and the rows each one objects to.
 */
export function QualityGateRows({ projectId, pipeline, node, env }: { projectId: string; pipeline: string; node: string; env: string }) {
  const { data } = useNodeQuality(projectId, pipeline, node);
  const { mutate, data: tried, isPending } = useTryChecks(projectId);
  const dataset = data?.outputs[0];
  const checks = (data?.quality?.checks ?? {}) as Record<string, Record<string, unknown>>;
  const key = dataset ? JSON.stringify([dataset, env, checks]) : null;
  useEffect(() => {
    if (key && dataset && Object.keys(checks).length) mutate({ dataset, env, checks });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` captures dataset, env and checks
  }, [key]);

  if (!data || isPending) return <Skeleton variant="block" height="60px" />;
  const failing = (tried?.results ?? []).filter((r) => r.passed === false);
  if (!dataset || failing.length === 0) return null;
  return (
    <div className="diagnose__rows">
      <h3 className="diagnose__subhead">What fails in {dataset} now</h3>
      {failing.map((r) =>
        ROW_CHECKS.has(r.check_name) ? (
          <FailingRows key={r.check_name} projectId={projectId} dataset={dataset} env={env} check={r.check_name} params={checks[r.check_name] ?? {}} />
        ) : (
          <p key={r.check_name} className="failing-rows__count">
            <span className="mono">{r.check_name}</span>: {r.message}
          </p>
        ),
      )}
    </div>
  );
}
