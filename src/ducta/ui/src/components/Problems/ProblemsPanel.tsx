import { IconAlertTriangle, IconCircleCheck, IconCircleX, IconInfoCircle, IconWand } from "@tabler/icons-react";
import type { Problem } from "../../api/queries/problems";
import "./Problems.css";

const ICON = { error: IconCircleX, warning: IconAlertTriangle, info: IconInfoCircle } as const;

/**
 * One problem: what is wrong, where (file:line, node), and — when the server
 * knows one — a fix you can apply. Clicking it goes to where it is.
 */
export function ProblemItem({
  problem,
  onOpen,
  onFix,
}: {
  problem: Problem;
  onOpen?: (p: Problem) => void;
  onFix?: (p: Problem) => void;
}) {
  const Icon = ICON[problem.severity] ?? IconInfoCircle;
  const where = [problem.file && `${problem.file}${problem.line ? `:${problem.line}` : ""}`, problem.node]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className={`problem problem--${problem.severity}`}>
      <button type="button" className="problem__main" onClick={() => onOpen?.(problem)} disabled={!onOpen}>
        <Icon size={14} className="problem__icon" aria-label={problem.severity} />
        <span className="problem__message">{problem.message}</span>
        {where && <span className="problem__where">{where}</span>}
        <span className="problem__source">{problem.source}</span>
      </button>
      {problem.fix && onFix && (
        <button type="button" className="problem__fix" onClick={() => onFix(problem)} title={problem.fix.label}>
          <IconWand size={13} aria-hidden="true" /> {problem.fix.label}
        </button>
      )}
    </li>
  );
}

/** The project's problems, errors first. Empty is good news, said plainly. */
export function ProblemsPanel({
  problems,
  isChecking,
  onOpen,
  onFix,
}: {
  problems: Problem[];
  isChecking?: boolean;
  onOpen?: (p: Problem) => void;
  onFix?: (p: Problem) => void;
}) {
  if (problems.length === 0) {
    return (
      <div className="problems problems--empty" role="status">
        <IconCircleCheck size={16} aria-hidden="true" />
        {isChecking ? "Checking…" : "No problems — the project validates in every environment."}
      </div>
    );
  }
  return (
    <ul className="problems" aria-label="Problems">
      {problems.map((p, i) => (
        <ProblemItem key={`${p.file}:${p.line}:${p.message}:${i}`} problem={p} onOpen={onOpen} onFix={onFix} />
      ))}
    </ul>
  );
}
