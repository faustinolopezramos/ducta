import { useEffect } from "react";
import type React from "react";
import { Navigate, Outlet, useLocation, useParams, useSearchParams } from "react-router-dom";
import { useUIStore } from "../../store/uiStore";

/**
 * The `/p/:projectId` subtree. Remembers the project so the rail can offer it
 * again from workspace-wide pages (History, Git…), where the URL names none.
 */
export function ProjectScope() {
  const { projectId } = useParams<{ projectId: string }>();
  const setLastProjectId = useUIStore((s) => s.setLastProjectId);
  useEffect(() => {
    if (projectId) setLastProjectId(projectId);
  }, [projectId, setLastProjectId]);
  return <Outlet />;
}

/**
 * Pages that already filter by `?project=` (Quality, MLOps) — under a project
 * they start filtered to it. Only seeded when absent, so the page's own
 * project picker still works.
 */
export function WithProjectParam({ children }: { children: React.ReactNode }) {
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const missing = Boolean(projectId) && !searchParams.has("project");
  useEffect(() => {
    if (!missing || !projectId) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("project", projectId);
        return next;
      },
      { replace: true },
    );
  }, [missing, projectId, setSearchParams]);
  return missing ? null : <>{children}</>;
}

/** An old URL, sent to its new place with the query and hash it carried. */
export function LegacyRedirect({ to }: { to: (params: Record<string, string | undefined>) => string }) {
  const params = useParams();
  const { search, hash } = useLocation();
  const target = to(params);
  const joiner = target.includes("?") ? "&" : "?";
  return <Navigate to={`${target}${search ? joiner + search.slice(1) : ""}${hash}`} replace />;
}

/**
 * A workspace-wide copy of a project section (`/workspace/quality`, …): the
 * rail no longer offers it, so an old link goes to that section of the last
 * project opened — or shows the workspace-wide page when there is none yet.
 */
export function ToLastProject({ to, fallback }: { to: (projectId: string) => string; fallback: React.ReactNode }) {
  const lastProjectId = useUIStore((s) => s.lastProjectId);
  const { search, hash } = useLocation();
  if (!lastProjectId) return <>{fallback}</>;
  const target = to(lastProjectId);
  const joiner = target.includes("?") ? "&" : "?";
  return <Navigate to={`${target}${search ? joiner + search.slice(1) : ""}${hash}`} replace />;
}
