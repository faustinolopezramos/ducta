import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import client from "../../api/client";
import { useGitFileAt, useServerProject, useWorkspaceFileContent } from "../../api/queries";
import { DagCanvas } from "../Pipeline/DagCanvas";
import { Skeleton } from "../ui/Skeleton";
import { joinPath } from "../../pages/CodePage/paths";
import { itemsFromPipelineYaml } from "./pipelineGraph";

/** Rows in the longest chain of *items* — how tall the graph is drawn. */
export function graphDepth(items: { id: string; dependsOn?: string[] }[]): number {
  const byId = new Map(items.map((it) => [it.id, it]));
  const memo = new Map<string, number>();
  const depth = (id: string, seen: Set<string>): number => {
    if (memo.has(id)) return memo.get(id)!;
    if (seen.has(id)) return 1; // a cycle is drawn, not followed
    seen.add(id);
    const deps = (byId.get(id)?.dependsOn ?? []).filter((d) => byId.has(d));
    const d = 1 + Math.max(0, ...deps.map((dep) => depth(dep, seen)));
    memo.set(id, d);
    return d;
  };
  return Math.max(0, ...items.map((it) => depth(it.id, new Set())));
}

/** No toolbars over this canvas: a small even margin frames the graph. */
const RUN_GRAPH_PADDING = { top: "24px", right: "24px", bottom: "24px", left: "24px" } as const;

/**
 * A canvas sized to the graph — one row of nodes does not need the room of
 * five: about 120px a row plus the even margin, so one row is 150px.
 */
function graphHeight(items: { id: string; dependsOn?: string[] }[] | null): number | null {
  if (!items || items.length === 0) return null;
  return Math.min(480, 30 + graphDepth(items) * 120);
}

/**
 * The run on its graph: each node in the state the run left it — drawn as the
 * pipeline was at the run's commit, so a node renamed or removed since is
 * where it was, or as it is now, to compare.
 */
export function RunGraph({
  projectId,
  pipeline,
  commit,
  nodeStates,
  onSelectNode,
  successfulNodes,
}: {
  projectId: string;
  pipeline: string;
  commit?: string | null;
  nodeStates: Record<string, string>;
  /**
   * Without a certificate there are no per-node states; a run that succeeded
   * still says every node it ran succeeded — these (all nodes when empty).
   */
  successfulNodes?: string[] | "all";
  onSelectNode?: (node: string) => void;
}) {
  // Until someone picks, the version the run used — once the certificate says which.
  const [picked, setAsOf] = useState<"run" | "now" | null>(null);
  const asOf = picked ?? (commit ? "run" : "now");
  const { data: project } = useServerProject(projectId);
  const { data: locations } = useQuery<{ pipelines: Record<string, { file: string }> }>({
    queryKey: ["server-projects", projectId, "locations"],
    queryFn: () => client.get(`/projects/${projectId}/locations`).then((r) => r.data),
    enabled: !!projectId,
    retry: false,
  });
  const rel = locations?.pipelines[pipeline]?.file ?? `pipelines/${pipeline}.yaml`;
  const path = project ? joinPath(project.root ?? "", rel) : "";
  const then = useGitFileAt(path, asOf === "run" ? commit : null);
  const now = useWorkspaceFileContent(asOf === "now" ? path : "");
  const text = asOf === "run" ? (then.data?.exists ? then.data.content : null) : now.data?.content ?? null;
  const items = useMemo(() => (text ? itemsFromPipelineYaml(text, pipeline) : null), [text, pipeline]);
  const missingThen = asOf === "run" && then.data && !then.data.exists;
  const height = graphHeight(items);
  const states = useMemo(() => {
    if (!items || !successfulNodes || Object.keys(nodeStates).length > 0) return nodeStates;
    const ran = successfulNodes === "all" ? null : new Set(successfulNodes);
    return Object.fromEntries(
      items.filter((it) => !ran || ran.has(it.id)).map((it) => [it.id, "success"]),
    );
  }, [items, nodeStates, successfulNodes]);

  return (
    <div className="run-graph">
      {commit && (
        <div className="run-graph__toggle" role="radiogroup" aria-label="Which version of the pipeline">
          <button type="button" role="radio" aria-checked={asOf === "run"} onClick={() => setAsOf("run")}>
            As the run saw it ({commit.slice(0, 8)})
          </button>
          <button type="button" role="radio" aria-checked={asOf === "now"} onClick={() => setAsOf("now")}>
            As it is now
          </button>
        </div>
      )}
      <div className="run-graph__canvas" style={height ? { height } : undefined}>
        {missingThen ? (
          <p className="focus-empty">The pipeline file did not exist at {commit?.slice(0, 8)}.</p>
        ) : !items ? (
          <Skeleton variant="block" height="100%" />
        ) : (
          <DagCanvas
            fitPadding={RUN_GRAPH_PADDING}
            items={items}
            executionStates={states}
            onSelect={(sel) => sel?.kind === "node" && onSelectNode?.(sel.id)}
          />
        )}
      </div>
    </div>
  );
}
