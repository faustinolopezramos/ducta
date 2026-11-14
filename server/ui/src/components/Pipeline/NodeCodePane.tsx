import { lazy, Suspense, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { IconArrowsMaximize, IconCode, IconFocusCentered, IconX } from "@tabler/icons-react";
import { nodesByFunction, useCodeIndex, useWorkspaceFileContent } from "../../api/queries";
import { useFileSave } from "../Editor/useFileSave";
import { ConflictBanner } from "../Editor/ConflictBanner";
import { qk } from "../../api/queryKeys";
import type { EditorCodeLens } from "../CodeEditor";
import { EmptyState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";
import { routes } from "../../utils/routes";

const CodeEditor = lazy(() => import("../CodeEditor").then((m) => ({ default: m.CodeEditor })));

interface NodeCodePaneProps {
  projectId: string;
  nodeId: string;
  onClose: () => void;
  /** Select another node — from a code lens over its function. */
  onSelectNode: (id: string) => void;
  /** Bring the node into view on the canvas. */
  onShowInGraph: (id: string) => void;
  onRunNode: (id: string) => void;
  /** ⌘⏎ / "▶ Sample": the node on the first rows of its inputs. */
  onRunSample?: (id: string) => void;
}

/**
 * The node's source file, beside the canvas, scrolled to the function it
 * runs. Every function a node runs carries that node above it (a code lens),
 * so the file reads as part of the graph: click to select it, ▶ to run it.
 */
export function NodeCodePane({ projectId, nodeId, onClose, onSelectNode, onShowInGraph, onRunNode, onRunSample }: NodeCodePaneProps) {
  const queryClient = useQueryClient();
  const { data: index, isLoading: indexLoading } = useCodeIndex(projectId);
  const entry = index?.nodes.find((n) => n.node === nodeId);
  const { data: file, isLoading: fileLoading } = useWorkspaceFileContent(entry?.workspace_file ?? "");
  const fileSave = useFileSave(entry?.workspace_file ?? "", file?.version, () => {
    queryClient.invalidateQueries({ queryKey: qk.projects.codeIndex(projectId) });
    queryClient.invalidateQueries({ queryKey: qk.nodes.code(nodeId) });
  });
  const isSaving = fileSave.isSaving;

  const lenses = useMemo<EditorCodeLens[]>(() => {
    if (!entry) return [];
    const byFn = nodesByFunction(index, entry.file);
    return (index?.files[entry.file] ?? [])
      .filter((f) => byFn.has(f.name))
      .map((f) => ({
        line: f.line,
        items: byFn.get(f.name)!.flatMap((n) => [
          {
            title: n.node === nodeId ? `◆ ${n.node}` : `◇ ${n.node}`,
            onClick: n.node === nodeId ? () => onShowInGraph(n.node) : () => onSelectNode(n.node),
          },
          { title: "▶ Run", onClick: () => onRunNode(n.node) },
          ...(onRunSample ? [{ title: "▶ Sample (⌘⏎)", onClick: () => onRunSample(n.node) }] : []),
        ]),
      }));
  }, [entry, index, nodeId, onRunNode, onRunSample, onSelectNode, onShowInGraph]);

  const save = (content: string) => (entry ? fileSave.save(content) : undefined);

  const header = (
    <div className="code-pane__head">
      <span className="code-pane__title" title={entry ? `${entry.module}:${entry.function}` : nodeId}>
        <IconCode size={14} aria-hidden="true" />
        {entry ? `${entry.module}:${entry.function}` : nodeId}
      </span>
      <div className="code-pane__actions">
        <button type="button" className="code-pane__btn" onClick={() => onShowInGraph(nodeId)} title="Show in graph (⌘⇧G)" aria-label="Show in graph">
          <IconFocusCentered size={15} />
        </button>
        {entry && (
          <Link className="code-pane__btn" to={routes.code(projectId, entry.file, entry.line ?? undefined)} title="Open in the code view" aria-label="Open in the code view">
            <IconArrowsMaximize size={15} />
          </Link>
        )}
        <button type="button" className="code-pane__btn" onClick={onClose} title="Close code" aria-label="Close code">
          <IconX size={15} />
        </button>
      </div>
    </div>
  );

  let body: React.ReactNode;
  if (indexLoading || (entry && fileLoading)) {
    body = <Skeleton variant="block" height="100%" />;
  } else if (!entry) {
    body = (
      <EmptyState
        icon={IconCode}
        title="No project code"
        description="This node runs no function of the project — an ingestion or a built-in step is configured, not coded."
      />
    );
  } else if (!entry.exists || !file) {
    body = (
      <EmptyState
        icon={IconCode}
        title={`${entry.file} does not exist`}
        description={`The node runs ${entry.module}:${entry.function}; create the file to give it code.`}
      />
    );
  } else {
    body = (
      <Suspense fallback={<Skeleton variant="block" height="100%" />}>
        {fileSave.conflict && (
          <ConflictBanner conflict={fileSave.conflict} language="python" onReload={fileSave.reload} onKeepMine={fileSave.keepMine} busy={isSaving} />
        )}
        <CodeEditor
          value={file.content}
          filePath={entry.file}
          gitPath={entry.workspace_file}
          language="python"
          height="100%"
          onSave={save}
          isSaving={isSaving}
          revealLine={entry.line ?? undefined}
          codeLenses={lenses}
          onRun={onRunSample ? () => onRunSample(nodeId) : undefined}
        />
      </Suspense>
    );
  }

  return (
    <section className="code-pane" aria-label={`Code of ${nodeId}`}>
      {header}
      <div className="code-pane__body">{body}</div>
      {entry && entry.line == null && entry.exists && (
        <p className="code-pane__warn" role="status">
          {entry.function}() is not defined in {entry.file} — the node cannot run until it is.
        </p>
      )}
    </section>
  );
}
