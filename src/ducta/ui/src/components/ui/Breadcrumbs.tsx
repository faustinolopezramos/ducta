import { Link, useMatches } from "react-router-dom";
import type { UIMatch } from "react-router-dom";
import { IconChevronDown, IconChevronRight } from "@tabler/icons-react";
import { useCommandMenu } from "../Shell/commandStore";
import type { CommandKind } from "../Shell/commandIndex";
import { useProjectList } from "../../hooks/useProjects";
import "./Breadcrumbs.css";
import { routes } from "../../utils/routes";

interface BreadcrumbHandle {
  breadcrumb?: (match: UIMatch) => string;
  /** The page draws this trail in its own toolbar (the pipeline canvas). */
  hideTrail?: boolean;
}

interface Crumb {
  pathname: string;
  label: string;
  /** What its switcher lists: the crumb's siblings. */
  switchKinds?: CommandKind[];
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
  const { projects } = useProjectList();
  const showMenu = useCommandMenu((st) => st.show);

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

  // Every page under /p/:projectId — a pipeline, a dataset, the runs — sits
  // below its project. The project's own page carries the only breadcrumb
  // handle at that level, so its crumb is synthesized from params.
  const projectPath = params.projectId ? routes.project(params.projectId) : null;
  if (params.projectId && projectPath && current.pathname.replace(/\/$/, "") !== projectPath) {
    crumbs.push({ pathname: projectPath, label: resolveProject(params.projectId), switchKinds: ["project"] });
  }

  let label = current.handle.breadcrumb!(current);
  if (params.projectId) label = label.split(params.projectId).join(resolveProject(params.projectId));
  crumbs.push({
    pathname: current.pathname,
    label,
    switchKinds: params.dataset ? ["dataset"] : params.pipelineId ? ["pipeline"] : undefined,
  });

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
            {crumb.switchKinds && (
              <button
                type="button"
                className="ducta-breadcrumbs__switch"
                aria-label={`Switch ${crumb.switchKinds[0]}`}
                title={`Switch ${crumb.switchKinds[0]}`}
                onClick={() => showMenu("", crumb.switchKinds)}
              >
                <IconChevronDown size={12} stroke={1.8} aria-hidden="true" />
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}
