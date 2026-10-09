import { Link } from "react-router-dom";
import { IconFlask, IconPlayerPlay } from "@tabler/icons-react";
import { useGenerateSnapshotTest, useNodeTests, useRunNodeTests } from "../../../api/queries";
import { apiErrorMessage } from "../../../api/mutations/errors";
import { PermittedButton } from "../../ui/PermittedButton";
import { routes } from "../../../utils/routes";

/**
 * The tests that cover the node: run them here, see which failed and on what
 * line — or freeze its current inputs into a snapshot test that pins the
 * columns it produces.
 */
export function NodeTests({ projectId, node, env }: { projectId: string; node: string; env: string }) {
  const { data } = useNodeTests(projectId, node);
  const run = useRunNodeTests(projectId);
  const snapshot = useGenerateSnapshotTest(projectId, node);
  const files = data?.files ?? [];
  const result = run.data;
  const exists = (snapshot.error as any)?.response?.status === 409 && /exists/.test(apiErrorMessage(snapshot.error));

  return (
    <section className="focus-col node-tests" aria-label="Tests of this node">
      <h4 className="focus-col-label">Tests</h4>
      {files.length === 0 ? (
        <p className="focus-empty">No test calls this node's function yet.</p>
      ) : (
        <ul className="node-tests__files">
          {files.map((f) => (
            <li key={f}><Link to={routes.code(projectId, f)} className="mono">{f}</Link></li>
          ))}
        </ul>
      )}
      <div className="node-tests__actions">
        <PermittedButton
          permission="pipeline.execute"
          variant="secondary"
          size="sm"
          leftIcon={<IconPlayerPlay size={13} />}
          disabled={files.length === 0}
          loading={run.isPending}
          onClick={() => run.mutate(node)}
        >
          Run tests
        </PermittedButton>
        <PermittedButton
          permission="pipeline.write"
          variant="ghost"
          size="sm"
          leftIcon={<IconFlask size={13} />}
          loading={snapshot.isPending}
          title={`Freeze 20 rows of each input in ${env} and pin the output's columns`}
          onClick={() => snapshot.mutate({ env, overwrite: exists })}
        >
          {exists ? "Regenerate snapshot test" : "Snapshot test from data"}
        </PermittedButton>
      </div>
      {snapshot.data && (
        <p className="node-tests__note" role="status">
          Wrote <Link to={routes.code(projectId, snapshot.data.test_file)} className="mono">{snapshot.data.test_file}</Link> and{" "}
          {snapshot.data.fixtures.length} fixture{snapshot.data.fixtures.length === 1 ? "" : "s"} — commit them from Changes.
        </p>
      )}
      {snapshot.error && <p className="node-tests__note is-error" role="alert">{apiErrorMessage(snapshot.error)}</p>}
      {run.error && <p className="node-tests__note is-error" role="alert">{apiErrorMessage(run.error)}</p>}
      {result && (
        <div className="node-tests__result" aria-live="polite">
          <p className={`node-tests__summary${result.ok ? " is-ok" : " is-bad"}`}>
            {Object.entries(result.summary).map(([k, v]) => `${v} ${k}`).join(" · ") || result.output}
          </p>
          <ul className="node-tests__list">
            {result.tests
              .filter((t) => t.outcome !== "passed")
              .concat(result.tests.filter((t) => t.outcome === "passed"))
              .map((t, i) => (
                <li key={`${t.name}-${i}`} data-outcome={t.outcome}>
                  <span className="node-tests__dot" aria-label={t.outcome} />
                  <span className="node-tests__name">{t.name}</span>
                  {t.file && (
                    <Link className="mono node-tests__where" to={routes.code(projectId, t.file, t.line ?? undefined)}>
                      {t.file}{t.line ? `:${t.line}` : ""}
                    </Link>
                  )}
                  {t.message && t.outcome !== "passed" && <span className="node-tests__msg">{t.message.slice(0, 240)}</span>}
                </li>
              ))}
          </ul>
        </div>
      )}
    </section>
  );
}
