import React, { useEffect, useCallback, useState, useMemo, lazy, Suspense } from "react";
import {
  createBrowserRouter,
  RouterProvider,
  Outlet,
  useNavigate,
  Navigate,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
const ReactQueryDevtools = lazy(() => import("@tanstack/react-query-devtools").then(m => ({ default: m.ReactQueryDevtools })));
import { colors } from "./theme/tokens";
import { useProjectStore } from "./store/projectStore";
import { useBuilderStore } from "./store/builderStore";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastContainer } from "./components/Toast";
import { PerfMonitor } from "./components/ui/PerfMonitor";
import { useToastStack } from "./hooks/useModalStack";
import { useWorkspaceSelection } from "./hooks/useWorkspaceSelection";
import { initializeErrorHandling } from "./utils/errorHandler";
import { LoginPage } from "./pages/LoginPage";
import { ProtectedRoute } from "./components/Auth/ProtectedRoute";
import { RequireWorkspace } from "./components/Auth/RequireWorkspace";
import { ProjectsList } from "./components/ProjectsList";
import { ProjectPage } from "./pages/ProjectPage";
import { PipelinePage } from "./pages/PipelinePage";
import { useExecutionNotifications } from "./hooks/useExecutionNotifications";

// ── Extracted sub-components ──────────────────────────────────────────────────
import { UnauthorizedRedirect } from "./components/App/UnauthorizedRedirect";
import { GitSetupGate } from "./components/App/GitSetupGate";
import { ServerProjectsHydrator } from "./components/App/ServerProjectsHydrator";
import { PageLoader, RootRedirect } from "./components/App/PageRedirects";
import { ConnectWorkspaceForm } from "./components/Workspace/ConnectWorkspaceForm";

// ── Lazy-loaded pages ────────────────────────────────────────────────────────
const NodeCodePage         = lazy(() => import("./pages/NodeCodePage")        .then(m => ({ default: m.NodeCodePage })));
const ExecutionHistoryPage = lazy(() => import("./pages/ExecutionHistoryPage").then(m => ({ default: m.ExecutionHistoryPage })));
const GitPage              = lazy(() => import("./pages/GitPage")             .then(m => ({ default: m.GitPage })));
const MLOpsPage            = lazy(() => import("./pages/MLOpsPage")          .then(m => ({ default: m.MLOpsPage })));
const QualityPage          = lazy(() => import("./pages/QualityPage"));
const IngestionPage        = lazy(() => import("./pages/IngestionPage"));
const SchedulesPage        = lazy(() => import("./pages/SchedulesPage"));

import { useUIStore } from "./store/uiStore";

// ── Route helpers ─────────────────────────────────────────────────────────────

function WorkspaceShellWrapper() {
  const { selectedSource } = useWorkspaceSelection();
  if (!selectedSource) return null;
  return <Outlet />;
}

// Reads the project store itself so the router stays static: subscribing in App
// and closing `projects` into the route element would recreate the router (and
// re-render the whole tree) on every project mutation.
function ProjectsListRoute() {
  const projects = useProjectStore((s) => s.present.projects);
  const dispatch = useProjectStore((s) => s.dispatch);
  return (
    <ProjectsList
      projects={projects}
      onDeleteProject={(id: string) => dispatch({ type: "DELETE_PROJECT", payload: id })}
    />
  );
}

// ── Main content shell ────────────────────────────────────────────────────────

export function AppContent() {
  const { selectedSource, isLoading: workspaceLoading } = useWorkspaceSelection();
  const theme = useUIStore(s => s.theme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const projects = useProjectStore(s => s.present.projects);
  const dispatch = useProjectStore(s => s.dispatch);
  const canUndo = useProjectStore(s => s.past.length > 0);
  const canRedo = useProjectStore(s => s.future.length > 0);
  const { toasts, dismiss } = useToastStack();

  useExecutionNotifications();

  useEffect(() => { initializeErrorHandling(); }, []);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement | null;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
      return;
    }

    const isMac = /mac/i.test(navigator.userAgent);
    const ctrl  = isMac ? e.metaKey : e.ctrlKey;
    if (!ctrl) return;

    const isPipelineView = globalThis.location?.pathname?.includes("/pipeline/");

    if (e.key === "z" && !e.shiftKey) {
      e.preventDefault();
      if (isPipelineView) {
        useBuilderStore.getState().undo();
      } else {
        dispatch({ type: "UNDO" });
      }
    }
    if (e.key === "y" || (e.key === "z" && e.shiftKey)) {
      e.preventDefault();
      if (isPipelineView) {
        useBuilderStore.getState().redo();
      } else {
        dispatch({ type: "REDO" });
      }
    }
  }, [dispatch]);

  useEffect(() => {
    globalThis.addEventListener("keydown", handleKeyDown);
    return () => globalThis.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  if (workspaceLoading) {
    return (
      <div style={{ backgroundColor: colors.bg, height: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: colors.textMuted, fontSize: 14, fontFamily: "var(--font-sans)" }}>
          Initializing…
        </div>
      </div>
    );
  }

  return (
    <>
      {selectedSource && <ServerProjectsHydrator />}
      <div className="ducta-app-root">
        <UnauthorizedRedirect />
        <GitSetupGate>
          <Suspense fallback={<PageLoader />}>
            <Outlet context={{ projects, dispatch, canUndo, canRedo, selectedSource }} />
          </Suspense>
        </GitSetupGate>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </>
  );
}

// ── Error fallback for React Router ──────────────────────────────────────────
function ErrorFallback() {
  return (
    <div style={{ padding: 40, fontFamily: "var(--font-sans)", background: "var(--bg)", minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <div style={{ maxWidth: 600, textAlign: "center" }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: "var(--text)", marginBottom: 8 }}>Unexpected Application Error</h1>
        <p style={{ fontSize: 14, color: "var(--text-muted)", marginBottom: 16 }}>Check the browser console for detailed error information.</p>
        <button onClick={() => globalThis.location.reload()} style={{ marginTop: 16, padding: "8px 24px", border: "none", borderRadius: 6, background: "var(--primary)", color: "#fff", cursor: "pointer", fontWeight: 600 }}>Reload</button>
      </div>
    </div>
  );
}

// ── App (QueryClient + Router) ────────────────────────────────────────────────

export default function App() {
  const [queryClient] = useState(() =>
    new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 2 * 60 * 1000 } } })
  );

  const router = useMemo(() => createBrowserRouter([
    {
      path: "/",
      element: <AppContent />,
      errorElement: <ErrorFallback />,
      children: [
        { index: true, element: <RootRedirect /> },
        { path: "login", element: <LoginPage /> },
        {
          element: <ProtectedRoute><Outlet /></ProtectedRoute>,
          children: [
            { path: "setup", element: <ConnectWorkspaceForm />, handle: { breadcrumb: () => "Setup" } },
            {
              element: <RequireWorkspace />,
              children: [
                {
                  path: "projects",
                  handle: { breadcrumb: () => "Projects" },
                  element: <ProjectsListRoute />,
                },
                { path: "project/:projectId", handle: { breadcrumb: (d: any) => d?.params?.projectId ?? "Project" }, element: <ProjectPage /> },
                { path: "project/:projectId/pipeline/:pipelineId", handle: { breadcrumb: (d: any) => d?.params?.pipelineId ?? "Pipeline" }, element: <PipelinePage /> },
                {
                  path: "workspace",
                  element: <WorkspaceShellWrapper />,
                  children: [
                    { path: "nodes/:name/code", element: <NodeCodePage />, handle: { breadcrumb: (d: any) => `Node: ${d?.params?.name}` } },
                    { path: "executions", element: <ExecutionHistoryPage />, handle: { breadcrumb: () => "Executions" } },
                    { path: "quality", element: <QualityPage />, handle: { breadcrumb: () => "Quality" } },
                    { path: "ingestion", element: <IngestionPage />, handle: { breadcrumb: () => "Ingestion" } },
                    { path: "git", element: <GitPage />, handle: { breadcrumb: () => "Git" } },
                    { path: "mlops", element: <MLOpsPage />, handle: { breadcrumb: () => "MLOps" } },
                    { path: "schedules", element: <SchedulesPage />, handle: { breadcrumb: () => "Schedules" } },
                  ],
                },
                { path: "*", element: <Navigate to="/" replace /> },
              ],
            },
          ],
        },
      ],
    },
  ]), []);

  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <RouterProvider router={router} />
      </ErrorBoundary>
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
      <PerfMonitor />
    </QueryClientProvider>
  );
}
