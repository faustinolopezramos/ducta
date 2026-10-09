import { Link } from "react-router-dom";
import { IconStethoscope } from "@tabler/icons-react";
import type { Diagnosis } from "../../api/queries/executions";
import { routes } from "../../utils/routes";
import { formatRelative } from "../../utils/timeLabels";
import { QualityGateRows } from "./QualityGateRows";

const KIND_LABEL: Record<string, string> = {
  code: "Code",
  data: "Data",
  quality_gate: "Quality gate",
  config: "Configuration",
  infra: "Infrastructure",
  unknown: "Unknown",
};

/**
 * Why the run failed, said the way it is fixed: what kind of failure, the line
 * in the project's own code, and what changed since the last good run — then
 * what to do about it.
 */
export function DiagnosePanel({
  diagnosis,
  projectId,
  onRetryFromNode,
  onRetry,
  onRunNodeOnly,
  onRetryWithOptions,
  onReproduce,
  pipeline,
  env,
}: {
  diagnosis: Diagnosis;
  projectId: string;
  onRetryFromNode?: (node: string) => void;
  onRetry?: () => void;
  /** Run just the failed node, reading its inputs as they are. */
  onRunNodeOnly?: (node: string) => void;
  /** Open the run dialog: other dates, parameters, a sample, a breakpoint. */
  onRetryWithOptions?: () => void;
  /** Re-run what the certificate recorded, to see whether it fails the same way. */
  onReproduce?: () => void;
  pipeline?: string;
  env?: string;
}) {
  const changed = diagnosis.what_changed;
  return (
    <section className="diagnose" aria-label="Diagnosis" data-kind={diagnosis.kind}>
      <header className="diagnose__head">
        <IconStethoscope size={18} aria-hidden="true" />
        <div>
          <h2 className="diagnose__title">{diagnosis.title}</h2>
          <p className="diagnose__meta">
            <span className="diagnose__kind">{KIND_LABEL[diagnosis.kind] ?? diagnosis.kind}</span>
            {diagnosis.node && <> · node <span className="mono">{diagnosis.node}</span></>}
          </p>
        </div>
      </header>

      {diagnosis.message && <pre className="diagnose__message">{diagnosis.message.split("\n").slice(0, 6).join("\n")}</pre>}

      <dl className="diagnose__facts">
        {diagnosis.frame && (
          <>
            <dt>Where</dt>
            <dd>
              <Link to={routes.code(projectId, diagnosis.frame.file, diagnosis.frame.line)} className="mono">
                {diagnosis.frame.file}:{diagnosis.frame.line}
              </Link>{" "}
              in {diagnosis.frame.function}()
            </dd>
          </>
        )}
        <dt>What changed</dt>
        <dd>
          {!changed ? (
            "No earlier successful run to compare with."
          ) : (
            <>
              <span className="diagnose__since">
                since the last good run ({formatRelative(changed.since) ?? changed.since_run_id}
                {changed.since_commit ? `, ${changed.since_commit.slice(0, 8)}` : ""}):
              </span>
              <ul className="diagnose__changes">
                <li data-changed={changed.code.length > 0}>
                  Code: {changed.code.length ? changed.code.join(", ") : "unchanged"}
                </li>
                <li data-changed={changed.data.length > 0}>
                  Input data: {changed.data.length ? changed.data.join(", ") : "unchanged"}
                </li>
                <li data-changed={changed.config}>Configuration: {changed.config ? "changed" : "unchanged"}</li>
              </ul>
            </>
          )}
        </dd>
      </dl>

      {diagnosis.kind === "quality_gate" && diagnosis.node && pipeline && env && (
        <QualityGateRows projectId={projectId} pipeline={pipeline} node={diagnosis.node} env={env} />
      )}

      {diagnosis.suggestions.length > 0 && (
        <ul className="diagnose__suggestions">
          {diagnosis.suggestions.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}

      <div className="diagnose__actions">
        {diagnosis.node && onRetryFromNode && (
          <button type="button" className="diagnose__btn is-primary" onClick={() => onRetryFromNode(diagnosis.node!)}>
            Retry from {diagnosis.node}
          </button>
        )}
        {diagnosis.node && onRunNodeOnly && (
          <button type="button" className="diagnose__btn" onClick={() => onRunNodeOnly(diagnosis.node!)}>
            Run only {diagnosis.node}
          </button>
        )}
        {onRetry && (
          <button type="button" className="diagnose__btn" onClick={onRetry}>
            Retry the whole run
          </button>
        )}
        {onRetryWithOptions && (
          <button type="button" className="diagnose__btn" onClick={onRetryWithOptions}>
            Retry with other options…
          </button>
        )}
        {onReproduce && (
          <button type="button" className="diagnose__btn" onClick={onReproduce} title="Run it again as recorded, to see if it fails the same way">
            Reproduce
          </button>
        )}
        {diagnosis.frame && (
          <Link className="diagnose__btn" to={routes.code(projectId, diagnosis.frame.file, diagnosis.frame.line)}>
            Open the code
          </Link>
        )}
      </div>
    </section>
  );
}
