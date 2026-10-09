import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useBlocker, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { IconCode, IconMessageCircle, IconX } from "@tabler/icons-react";
import { nodesByFunction, useCodeIndex, useComments, useServerProject, useWorkspaceFileContent } from "../../api/queries";
import { CommentThreads } from "../../components/Comments/CommentThreads";
import { useFileSave } from "../../components/Editor/useFileSave";
import { ConflictBanner } from "../../components/Editor/ConflictBanner";
import { qk } from "../../api/queryKeys";
import { FileTree } from "../../components/FileTree";
import { EmptyState } from "../../components/ui/EmptyState";
import { Skeleton } from "../../components/ui/Skeleton";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import type { EditorCodeLens } from "../../components/CodeEditor";
import { routes } from "../../utils/routes";
import { joinPath, languageFor } from "./paths";
import { FileCompare, type CompareMode } from "../../components/Editor/FileCompare";
import { useSourceStore } from "../../store/workspace";
import "./CodePage.css";

const CodeEditor = lazy(() => import("../../components/CodeEditor").then((m) => ({ default: m.CodeEditor })));

/**
 * `/p/:projectId/code/<path>` — the project's files, with the nodes each
 * function runs as code lenses: from a function to its node in one click.
 *
 * The URL holds the open file and `?line=`; the other open tabs are this
 * page's own state, like an editor's — and so is what was typed in each of
 * them: switching tabs keeps it, closing a tab or leaving the page with it
 * unsaved asks first.
 */
export function CodePage() {
  const { projectId = "", "*": splat = "" } = useParams<{ projectId: string; "*": string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const line = Number(searchParams.get("line")) || undefined;

  const { data: project } = useServerProject(projectId);
  const root = project?.root ?? "";
  // Already decoded by react-router: decoding again threw on a "%" in a file name.
  const filePath = splat;
  const workspacePath = filePath ? joinPath(root, filePath) : "";

  const [tabs, setTabs] = useState<string[]>([]);
  const [prevFile, setPrevFile] = useState("");
  if (filePath && filePath !== prevFile) {
    setPrevFile(filePath);
    if (!tabs.includes(filePath)) setTabs([...tabs, filePath]);
  }

  // What was typed in each open file and not saved yet. The editor reports it;
  // a tab opened again gets it back as its draft.
  const [drafts, setDrafts] = useState<ReadonlyMap<string, string>>(() => new Map());
  const setDraft = useCallback((path: string, text: string | null) => {
    setDrafts((prev) => {
      if (text === null ? !prev.has(path) : prev.get(path) === text) return prev;
      const next = new Map(prev);
      if (text === null) next.delete(path);
      else next.set(path, text);
      return next;
    });
  }, []);
  const [dirty, setDirty] = useState<ReadonlySet<string>>(() => new Set());
  const markDirty = useCallback((path: string, isDirty: boolean) => {
    if (!isDirty) setDraft(path, null);
    setDirty((prev) => {
      if (prev.has(path) === isDirty) return prev;
      const next = new Set(prev);
      if (isDirty) next.add(path);
      else next.delete(path);
      return next;
    });
  }, [setDraft]);

  const open = (path: string, at?: number) => navigate(routes.code(projectId, path, at));
  const doCloseTab = (path: string) => {
    markDirty(path, false);
    const rest = tabs.filter((t) => t !== path);
    setTabs(rest);
    if (path === filePath) navigate(rest.length ? routes.code(projectId, rest[rest.length - 1]) : routes.code(projectId));
  };
  const [closing, setClosing] = useState<string | null>(null);
  const closeTab = (path: string) => (dirty.has(path) ? setClosing(path) : doCloseTab(path));

  // Leaving the page (not just moving between its files) with unsaved files asks
  // first; so does closing or reloading the browser tab.
  const codeRoot = routes.code(projectId);
  const blocker = useBlocker(
    ({ nextLocation }) =>
      dirty.size > 0 && nextLocation.pathname !== codeRoot && !nextLocation.pathname.startsWith(`${codeRoot}/`),
  );
  useEffect(() => {
    if (dirty.size === 0) return;
    const handler = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty.size]);

  const { data: file, isLoading, isError } = useWorkspaceFileContent(workspacePath);
  const { data: index } = useCodeIndex(projectId);

  // Line comments: a lens over each commented line opens the side panel; a new
  // thread is anchored at the cursor's line.
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [cursorLine, setCursorLine] = useState(1);
  const cursorSub = useRef<{ dispose: () => void } | null>(null);
  const { data: commentData } = useComments(projectId, { file: filePath }, !!filePath);
  const openThreads = useMemo(() => (commentData?.threads ?? []).filter((t) => !t.resolved), [commentData]);

  const lenses = useMemo<EditorCodeLens[]>(() => {
    const byFn = nodesByFunction(index, filePath);
    const functions = index?.files[filePath] ?? [];
    const byLine = new Map<number, EditorCodeLens["items"]>();
    for (const f of functions.filter((fn) => byFn.has(fn.name))) {
      byLine.set(
        f.line,
        byFn.get(f.name)!.map((n) => ({
          title: `◆ ${n.node}${n.pipeline ? ` · ${n.pipeline}` : ""}`,
          onClick: n.pipeline ? () => navigate(routes.node(projectId, n.pipeline!, n.node)) : undefined,
        })),
      );
    }
    const perLine = new Map<number, number>();
    for (const t of openThreads) if (t.anchor.line) perLine.set(t.anchor.line, (perLine.get(t.anchor.line) ?? 0) + 1);
    for (const [line, n] of perLine) {
      byLine.set(line, [
        ...(byLine.get(line) ?? []),
        { title: `${n} comment${n === 1 ? "" : "s"}`, onClick: () => setCommentsOpen(true) },
      ]);
    }
    return [...byLine].map(([line, items]) => ({ line, items }));
  }, [index, filePath, navigate, projectId, openThreads]);

  const fileSave = useFileSave(workspacePath, file?.version, () =>
    queryClient.invalidateQueries({ queryKey: qk.projects.codeIndex(projectId) }),
  );
  const save = fileSave.save;
  const isSaving = fileSave.isSaving;

  const treeActive = workspacePath || undefined;
  const [mode, setMode] = useState<"edit" | CompareMode>("edit");
  const activeEnv = useSourceStore((st) => st.activeEnv) || "base";
  // The pipeline whose last good run this file is compared with: the first that runs it.
  const pipelineOfFile = index?.nodes.find((n) => n.file === filePath)?.pipeline ?? null;

  return (
    <div className="code-page">
      <div className="code-page__tree">
        <FileTree
          rootPath={root}
          title={project?.name ?? projectId}
          newFileDir="src"
          activePath={treeActive}
          onSelectFile={(path) => open(root && path.startsWith(`${root}/`) ? path.slice(root.length + 1) : path)}
        />
      </div>
      <div className="code-page__main">
        {tabs.length > 0 && (
          <div className="code-page__tabs" role="tablist" aria-label="Open files">
            {tabs.map((t) => (
              <div key={t} className={`code-page__tab${t === filePath ? " is-active" : ""}${dirty.has(t) ? " is-dirty" : ""}`}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={t === filePath}
                  className="code-page__tab-name"
                  title={t}
                  onClick={() => open(t)}
                >
                  {t.split("/").pop()}
                  {dirty.has(t) && (
                    <span className="code-page__tab-dirty" aria-label="unsaved" title="Unsaved changes">●</span>
                  )}
                </button>
                <button
                  type="button"
                  className="code-page__tab-close"
                  aria-label={`Close ${t}`}
                  onClick={() => closeTab(t)}
                >
                  <IconX size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
        {filePath && (
          <div className="code-page__modes" role="tablist" aria-label="Edit or compare">
            {([
              ["edit", "Edit"],
              ["head", "Changes"],
              ["last-good", "Vs last good run"],
              ["history", "History"],
              ["branch", "Vs branch"],
            ] as const).map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={mode === id}
                className={`code-page__mode${mode === id ? " is-active" : ""}`} onClick={() => setMode(id)}>
                {label}
              </button>
            ))}
          </div>
        )}
        <div className="code-page__editor">
          {filePath && file && mode !== "edit" ? (
            <FileCompare
              mode={mode}
              projectId={projectId}
              path={workspacePath}
              language={languageFor(filePath)}
              current={file.content}
              pipeline={pipelineOfFile}
              env={activeEnv === "base" ? "dev" : activeEnv}
            />
          ) : !filePath ? (
            <EmptyState
              icon={IconCode}
              title="Open a file"
              description="Pick a file on the left. Functions that a node runs show that node above them — click it to see the node on its pipeline."
            />
          ) : isLoading ? (
            <Skeleton variant="block" height="100%" />
          ) : isError || !file ? (
            <EmptyState icon={IconCode} title="Could not open this file" description={workspacePath} />
          ) : (
            <Suspense fallback={<Skeleton variant="block" height="100%" />}>
              {fileSave.conflict && (
                <ConflictBanner
                  conflict={fileSave.conflict}
                  language={languageFor(filePath)}
                  onReload={fileSave.reload}
                  onKeepMine={fileSave.keepMine}
                  busy={isSaving}
                />
              )}
              <CodeEditor
                value={file.content}
                draft={drafts.get(filePath)}
                onChangeValue={(text) => setDraft(filePath, text)}
                onDirtyChange={(isDirty) => markDirty(filePath, isDirty)}
                filePath={filePath}
                gitPath={workspacePath}
                language={languageFor(filePath)}
                height="100%"
                onSave={save}
                isSaving={isSaving}
                revealLine={line}
                codeLenses={lenses}
                onEditorReady={(editor) => {
                  cursorSub.current?.dispose();
                  cursorSub.current = editor.onDidChangeCursorPosition((e) => setCursorLine(e.position.lineNumber));
                }}
                headerActions={
                  <button
                    type="button"
                    className={`code-page__comments-btn${commentsOpen ? " is-on" : ""}`}
                    onClick={() => setCommentsOpen((v) => !v)}
                    aria-pressed={commentsOpen}
                    title="Comments on this file"
                  >
                    <IconMessageCircle size={14} aria-hidden="true" />
                    {openThreads.length > 0 && <span>{openThreads.length}</span>}
                  </button>
                }
              />
            </Suspense>
          )}
        </div>
      </div>
      {commentsOpen && filePath && mode === "edit" && (
        <aside className="code-page__comments" aria-label={`Comments on ${filePath}`}>
          <header className="code-page__comments-head">
            <strong>Comments</strong>
            <span className="code-page__comments-hint">new ones go on line {cursorLine}</span>
            <button type="button" className="code-page__tab-close" aria-label="Close comments" onClick={() => setCommentsOpen(false)}>
              <IconX size={12} />
            </button>
          </header>
          <CommentThreads
            projectId={projectId}
            filter={{ file: filePath }}
            anchor={{ file: filePath, line: cursorLine }}
            label={`comments on ${filePath}`}
          />
        </aside>
      )}
      <ConfirmDialog
        open={closing !== null}
        title={`Close ${closing?.split("/").pop() ?? ""} without saving?`}
        description="What you typed in this file has not been saved. It will be lost."
        confirmLabel="Discard and close"
        tone="danger"
        onConfirm={() => {
          if (closing) doCloseTab(closing);
          setClosing(null);
        }}
        onCancel={() => setClosing(null)}
      />
      <ConfirmDialog
        open={blocker.state === "blocked"}
        title="Leave without saving?"
        description={`${dirty.size} open file${dirty.size === 1 ? " has" : "s have"} unsaved changes. They will be lost.`}
        confirmLabel="Discard changes"
        tone="danger"
        onConfirm={() => blocker.proceed?.()}
        onCancel={() => blocker.reset?.()}
      />
    </div>
  );
}
