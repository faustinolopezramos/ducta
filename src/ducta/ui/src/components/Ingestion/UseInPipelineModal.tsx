import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { colors } from "../../theme/tokens";
import { toastStore } from "../../hooks/useModalStack";
import { useServerProjects, useServerProjectPipelines } from "../../api/queries";
import { useUpdateNode, useUpdatePipeline, apiErrorMessage } from "../../api/mutations";
import { IconPlus } from "@tabler/icons-react";
import { routes } from "../../utils/routes";

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

const NODE_NAME_RE = /^[A-Za-z_][A-Za-z0-9_-]*$/;

/**
 * Create a declarative `type: ingestion` node from a saved connection and
 * attach it to a pipeline — no Python required. This is the UI counterpart of
 * the core's declarative ingestion nodes (source + table/query).
 */
export function UseInPipelineModal({
  connectionName,
  onClose,
}: {
  connectionName: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [projectId, setProjectId] = useState("");
  const [pipelineName, setPipelineName] = useState("");
  const [nodeName, setNodeName] = useState(`ingest_${connectionName}`.replace(/[^A-Za-z0-9_-]/g, "_"));
  const [mode, setMode] = useState<"table" | "query">("table");
  const [table, setTable] = useState("");
  const [where, setWhere] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);

  const { data: projectsData, isLoading: projectsLoading } = useServerProjects();
  const { data: pipelinesData, isLoading: pipelinesLoading } = useServerProjectPipelines(projectId);
  const { mutateAsync: updateNode } = useUpdateNode();
  const { mutateAsync: updatePipeline } = useUpdatePipeline();

  const projects = projectsData?.projects ?? [];
  const pipelineNames = useMemo(
    () => Object.keys(pipelinesData?.pipelines ?? {}).sort(),
    [pipelinesData]
  );
  const pipelineSpec = pipelinesData?.pipelines?.[pipelineName];

  const nameError =
    nodeName && !NODE_NAME_RE.test(nodeName)
      ? "Must start with a letter or _, using only letters, numbers, - or _."
      : undefined;
  const sourceReady = mode === "table" ? Boolean(table.trim()) : Boolean(query.trim());
  const canCreate = Boolean(projectId && pipelineName && nodeName && !nameError && sourceReady && !saving);

  const handleCreate = async () => {
    setSaving(true);
    try {
      const spec: Record<string, unknown> = {
        type: "ingestion",
        source: connectionName,
        description: `Ingest from '${connectionName}' (${mode})`,
      };
      if (mode === "table") {
        spec.table = table.trim();
        if (where.trim()) spec.where = where.trim();
      } else {
        spec.query = query.trim();
      }

      await updateNode({ name: nodeName, spec, pipeline: pipelineName });
      const currentNodes: string[] = Array.isArray(pipelineSpec?.nodes) ? pipelineSpec.nodes : [];
      if (!currentNodes.includes(nodeName)) {
        await updatePipeline({
          projectId,
          name: pipelineName,
          spec: { ...(pipelineSpec ?? {}), nodes: [...currentNodes, nodeName] },
        });
      }
      toastStore
        .getState()
        .show(`Ingestion node "${nodeName}" added to pipeline "${pipelineName}"`, "success");
      onClose();
      navigate(routes.pipeline(projectId, pipelineName));
    } catch (e) {
      toastStore.getState().show(apiErrorMessage(e, "Failed to create ingestion node"), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`Use '${connectionName}' in a pipeline`} onClose={onClose} width={560}>
      <div style={{ display: "grid", gap: 14 }}>
        <p style={{ margin: 0, fontSize: 12, color: colors.textMuted }}>
          Creates a declarative <code>type: ingestion</code> node — Ducta owns the JDBC
          connection and Spark read, no Python needed. Wire its <code>output</code> dataset
          later from the node's I/O tab if you want the result persisted.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <span style={label}>Project</span>
            <select
              style={input}
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                setPipelineName("");
              }}
              disabled={projectsLoading}
            >
              <option value="">{projectsLoading ? "Loading…" : "Select project…"}</option>
              {projects.map((p: { id: string; name?: string }) => (
                <option key={p.id} value={p.id}>
                  {p.name ?? p.id}
                </option>
              ))}
            </select>
          </div>
          <div>
            <span style={label}>Pipeline</span>
            <select
              style={input}
              value={pipelineName}
              onChange={(e) => setPipelineName(e.target.value)}
              disabled={!projectId || pipelinesLoading}
            >
              <option value="">
                {!projectId ? "Pick a project first" : pipelinesLoading ? "Loading…" : "Select pipeline…"}
              </option>
              {pipelineNames.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <span style={label}>Node name</span>
          <input style={input} value={nodeName} onChange={(e) => setNodeName(e.target.value)} />
          {nameError && (
            <span style={{ fontSize: 11, color: colors.danger }}>{nameError}</span>
          )}
        </div>

        <div>
          <span style={label}>Read from</span>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            {(["table", "query"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                style={{
                  padding: "4px 10px",
                  borderRadius: 5,
                  border: `1px solid ${mode === m ? colors.accent : colors.border}`,
                  background: mode === m ? `${colors.accent}12` : "transparent",
                  color: mode === m ? colors.accent : colors.textMuted,
                  cursor: "pointer",
                  fontSize: 11,
                  fontWeight: mode === m ? 600 : 400,
                }}
              >
                {m === "table" ? "Table" : "SQL query"}
              </button>
            ))}
          </div>

          {mode === "table" ? (
            <div style={{ display: "grid", gap: 8 }}>
              <input
                style={input}
                value={table}
                onChange={(e) => setTable(e.target.value)}
                placeholder="schema.table_name"
              />
              <input
                style={input}
                value={where}
                onChange={(e) => setWhere(e.target.value)}
                placeholder="WHERE filter (optional), e.g. country = 'US'"
              />
            </div>
          ) : (
            <textarea
              style={{ ...input, minHeight: 80, resize: "vertical" }}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="SELECT id, amount FROM sales WHERE created_at >= '2026-01-01'"
            />
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleCreate}
            disabled={!canCreate}
            leftIcon={<IconPlus size={15} />}
          >
            {saving ? "Creating…" : "Create node"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
