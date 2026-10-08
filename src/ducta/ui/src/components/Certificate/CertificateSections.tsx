import { useState } from "react";
import { IconBox, IconChecklist, IconChevronDown, IconChevronRight, IconCode, IconDatabase, IconServer, IconAlertTriangle } from "@tabler/icons-react";
import { Panel } from "../ui/Panel";
import { DataTable, type DataTableColumn } from "../ui/DataTable";
import { StatusBadge } from "../ui/StatusBadge";
import { EmptyState } from "../ui/EmptyState";
import { CopyButton } from "./CopyButton";
import type {
  CertificateCodeNodeHash,
  CertificateDatasetFingerprint,
  CertificateEnvironment,
  CertificateNode,
  CertificateNodeML,
  CertificateQualityEntry,
  RunCertificate,
} from "../../api/certificatesApi";
import "./Certificate.css";

function truncatedHash(value: string | null | undefined, len = 16): string {
  if (!value) return "—";
  const raw = value.includes(":") ? value.split(":", 2)[1] : value;
  return raw.length > len ? `${raw.slice(0, len)}…` : raw;
}

function HashCell({ value }: { value: string | null | undefined }) {
  if (!value) return <span>—</span>;
  return (
    <span className="cert-hash">
      {truncatedHash(value)}
      <CopyButton label="hash" value={value} />
    </span>
  );
}

const STRONG_MODES = new Set(["exact", "exact_crypto"]);
const MODE_MEANING: Record<string, string> = {
  exact: "Full order-independent digest.",
  exact_crypto: "SHA-256 per row — the strongest mode.",
  sample: "Head-only — misses most of it on large tables.",
  schema: "Schema only — misses every row.",
};

function ModeChip({ mode }: { mode?: string }) {
  if (!mode) return <span>—</span>;
  const strong = STRONG_MODES.has(mode);
  return (
    <span className={`cert-mode-chip ${strong ? "cert-mode-chip--strong" : "cert-mode-chip--weak"}`} title={MODE_MEANING[mode] ?? mode}>
      {mode}
    </span>
  );
}

// ── Nodes ────────────────────────────────────────────────────────────────────

export function NodesSection({ nodes }: { nodes: CertificateNode[] }) {
  const columns: DataTableColumn<CertificateNode>[] = [
    { key: "name", header: "Name", mono: true, sortable: true },
    { key: "type", header: "Type", sortable: true },
    { key: "status", header: "Status", cell: (n) => <StatusBadge status={n.status} size="sm" />, sortable: true },
    {
      key: "duration_seconds",
      header: "Duration",
      align: "right",
      mono: true,
      sortable: true,
      cell: (n) => (n.duration_seconds != null ? `${n.duration_seconds.toFixed(2)}s` : "—"),
    },
    { key: "outputs", header: "Outputs", cell: (n) => (n.outputs ?? []).join(", ") || "—" },
  ];
  return (
    <Panel title="Nodes">
      <DataTable
        columns={columns}
        rows={nodes}
        rowKey={(n) => n.name}
        density="compact"
        empty={<EmptyState icon={IconBox} size="sm" title="No nodes recorded" description="This certificate has no node-level detail." />}
      />
    </Panel>
  );
}

// ── ML ───────────────────────────────────────────────────────────────────────

const SPLIT_ORDER = ["method", "test_size", "val_size", "stratify_col", "time_col", "group_col", "seed"];

/** `stratified, test_size=0.2, stratify_col=churned, seed=42` */
export function describeSplit(split: Record<string, unknown> | null | undefined): string {
  if (!split) return "—";
  const keys = [...SPLIT_ORDER.filter((k) => k in split), ...Object.keys(split).filter((k) => !SPLIT_ORDER.includes(k))];
  return keys
    .filter((k) => split[k] != null)
    .map((k) => (k === "method" ? String(split[k]) : `${k}=${String(split[k])}`))
    .join(", ");
}

/** The one question a reviewer asks of an ML run: was the declared split used? */
export function SplitVerdict({ ml }: { ml: CertificateNodeML }) {
  if (!ml.split) return <span>—</span>;
  if (ml.split_applied) {
    return (
      <span className="cert-mode-chip cert-mode-chip--strong" title="The node called split_dataframe with its ml_context.">
        applied
      </span>
    );
  }
  if (ml.split_required) {
    return (
      <span
        className="cert-mode-chip cert-mode-chip--failed"
        title="The node was bound to this split and did not apply it: its model was fitted on a partition nobody declared."
      >
        not applied
      </span>
    );
  }
  return (
    <span className="cert-mode-chip" title="This node received the split but is not bound to apply it (e.g. feature engineering).">
      not required
    </span>
  );
}

interface MLRow extends CertificateNodeML {
  name: string;
}

/**
 * What each ML node was given and did. Shown only when the certificate has ML
 * evidence; certificates written before Ducta recorded it simply omit the panel.
 */
export function MLSection({ nodes }: { nodes: CertificateNode[] }) {
  const rows: MLRow[] = nodes.filter((n) => n.ml).map((n) => ({ name: n.name, ...(n.ml as CertificateNodeML) }));
  if (rows.length === 0) return null;
  const missed = rows.filter((r) => r.split && r.split_required && !r.split_applied);
  const columns: DataTableColumn<MLRow>[] = [
    { key: "name", header: "Node", mono: true, sortable: true },
    { key: "stage", header: "Stage", cell: (r) => r.stage ?? "—" },
    { key: "split", header: "Split", mono: true, cell: (r) => describeSplit(r.split) },
    { key: "split_source", header: "Declared on", cell: (r) => r.split_source ?? "—" },
    { key: "split_applied", header: "Split", cell: (r) => <SplitVerdict ml={r} /> },
    { key: "model_version", header: "Model version", mono: true, cell: (r) => r.model_version ?? "—" },
    ...(rows.some((r) => r.model)
      ? [
          {
            key: "model",
            header: "Served model",
            mono: true,
            cell: (r: MLRow) =>
              r.model ? (
                <span title={`${r.model.uri}\n${r.model.artifact_sha256 ?? ""}`}>
                  {r.model.name} v{r.model.version}
                  {r.model.stage_at_resolution ? ` (${r.model.stage_at_resolution})` : ""}
                </span>
              ) : (
                "—"
              ),
          } as DataTableColumn<MLRow>,
        ]
      : []),
    {
      key: "hyperparams",
      header: "Hyperparameters",
      mono: true,
      cell: (r) => {
        const entries = Object.entries(r.hyperparams ?? {});
        if (entries.length === 0) return "—";
        const text = entries.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
        return <span title={text}>{text.length > 60 ? `${text.slice(0, 57)}…` : text}</span>;
      },
    },
  ];
  return (
    <Panel title="ML">
      {missed.length > 0 && (
        <p className="cert-section-warning" role="alert">
          <IconAlertTriangle size={14} /> {missed.map((r) => r.name).join(", ")}{" "}
          {missed.length === 1 ? "was" : "were"} given a train/test split and did not apply it.
        </p>
      )}
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.name} density="compact" />
    </Panel>
  );
}

// ── Datasets ─────────────────────────────────────────────────────────────────

interface DatasetRow {
  key: string;
  direction: "input" | "output";
  fp: CertificateDatasetFingerprint;
}

export function DatasetsSection({
  inputs,
  outputs,
}: {
  inputs: Record<string, CertificateDatasetFingerprint>;
  outputs: Record<string, CertificateDatasetFingerprint>;
}) {
  const rows: DatasetRow[] = [
    ...Object.entries(inputs ?? {}).map(([key, fp]) => ({ key, direction: "input" as const, fp })),
    ...Object.entries(outputs ?? {}).map(([key, fp]) => ({ key, direction: "output" as const, fp })),
  ];

  const columns: DataTableColumn<DatasetRow>[] = [
    {
      key: "direction",
      header: "Direction",
      sortable: true,
      cell: (r) => (
        <span style={{ color: r.direction === "output" ? "var(--primary)" : "var(--text-dim)" }}>{r.direction}</span>
      ),
    },
    { key: "key", header: "Key", mono: true, sortable: true },
    { key: "mode", header: "Mode", cell: (r) => <ModeChip mode={r.fp.mode} /> },
    {
      key: "row_count",
      header: "Rows",
      align: "right",
      mono: true,
      sortable: true,
      sortValue: (r) => r.fp.row_count ?? null,
      cell: (r) => r.fp.row_count ?? "—",
    },
    { key: "schema_hash", header: "Schema hash", cell: (r) => <HashCell value={r.fp.schema_hash} /> },
    {
      key: "content_hash",
      header: "Content hash",
      cell: (r) => (r.fp.content_hash ? <HashCell value={r.fp.content_hash} /> : "—"),
    },
    {
      key: "engine",
      header: "Engine",
      cell: (r) => (
        <span style={{ color: "var(--text-muted)" }}>
          {r.fp.engine ?? "—"}
          {r.fp.degraded_reason && (
            <IconAlertTriangle size={12} className="cert-section-warning" title={r.fp.degraded_reason} />
          )}
        </span>
      ),
    },
  ];

  return (
    <Panel title="Datasets">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => `${r.direction}:${r.key}`}
        density="compact"
        empty={<EmptyState icon={IconDatabase} size="sm" title="No datasets recorded" />}
      />
    </Panel>
  );
}

// ── Quality ──────────────────────────────────────────────────────────────────

export function QualitySection({ quality }: { quality: CertificateQualityEntry[] }) {
  const totalWarnings = quality.reduce((sum, q) => sum + (q.warnings ?? 0), 0);
  const [expanded, setExpanded] = useState<string | null>(null);

  const columns: DataTableColumn<CertificateQualityEntry>[] = [
    { key: "node", header: "Node", mono: true, sortable: true },
    { key: "phase", header: "Phase", sortable: true },
    {
      key: "result",
      header: "Result",
      cell: (q) =>
        q.aborted ? (
          <StatusBadge status="cancelled" label="Aborted" size="sm" />
        ) : (
          <StatusBadge status={q.passed ? "success" : "failed"} size="sm" />
        ),
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      mono: true,
      sortable: true,
      cell: (q) => (q.score != null ? q.score.toFixed(2) : "—"),
    },
    { key: "errors", header: "Errors", align: "right", mono: true, sortable: true },
    { key: "warnings", header: "Warnings", align: "right", mono: true, sortable: true },
  ];

  const rowKey = (q: CertificateQualityEntry) => `${q.node}:${q.phase}`;

  return (
    <Panel title="Quality checks" actions={totalWarnings > 0 ? <span style={{ color: "var(--status-warning-fg)", fontSize: "var(--text-xs)" }}>{totalWarnings} warnings</span> : undefined}>
      <DataTable
        columns={columns}
        rows={quality}
        rowKey={rowKey}
        density="compact"
        onRowClick={(q) => q.aborted && setExpanded((cur) => (cur === rowKey(q) ? null : rowKey(q)))}
        expandedRowKey={expanded}
        renderRowDetail={(q) =>
          q.aborted ? (
            <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }}>
              <div><strong>Gate:</strong> {q.gate ?? "—"}</div>
              <div><strong>Reason:</strong> {q.reason ?? "—"}</div>
              {q.triggered_rules && q.triggered_rules.length > 0 && (
                <div><strong>Triggered rules:</strong> {q.triggered_rules.join(", ")}</div>
              )}
            </div>
          ) : null
        }
        empty={<EmptyState icon={IconChecklist} size="sm" title="No quality checks recorded" />}
      />
    </Panel>
  );
}

// ── Code ─────────────────────────────────────────────────────────────────────

interface CodeRow extends CertificateCodeNodeHash {
  node: string;
}

export function CodeSection({ code }: { code?: RunCertificate["code"] }) {
  const rows: CodeRow[] = Object.entries(code?.nodes ?? {}).map(([node, hash]) => ({ node, ...hash }));

  const columns: DataTableColumn<CodeRow>[] = [
    { key: "node", header: "Node", mono: true, sortable: true },
    {
      key: "scope",
      header: "Scope",
      cell: (r) => (r.scope === "none" ? <span style={{ color: "var(--text-dim)", fontStyle: "italic" }}>not captured</span> : r.scope),
    },
    { key: "source_hash", header: "Source hash", cell: (r) => <HashCell value={r.source_hash} /> },
    { key: "module_hash", header: "Module hash", cell: (r) => <HashCell value={r.module_hash} /> },
    {
      key: "module_file",
      header: "Module file",
      cell: (r) => (
        <span title={r.module_file ?? undefined} style={{ color: "var(--text-muted)" }}>
          {r.module_file ? r.module_file.split("/").slice(-1)[0] : "—"}
        </span>
      ),
    },
  ];

  return (
    <Panel title="Code hashes" description="The transformation logic each node actually ran, independent of config.">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.node}
        density="compact"
        empty={
          <EmptyState
            icon={IconCode}
            size="sm"
            title="No code hashes recorded"
            description="This certificate predates schema 1.4, or code hashing was unavailable for this run."
          />
        }
      />
      {code?.quality_extensions && Object.keys(code.quality_extensions).length > 0 && (
        <div style={{ marginTop: "var(--space-4)" }}>
          <DataTable
            columns={[
              { key: "path", header: "Quality extension" },
              { key: "hash", header: "Hash", cell: (r: { path: string; hash: string }) => <HashCell value={r.hash} /> },
            ]}
            rows={Object.entries(code.quality_extensions).map(([path, hash]) => ({ path, hash }))}
            rowKey={(r) => r.path}
            density="compact"
          />
        </div>
      )}
    </Panel>
  );
}

// ── Environment (collapsed by default) ──────────────────────────────────────

export function EnvironmentSection({ environment }: { environment?: CertificateEnvironment }) {
  const [open, setOpen] = useState(false);
  const [packagesOpen, setPackagesOpen] = useState(false);
  if (!environment) return null;

  const packages = Object.entries(environment.pip_packages ?? {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="cert-disclosure">
      <button type="button" className="cert-disclosure__trigger" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <IconServer size={16} stroke={1.75} />
        Environment
        {open ? <IconChevronDown size={14} className="cert-disclosure__chevron" /> : <IconChevronRight size={14} className="cert-disclosure__chevron" />}
      </button>
      {open && (
        <div className="cert-disclosure__body">
          <div className="cert-kv-grid">
            <div className="cert-kv-grid__field">
              <span className="cert-kv-grid__label">Python</span>
              <span className="cert-kv-grid__value">{environment.python_version ?? "—"}</span>
            </div>
            <div className="cert-kv-grid__field">
              <span className="cert-kv-grid__label">OS</span>
              <span className="cert-kv-grid__value">{environment.os_info ?? "—"}</span>
            </div>
            <div className="cert-kv-grid__field">
              <span className="cert-kv-grid__label">Hostname</span>
              <span className="cert-kv-grid__value">{environment.hostname ?? "—"}</span>
            </div>
            <div className="cert-kv-grid__field">
              <span className="cert-kv-grid__label">Ducta version</span>
              <span className="cert-kv-grid__value">{environment.ducta_version ?? "—"}</span>
            </div>
            <div className="cert-kv-grid__field">
              <span className="cert-kv-grid__label">Git commit</span>
              <span className="cert-kv-grid__value">
                {environment.git_commit ? <HashCell value={environment.git_commit} /> : "—"}
                {environment.git_dirty && <span className="cert-dirty-chip">dirty</span>}
              </span>
            </div>
            <div className="cert-kv-grid__field">
              <span className="cert-kv-grid__label">Git branch</span>
              <span className="cert-kv-grid__value">{environment.git_branch ?? "—"}</span>
            </div>
            <div className="cert-kv-grid__field">
              <span className="cert-kv-grid__label">Environment hash</span>
              <span className="cert-kv-grid__value">{environment.env_hash ? <HashCell value={environment.env_hash} /> : "—"}</span>
            </div>
          </div>

          {packages.length > 0 && (
            <div style={{ marginTop: "var(--space-4)" }}>
              <button
                type="button"
                className="cert-raw-json__trigger"
                onClick={() => setPackagesOpen((v) => !v)}
                style={{ background: "none", border: "none", padding: 0 }}
              >
                {packagesOpen ? "Hide" : "Show"} installed packages ({packages.length})
              </button>
              {packagesOpen && (
                <div style={{ marginTop: "var(--space-2)" }}>
                  <DataTable
                    columns={[
                      { key: "name", header: "Package", mono: true, sortable: true },
                      { key: "version", header: "Version", mono: true, sortable: true },
                    ]}
                    rows={packages.map(([name, version]) => ({ name, version }))}
                    rowKey={(r) => r.name}
                    density="compact"
                    stickyHeader
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Raw JSON ─────────────────────────────────────────────────────────────────

export function RawCertificateJson({ certificate }: { certificate: unknown }) {
  return (
    <details className="cert-raw-json">
      <summary className="cert-raw-json__trigger">Full certificate JSON</summary>
      <pre>{JSON.stringify(certificate, null, 2)}</pre>
    </details>
  );
}
