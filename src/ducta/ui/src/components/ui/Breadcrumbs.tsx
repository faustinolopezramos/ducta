import { Link, useMatches } from "react-router-dom";
import type { UIMatch } from "react-router-dom";
import { IconChevronRight } from "@tabler/icons-react";
import { useProjectStore } from "../../store/projectStore";
import { selectPresent } from "../../store/reducer";
import "./Breadcrumbs.css";

interface BreadcrumbHandle {
  breadcrumb?: (match: UIMatch) => string;
  /** The page draws this trail in its own toolbar (the pipeline canvas). */
  hideTrail?: boolean;
}

interface Crumb {
  pathname: string;
  label: string;
}

/**
 * Reads the `handle.breadcrumb` every route in App.tsx already declares —
 * previously dead, since nothing called `useMatches()` to consume it — and
 * renders it as a clickable trail. Mounted once in MainLayout so every page
 * under RequireWorkspace gets a consistent hierarchy indicator instead of
 * the handful of pages that hand-rolled their own (or the majority that had
 * none at all).
 *
 * "Projects" is always the first crumb: it's the true root of every
 * workspace-scoped page, but only the /projects route itself declares a
 * breadcrumb handle for it, so relying on handles alone would leave every
 * other page (Quality, MLOps, a pipeline, ...) without a way back.
 */
export function Breadcrumbs() {
  const matches = useMatches();
  const outerState = useProjectStore();
  const { projects } = selectPresent(outerState);

  // Every wrapper route (RequireWorkspace, WorkspaceShellWrapper, ...) is
  // handle-less, so at most one match ever carries a breadcrumb — the leaf.
  const current = matches.find(
    (m): m is UIMatch & { handle: BreadcrumbHandle } =>
      Boolean((m.handle as BreadcrumbHandle | undefined)?.breadcrumb),
  );
  // No handle at all, or already on /projects — the trail would be redundant
  // with the page's own title.
  if (!current || current.pathname === "/projects") return null;
  // Drawn by the page itself; a second copy here would cost the canvas a row.
  if (current.handle.hideTrail) return null;

  const params = current.params as Record<string, string | undefined>;
  const resolveProject = (id: string) => projects.find((p) => p.id === id)?.name ?? id;

  const crumbs: Crumb[] = [{ pathname: "/projects", label: "Projects" }];

  // "project/:projectId/pipeline/:pipelineId" is a flat sibling route, not
  // nested under "project/:projectId" — it never separately matches the
  // project route, so that intermediate crumb has to be synthesized from
  // params rather than found in `matches`.
  if (params.projectId && params.pipelineId) {
    crumbs.push({ pathname: `/project/${params.projectId}`, label: resolveProject(params.projectId) });
  }

  let label = current.handle.breadcrumb!(current);
  if (params.projectId) label = label.split(params.projectId).join(resolveProject(params.projectId));
  crumbs.push({ pathname: current.pathname, label });

  return (
    <nav className="ducta-breadcrumbs" aria-label="Breadcrumb">
      {crumbs.map((crumb, i) => {
        const isLast = i === crumbs.length - 1;
        return (
          <span className="ducta-breadcrumbs__item" key={crumb.pathname}>
            {i > 0 && (
              <IconChevronRight
                size={13}
                stroke={1.6}
                className="ducta-breadcrumbs__sep"
                aria-hidden="true"
              />
            )}
            {isLast ? (
              <span className="ducta-breadcrumbs__current" aria-current="page">
                {crumb.label}
              </span>
            ) : (
              <Link to={crumb.pathname} className="ducta-breadcrumbs__link">
                {crumb.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
