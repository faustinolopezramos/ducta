import React, { useMemo, useState } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { StatusBadge } from "../ui/StatusBadge";
import { colors } from "../../theme/tokens";
import { toastStore } from "../../hooks/useModalStack";
import {
  useQualityChecks,
  useRunQualityChecks,
  type RunChecksVars,
} from "../../api/qualityApi";
import { FilePickerField } from "./FilePickerField";
import { CheckResultsList, RawJson, type QualityReportData } from "./report";
import { IconPlayerPlay, IconPlus, IconTrash } from "@tabler/icons-react";

const label: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  color: colors.textMuted,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  marginBottom: 4,
};

const input: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  borderRadius: 6,
  border: `1px solid ${colors.border}`,
  background: colors.bg,
  color: colors.text,
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  outline: "none",
};

// Suggested params shown as placeholder hints for the most common checks.
const PARAM_HINTS: Record<string, string> = {
  null_rate: "threshold, columns",
  row_count: "min_rows, max_rows",
  range: "column, min, max",
  freshness: "column, max_age_hours",
  duplicates: "columns",
  schema: "expected_columns",
  statistical: "column, min_mean, max_mean",
  business_rules: "expression",
};

interface BuilderCheck {
  id: number;
  name: string;
  severity: "error" | "warning";
  params: { key: string; value: string }[];
}

/** Coerce a raw text param value into bool/number/JSON when it looks like one. */
function coerceValue(raw: string): unknown {
  const v = raw.trim();
  if (v === "true") return true;
  if (v === "false") return false;
  if (v !== "" && !Number.isNaN(Number(v))) return Number(v);
  if ((v.startsWith("[") && v.endsWith("]")) || (v.startsWith("{") && v.endsWith("}"))) {
    try {
      return JSON.parse(v);
    } catch {
      /* keep as string */
    }
  }
  return v;
}

function formatFromPath(path: string): RunChecksVars["format"] | null {
  const lower = path.toLowerCase();
  if (lower.endsWith(".parquet")) return "parquet";
  if (lower.endsWith(".csv")) return "csv";
  if (lower.endsWith(".json")) return "json";
  return null;
}

type ChecksSource = "builder" | "config" | "json";

/**
 * Guided "Run checks" flow: pick a real workspace file, assemble checks from
 * the registered-check catalog (no raw JSON required), run, and see results
 * inline. Config-file and advanced-JSON modes remain available.
 */
export function RunChecksModal({
  onClose,
  onCompleted,
}: {
  onClose: () => void;
  /** Called with the dataset name after a successful run (for drill-down). */
  onCompleted: (dataset: string | null) => void;
}) {
  const [inputPath, setInputPath] = useState("");
  const [format, setFormat] = useState<NonNullable<RunChecksVars["format"]>>("parquet");
  const [failFast, setFailFast] = useState(false);
  const [source, setSource] = useState<ChecksSource>("builder");
  const [builderChecks, setBuilderChecks] = useState<BuilderCheck[]>([]);
  const [configPath, setConfigPath] = useState("");
  const [checksJson, setChecksJson] = useState("");
  const [result, setResult] = useState<QualityReportData | null>(null);
  const nextId = React.useRef(1);

  const { data: catalog } = useQualityChecks();
  const run = useRunQualityChecks();

  const usedNames = new Set(builderChecks.map((c) => c.name));
  const availableNames = (catalog ?? []).filter((c) => !usedNames.has(c.name));

  const handleInputPath = (path: string) => {
    setInputPath(path);
    const fmt = formatFromPath(path);
    if (fmt) setFormat(fmt);
  };

  const addCheck = () => {
    const first = availableNames[0]?.name;
    if (!first) return;
    setBuilderChecks((cs) => [
      ...cs,
      { id: nextId.current++, name: first, severity: "error", params: [] },
    ]);
  };

  const updateCheck = (id: number, patch: Partial<BuilderCheck>) =>
    setBuilderChecks((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  const builtChecks = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const c of builderChecks) {
      const cfg: Record<string, unknown> = { enabled: true, severity: c.severity };
      for (const p of c.params) {
        if (p.key.trim()) cfg[p.key.trim()] = coerceValue(p.value);
      }
      out[c.name] = cfg;
    }
    return out;
  }, [builderChecks]);

  const submit = () => {
    const vars: RunChecksVars = { input_path: inputPath, format, fail_fast: failFast };
    if (source === "builder") {
      if (builderChecks.length === 0) {
        toastStore.getState().show("Add at least one check", "error");
        return;
      }
      vars.checks = builtChecks;
    } else if (source === "config") {
      if (!configPath.trim()) {
        toastStore.getState().show("Pick a checks config file", "error");
        return;
      }
      vars.config_path = configPath.trim();
    } else {
      try {
        vars.checks = JSON.parse(checksJson);
      } catch (e) {
        toastStore.getState().show(`Invalid checks JSON: ${(e as Error).message}`, "error");
        return;
      }
    }
    run.mutate(vars, {
      onSuccess: (data) => {
        setResult(data as QualityReportData);
      },
    });
  };

  const sourceTab = (key: ChecksSource, text: string) => (
    <button
      type="button"
      onClick={() => setSource(key)}
      style={{
        padding: "4px 10px",
        borderRadius: 5,
        border: `1px solid ${source === key ? colors.accent : colors.border}`,
        background: source === key ? `${colors.accent}12` : "transparent",
        color: source === key ? colors.accent : colors.textMuted,
        cursor: "pointer",
        fontSize: 11,
        fontWeight: source === key ? 600 : 400,
      }}
    >
      {text}
    </button>
  );

  return (
    <Modal title="Run quality checks" onClose={onClose} width={640}>
      <div style={{ display: "grid", gap: 14 }}>
        <div>
          <span style={label}>Data file</span>
          <FilePickerField
            value={inputPath}
            onChange={handleInputPath}
            placeholder="data/bronze/sales.parquet"
            extensions={[".parquet", ".csv", ".json"]}
          />
        </div>

        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <div style={{ width: 140 }}>
            <span style={label}>Format</span>
            <select
              style={input}
              value={format}
              onChange={(e) => setFormat(e.target.value as NonNullable<RunChecksVars["format"]>)}
            >
              <option value="parquet">parquet</option>
              <option value="csv">csv</option>
              <option value="json">json</option>
            </select>
          </div>
          <label
            style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: colors.text, paddingBottom: 7 }}
          >
            <input type="checkbox" checked={failFast} onChange={(e) => setFailFast(e.target.checked)} />
            Fail fast (stop on first failing check)
          </label>
        </div>

        <div>
          <span style={label}>Checks</span>
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            {sourceTab("builder", "Builder")}
            {sourceTab("config", "Config file")}
            {sourceTab("json", "Advanced JSON")}
          </div>

          {source === "builder" && (
            <div style={{ display: "grid", gap: 8 }}>
              {builderChecks.length === 0 && (
                <p style={{ margin: 0, fontSize: 12, color: colors.textMuted }}>
                  Pick checks from the registered catalog — parameters are optional for most checks.
                </p>
              )}
              {builderChecks.map((c) => (
                <div
                  key={c.id}
                  style={{
                    border: `1px solid ${colors.border}`,
                    borderRadius: 6,
                    padding: "8px 10px",
                    background: colors.bg,
                    display: "grid",
                    gap: 6,
                  }}
                >
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <select
                      style={{ ...input, flex: 1 }}
                      value={c.name}
                      onChange={(e) => updateCheck(c.id, { name: e.target.value, params: [] })}
                    >
                      <option value={c.name}>{c.name}</option>
                      {availableNames.map((opt) => (
                        <option key={opt.name} value={opt.name}>
                          {opt.name}
                        </option>
                      ))}
                    </select>
                    <select
                      style={{ ...input, width: 110 }}
                      value={c.severity}
                      onChange={(e) =>
                        updateCheck(c.id, { severity: e.target.value as "error" | "warning" })
                      }
                    >
                      <option value="error">error</option>
                      <option value="warning">warning</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => setBuilderChecks((cs) => cs.filter((x) => x.id !== c.id))}
                      title="Remove check"
                      style={{ background: "none", border: "none", cursor: "pointer", color: colors.textMuted, padding: 4 }}
                    >
                      <IconTrash size={14} />
                    </button>
                  </div>

                  {c.params.map((p, i) => (
                    <div key={i} style={{ display: "flex", gap: 6 }}>
                      <input
                        style={{ ...input, width: 160 }}
                        value={p.key}
                        onChange={(e) =>
                          updateCheck(c.id, {
                            params: c.params.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)),
                          })
                        }
                        placeholder={PARAM_HINTS[c.name] ? `e.g. ${PARAM_HINTS[c.name].split(",")[0].trim()}` : "param"}
                      />
                      <input
                        style={{ ...input, flex: 1 }}
                        value={p.value}
                        onChange={(e) =>
                          updateCheck(c.id, {
                            params: c.params.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)),
                          })
                        }
                        placeholder="value (numbers/booleans/[lists] auto-detected)"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          updateCheck(c.id, { params: c.params.filter((_, j) => j !== i) })
                        }
                        title="Remove parameter"
                        style={{ background: "none", border: "none", cursor: "pointer", color: colors.textMuted, padding: 4 }}
                      >
                        <IconTrash size={13} />
                      </button>
                    </div>
                  ))}

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <button
                      type="button"
                      onClick={() => updateCheck(c.id, { params: [...c.params, { key: "", value: "" }] })}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        fontSize: 11,
                        color: colors.accent,
                        padding: 0,
                      }}
                    >
                      <IconPlus size={12} /> Add parameter
                    </button>
                    {PARAM_HINTS[c.name] && (
                      <span style={{ fontSize: 10, color: colors.textDim }}>
                        common: {PARAM_HINTS[c.name]}
                      </span>
                    )}
                  </div>
                </div>
              ))}
              <div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={addCheck}
                  disabled={availableNames.length === 0}
                  leftIcon={<IconPlus size={14} />}
                >
                  Add check
                </Button>
              </div>
            </div>
          )}

          {source === "config" && (
            <FilePickerField
              value={configPath}
              onChange={setConfigPath}
              placeholder="config/quality.toml"
              extensions={[".toml", ".yaml", ".yml", ".json"]}
            />
          )}

          {source === "json" && (
            <textarea
              style={{ ...input, minHeight: 100, resize: "vertical" }}
              value={checksJson}
              onChange={(e) => setChecksJson(e.target.value)}
              placeholder='{ "row_count": { "min_rows": 1 }, "null_rate": { "threshold": 0.05 } }'
            />
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            disabled={run.isPending || !inputPath}
            leftIcon={<IconPlayerPlay size={15} />}
          >
            {run.isPending ? "Running…" : "Run checks"}
          </Button>
        </div>

        {result && (
          <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <StatusBadge status={result.passed ? "success" : "failed"} />
              {typeof result.score === "number" && (
                <span style={{ fontSize: 12, color: colors.textMuted }}>
                  score {result.score.toFixed(3)}
                </span>
              )}
              <div style={{ flex: 1 }} />
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onCompleted(result.dataset_name ?? null)}
              >
                View in reports
              </Button>
            </div>
            {result.results && result.results.length > 0 ? (
              <CheckResultsList results={result.results} />
            ) : (
              <p style={{ fontSize: 12, color: colors.textMuted }}>
                No per-check details in this report.
              </p>
            )}
            <RawJson data={result} />
          </div>
        )}
      </div>
    </Modal>
  );
}
