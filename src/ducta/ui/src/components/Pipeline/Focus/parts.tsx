import type React from "react";
import { IconArrowRight } from "@tabler/icons-react";
import type {
  MlPlanModel,
  MlPlanModelResolution,
  MlPlanNode,
  NodeQualityGate,
  NodeSchema,
} from "../../../api/queries";
import { compactDuration, formatGlyph, humanizeGate } from "../../../utils/nodePresentation";
import { formatDate } from "../../../utils/formatDate";

/**
 * Pieces shared by the focus panel and the contract list, so a node reads the
 * same way in both: the same quality line, the same dataset references, the
 * same "not declared" answer where the registry is silent.
 */

export interface KeyValueRow {
  label: string;
  value: React.ReactNode | null;
  /** Render in the sans stack instead of mono — for prose, not identifiers. */
  plain?: boolean;
  /** Override the "not declared" placeholder for a null value. */
  absent?: string;
}

/**
 * A label/value list. Values are monospaced by default because most of them are
 * identifiers, paths or formats; `plain` opts a prose value out.
 */
export function KeyValues({ rows }: { rows: KeyValueRow[] }) {
  return (
    <dl className="inspector-kv">
      {rows.map((row) => (
        <div className="inspector-kv-row" key={row.label}>
          <dt>{row.label}</dt>
          <dd
            className={[row.plain ? "plain" : "", row.value == null ? "absent" : ""]
              .filter(Boolean)
              .join(" ")}
            title={typeof row.value === "string" ? row.value : undefined}
          >
            {/* "not declared" is the useful answer: it points at the config
                that needs fixing, where a dash or a fake default does not. */}
            {row.value ?? row.absent ?? "not declared"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function Pill({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "bronze" | "silver" | "gold" | "ok" | "warn" | "bad" | "neutral";
}) {
  return <span className={`inspector-pill${tone ? ` tone-${tone}` : ""}`}>{children}</span>;
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** `{min: 350}` → `min 350`; `{columns: ["G3", "G1"], threshold: 0}` → `columns G3, G1 · threshold 0`. */
export function formatParams(params: Record<string, unknown> | undefined | null): string {
  if (!params) return "";
  return Object.entries(params)
    .map(([key, value]) => `${key} ${formatValue(value)}`)
    .join(" · ");
}

/** How a node is guarded, in one line: `1 sanity · 3 quality · gate`. */
export function qualityLine(quality: NodeSchema["quality"] | undefined): string | null {
  if (!quality) return null;
  const parts: string[] = [];
  const checks = quality.checks ?? [];
  if (checks.length > 0) {
    const sanity = checks.filter((c) => c.phase === "sanity").length;
    if (sanity > 0) parts.push(`${sanity} sanity`);
    if (checks.length - sanity > 0) parts.push(`${checks.length - sanity} quality`);
  } else if (quality.check_count > 0) {
    parts.push(`${quality.check_count} ${quality.is_sanity ? "sanity" : "quality"}`);
  }
  if ((quality.gates?.length ?? 0) > 0 || quality.gate_behavior) parts.push("gate");
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function gateLine(gate: NodeQualityGate): string {
  return (
    [gate.behavior ? humanizeGate(gate.behavior) : null, formatParams(gate.params) || null]
      .filter(Boolean)
      .join(" · ") || "enabled"
  );
}

/** `Failed · Sep 15, 08:48 · 10.6 s`, from whichever of the three are known. */
export function lastRunLine(
  status: string | null | undefined,
  time: string | null | undefined,
  seconds: number | null | undefined
): string | null {
  const parts = [
    status ? status.charAt(0).toUpperCase() + status.slice(1) : null,
    time ? formatDate(time) : null,
    compactDuration(seconds),
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** The checks and gates of a node, one per line, parameters spelled out. */
export function ChecksList({ quality }: { quality: NodeSchema["quality"] | undefined }) {
  const checks = quality?.checks ?? [];
  const gates = quality?.gates ?? [];
  if (checks.length === 0 && gates.length === 0) return null;
  return (
    <ul className="focus-checks">
      {checks.map((check) => (
        <li key={`${check.phase}:${check.name}`}>
          <span className="focus-check-name">{check.name}</span>
          <span className="focus-check-params">{formatParams(check.params) || check.phase}</span>
        </li>
      ))}
      {gates.map((gate) => (
        <li key={`gate:${gate.phase}`} className="focus-check--gate">
          <span className="focus-check-name">{gate.phase === "sanity" ? "sanity gate" : "gate"}</span>
          <span className="focus-check-params">{gateLine(gate)}</span>
        </li>
      ))}
    </ul>
  );
}

export interface DatasetRefItem {
  name: string;
  declared?: boolean;
  format?: string | null;
  path?: string | null;
  write_mode?: string | null;
  layer?: string | null;
}

/** A dataset a node reads or writes, as a link into its focus. */
export function DatasetRef({
  item,
  onSelect,
}: {
  item: DatasetRefItem;
  onSelect?: (name: string) => void;
}) {
  const declared = item.declared ?? true;
  const meta = [declared ? item.format : null, item.write_mode, item.path].filter(Boolean) as string[];
  return (
    <button
      type="button"
      className={`inspector-io-row${declared ? "" : " undeclared"}`}
      data-layer={item.layer ?? undefined}
      onClick={() => onSelect?.(item.name)}
      title={declared ? item.path ?? undefined : "No entry in input_config / output_config"}
    >
      <span className="inspector-io-swatch" aria-hidden="true" />
      <span className="inspector-io-glyph" aria-hidden="true">
        {formatGlyph(declared ? item.format : null)}
      </span>
      <span className="inspector-io-text">
        <span className="inspector-io-name">{item.name}</span>
        <span className="inspector-io-meta">{meta.length > 0 ? meta.join(", ") : "not declared"}</span>
      </span>
    </button>
  );
}

/** A neighbouring node. One in a pipeline that is not drawn opens that pipeline instead. */
export function NodeRef({
  name,
  meta,
  elsewhere = false,
  onClick,
}: {
  name: string;
  meta?: string | null;
  elsewhere?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="inspector-io-row focus-node-ref"
      onClick={onClick}
      title={elsewhere ? `In pipeline ${meta} — click to open it` : "Click to focus this node"}
    >
      <span className="inspector-io-text">
        <span className="inspector-io-name">{name}</span>
        {meta && (
          <span className="inspector-io-meta">
            {meta}
            {elsewhere ? ", another pipeline" : ""}
          </span>
        )}
      </span>
      {elsewhere && (
        <IconArrowRight size={13} stroke={1.7} className="inspector-io-go" aria-hidden="true" />
      )}
    </button>
  );
}

/** `stratified · test_size 0.2 · stratify_col churned · seed 42` */
export function splitLine(split: Record<string, unknown> | undefined): string | null {
  if (!split) return null;
  const { method, ...rest } = split;
  return [method, formatParams(Object.fromEntries(Object.entries(rest).filter(([, v]) => v != null)))]
    .filter(Boolean)
    .join(" · ");
}

/** `churn @ production → prediction (predict)` or the MLflow uri. */
export function modelLine(model: MlPlanModel): string {
  const which =
    model.source === "mlflow"
      ? model.uri ?? "mlflow"
      : `${model.name ?? "?"} ${model.version != null ? `v${model.version}` : `@ ${model.stage ?? "?"}`}`;
  return `${which} → ${model.output_col ?? "prediction"} (${model.method ?? "predict"})`;
}

/** Which version a run starting now would score with — or why there is none. */
export function ModelResolution({ resolution }: { resolution?: MlPlanModelResolution }) {
  if (!resolution) return <>—</>;
  switch (resolution.status) {
    case "resolved":
      return (
        <span title={resolution.artifact_sha256 ?? undefined}>
          v{resolution.version}
          {resolution.stage ? ` (${resolution.stage})` : ""} — pinned when a run starts
        </span>
      );
    case "unresolved":
      // The pill stays short; the reason wraps beside it.
      return (
        <span>
          <Pill tone="bad">nothing to serve</Pill> {resolution.message}
        </span>
      );
    case "at_run_time":
      return <>resolved when the run starts (MLflow)</>;
    default:
      return (
        <span>
          <Pill tone="warn">unknown</Pill> {resolution.message ?? "the registry could not be read"}
        </span>
      );
  }
}

/**
 * What an ML node is given — the same answer as `ducta config show --ml`: its stage,
 * the split it receives and where that was declared, whether it must apply it, its
 * merged hyperparameters and its model version.
 */
export function MLPlanBlock({
  plan,
  enforcement,
}: {
  plan: MlPlanNode;
  enforcement?: "error" | "warn" | null;
}) {
  const bound = plan.must_apply_split === true;
  return (
    <section className="focus-ml" aria-label="ML">
      <h4 className="focus-ml-title">ML</h4>
      <KeyValues
        rows={[
          { label: "Stage", value: plan.ml_stage === "none" ? null : plan.ml_stage, absent: "none", plain: true },
          {
            label: "Split",
            value: plan.split ? `${splitLine(plan.split)} (from ${plan.split_from ?? "pipeline"})` : null,
            absent: "none",
          },
          {
            label: "Must apply",
            value: !plan.split ? null : bound ? (
              <Pill tone={enforcement === "warn" ? "warn" : "bad"}>
                yes — {enforcement === "warn" ? "warns if it does not" : "the run fails if it does not"}
              </Pill>
            ) : (
              "no"
            ),
            absent: "—",
            plain: true,
          },
          { label: "Hyperparameters", value: plan.hyperparams ? formatParams(plan.hyperparams) : null, absent: "none" },
          { label: "Model version", value: plan.model_version ?? null, absent: "not set" },
          ...(plan.model
            ? [
                { label: "Serves", value: modelLine(plan.model), absent: "—" },
                {
                  label: "Right now",
                  value: <ModelResolution resolution={plan.model_resolution} />,
                  absent: "—",
                  plain: true,
                },
                { label: "Scorer", value: plan.run ?? "own run function", absent: "—", plain: true },
              ]
            : []),
        ]}
      />
    </section>
  );
}
