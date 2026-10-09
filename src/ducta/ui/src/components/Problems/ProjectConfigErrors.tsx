import { useNavigate } from "react-router-dom";
import { IconAlertTriangle } from "@tabler/icons-react";
import type { Problem } from "../../api/queries/problems";
import { routes } from "../../utils/routes";
import { ProblemsPanel } from "./ProblemsPanel";

/**
 * A project whose configuration does not load: why, and a way to each line to
 * fix. Shown in place of the page that needed it to load.
 */
export function ProjectConfigErrors({
  projectId,
  problems,
  isChecking,
  onFix,
}: {
  projectId: string;
  problems: Problem[];
  isChecking?: boolean;
  onFix?: (p: Problem) => void;
}) {
  const navigate = useNavigate();
  return (
    <div className="pipeline-broken">
      <div className="pipeline-broken__head">
        <IconAlertTriangle size={20} aria-hidden="true" />
        <div>
          <h1>The project&apos;s configuration has errors</h1>
          <p>Nothing can run until it loads. Open each problem to fix it — the list updates as you save.</p>
        </div>
      </div>
      <ProblemsPanel
        problems={problems}
        isChecking={isChecking}
        onOpen={(p) => p.file && navigate(routes.code(projectId, p.file, p.line ?? undefined))}
        onFix={onFix}
      />
    </div>
  );
}
