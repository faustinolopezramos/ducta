import { colors } from "../../theme/tokens";

/** A quiet "how has this pipeline been doing lately" signal, shown only when
 *  a single pipeline is filtered — one tick per terminal run, oldest to
 *  newest, colored the same way status already is everywhere else. It's
 *  explicitly scoped to "last N loaded runs", not all-time health: there's
 *  no aggregation endpoint for the latter, and overclaiming would be worse
 *  than not showing it. */
export function PipelineHealthStrip({
  pipelineName,
  executions,
}: Readonly<{ pipelineName: string; executions: { status: string }[] }>) {
  const terminal = executions.filter((e) => e.status === "success" || e.status === "failed");
  if (terminal.length === 0) return null;

  const successCount = terminal.filter((e) => e.status === "success").length;
  const ticks = [...terminal].reverse(); // executions arrive newest-first; show oldest→newest

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "0 0 10px",
        fontSize: "var(--text-2xs)",
        fontFamily: "var(--font-mono)",
        color: colors.textDim,
      }}
    >
      <span>
        {pipelineName}: {successCount}/{terminal.length} succeeded (last {terminal.length} runs)
      </span>
      <div style={{ display: "flex", gap: 2 }} aria-hidden="true">
        {ticks.map((e, i) => (
          <span
            key={i}
            title={e.status}
            style={{
              width: 6,
              height: 12,
              borderRadius: 1,
              background: e.status === "success" ? colors.success : colors.danger,
              opacity: e.status === "success" ? 0.7 : 1,
            }}
          />
        ))}
      </div>
    </div>
  );
}
