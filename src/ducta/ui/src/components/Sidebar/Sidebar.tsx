import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  IconLayoutDashboard,
  IconGitBranch,
  IconBox,
  IconFlask,
  IconShieldCheck,
  IconSitemap,
  IconCode,
  IconPlayerPlay,
  IconSettings,
  IconHome,
  IconCertificate,
} from "@tabler/icons-react";
import { useUIStore } from "../../store/uiStore";
import { projectIdFromPath, routes } from "../../utils/routes";
import { useServerProjectPipelines } from "../../api/queries";

interface RailItem {
  label: string;
  icon: typeof IconBox;
  path: string;
  /** Active for exactly this path. */
  exact?: boolean;
  /** Other paths (and what is under them) this item stands for. */
  also?: string[];
  divideBefore?: boolean;
}

/**
 * What the rail offers: the open project's sections, then the workspace's.
 * One item per concept — Schedules live in Runs, Connections in Settings — and
 * Models only for a project that has a machine-learning pipeline.
 */
export function railItems(projectId: string | null, opts: { hasModels?: boolean } = {}): RailItem[] {
  const project: RailItem[] = projectId
    ? [
        { label: "Overview", icon: IconHome, path: routes.project(projectId), exact: true },
        {
          label: "Pipelines",
          icon: IconSitemap,
          path: routes.pipelines(projectId),
          also: [`/p/${encodeURIComponent(projectId)}/datasets`],
        },
        { label: "Code", icon: IconCode, path: routes.code(projectId) },
        { label: "Runs", icon: IconPlayerPlay, path: routes.runs(projectId), also: [routes.section(projectId, "schedules")] },
        { label: "Quality", icon: IconShieldCheck, path: routes.section(projectId, "quality") },
        ...(opts.hasModels ? [{ label: "Models", icon: IconFlask, path: routes.section(projectId, "models") }] : []),
        { label: "Settings", icon: IconSettings, path: routes.section(projectId, "settings") },
      ]
    : [];
  const workspace: RailItem[] = [
    { label: "Projects", icon: IconLayoutDashboard, path: "/projects", divideBefore: project.length > 0 },
    { label: "Certificates", icon: IconCertificate, path: "/workspace/certificates" },
    { label: "Git", icon: IconGitBranch, path: "/workspace/git" },
  ];
  return [...project, ...workspace];
}

/** Whether *pathname* is *item*'s page or under it. */
export function isRailItemActive(item: RailItem, pathname: string): boolean {
  if (item.exact) return pathname === item.path;
  return [item.path, ...(item.also ?? [])].some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/**
 * Icon rail — the narrow primary navigation. Inside a project it leads with
 * that project's sections (pipelines, code, runs…), so moving between them
 * never loses which project you are in; workspace-wide pages follow. From a
 * workspace page, the last project opened stays one click away.
 */
export function Sidebar() {
  const location = useLocation();
  const lastProjectId = useUIStore((s) => s.lastProjectId);
  const projectId = projectIdFromPath(location.pathname) ?? lastProjectId;
  const { data: pipelines } = useServerProjectPipelines(projectId ?? "");
  const specs = Object.values((pipelines?.pipelines ?? {}) as Record<string, { type?: string } | undefined>);
  const onModels = Boolean(projectId) && location.pathname.startsWith(routes.section(projectId ?? "", "models"));
  const items = railItems(projectId, { hasModels: onModels || specs.some((p) => p?.type === "ml") });

  return (
    <aside className="ducta-rail" aria-label="Primary navigation">
      <Link to="/projects" className="ducta-rail-logo" title="Ducta" aria-label="Ducta home">
        <IconBox size={24} stroke={1.6} color="var(--primary)" />
      </Link>

      <nav className="ducta-rail-nav">
        {items.map((item) => {
          const isActive = isRailItemActive(item, location.pathname);
          return (
            <React.Fragment key={item.path}>
              {item.divideBefore && <span className="rail-divider" aria-hidden="true" />}
              <Link
                to={item.path}
                className={`rail-item ${isActive ? "active" : ""}`}
                aria-label={item.label}
                aria-current={isActive ? "page" : undefined}
              >
                <item.icon size={20} stroke={1.5} />
                <span className="rail-flyout">{item.label}</span>
              </Link>
            </React.Fragment>
          );
        })}
      </nav>

      {/* The workspace is switched from the header, where its name is. */}
      <div className="ducta-rail-footer">
        <div className="rail-version" title={`Ducta v${__APP_VERSION__}`}>v{__APP_VERSION__}</div>
      </div>
    </aside>
  );
}
